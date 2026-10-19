"""
AWS Batch, for `manage.py embed_documents --remote`.

The command uploads a manifest of tasks to
s3://lgsf-data-archive/embedding-runs/<run id>/ and submits a job to the
queue here, with a child job for each shard. Each one runs the image
built from Dockerfile.embeddings, reads its documents from the bucket
and writes the sidecar files back next to them.

Only for the development environment. Deploy it by hand, as the image
is several GB and CircleCI doesn't build it:

    DC_ENVIRONMENT=development npx cdk deploy LGSFEmbeddingsBatch

The instances are GPU ones (g6/g5) unless the context says otherwise:

    DC_ENVIRONMENT=development npx cdk deploy LGSFEmbeddingsBatch \\
        -c embeddings-instances=cpu
"""

from dataclasses import dataclass

from aws_cdk import Duration, Size, Stack
from aws_cdk import aws_batch as batch
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from constructs import Construct

DATA_BUCKET = "lgsf-data-archive"
RUNS_PREFIX = "embedding-runs/"

#: The names embed_documents submits to, by default. See
#: EMBEDDINGS_BATCH_JOB_QUEUE and EMBEDDINGS_BATCH_JOB_DEFINITION.
JOB_QUEUE_NAME = "lgsf-embeddings"
JOB_DEFINITION_NAME = "lgsf-embeddings"

TITAN_V2 = (
    "arn:aws:bedrock:eu-west-2::foundation-model/amazon.titan-embed-text-v2:0"
)

#: The most vCPUs running at once. Each shard embeds from 8 threads, and
#: Titan's default quota is 2,000 requests a minute for the account, so
#: this also limits how hard the jobs together use Bedrock. Raise it with
#: the quota in mind.
MAX_VCPUS = 32


@dataclass
class Instances:
    """The instances jobs run on, and what each job asks for."""

    instance_types: list[str]
    image_type: batch.EcsMachineImageType
    hardware_type: ecs.AmiHardwareType
    #: The Dockerfile.embeddings dependency group.
    dependency_group: str
    vcpus: int
    #: Less than the instance's memory, which ECS keeps some of.
    memory_gib: int
    gpus: int


INSTANCES = {
    # One NVIDIA L4 (g6) or A10G (g5), with 4 or 8 vCPUs. The job's
    # numbers fit the smaller of each.
    "gpu": Instances(
        instance_types=["g6.xlarge", "g6.2xlarge", "g5.xlarge", "g5.2xlarge"],
        image_type=batch.EcsMachineImageType.ECS_AL2023_NVIDIA,
        hardware_type=ecs.AmiHardwareType.GPU,
        dependency_group="embeddings-gpu",
        vcpus=4,
        memory_gib=14,
        gpus=1,
    ),
    # 16 vCPUs and 32 GiB.
    "cpu": Instances(
        instance_types=["c7i.4xlarge", "c7a.4xlarge"],
        image_type=batch.EcsMachineImageType.ECS_AL2023,
        hardware_type=ecs.AmiHardwareType.STANDARD,
        dependency_group="embeddings",
        vcpus=16,
        memory_gib=30,
        gpus=0,
    ),
}


class EmbeddingsBatch(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        kind = self.node.try_get_context("embeddings-instances") or "gpu"
        assert kind in INSTANCES, (
            f"context `embeddings-instances` must be one of {list(INSTANCES)}"
        )
        instances = INSTANCES[kind]

        vpc = ec2.Vpc.from_lookup(self, "default-vpc-id", is_default=True)

        image = ecr_assets.DockerImageAsset(
            self,
            "embeddings-image-id",
            directory=".",
            file="Dockerfile.embeddings",
            platform=ecr_assets.Platform.LINUX_AMD64,
            build_args={"GROUP": instances.dependency_group},
        )

        compute_environment = batch.ManagedEc2EcsComputeEnvironment(
            self,
            "embeddings-compute-environment-id",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_types=[
                ec2.InstanceType(name) for name in instances.instance_types
            ],
            use_optimal_instance_classes=False,
            images=[
                batch.EcsMachineImage(
                    image=ecs.EcsOptimizedImage.amazon_linux2023(
                        hardware_type=instances.hardware_type
                    ),
                    image_type=instances.image_type,
                )
            ],
            spot=True,
            allocation_strategy=batch.AllocationStrategy.SPOT_PRICE_CAPACITY_OPTIMIZED,
            # Nothing runs between jobs.
            minv_cpus=0,
            maxv_cpus=MAX_VCPUS,
            launch_template=self.create_launch_template(),
        )

        job_queue = batch.JobQueue(
            self,
            "embeddings-job-queue-id",
            job_queue_name=JOB_QUEUE_NAME,
            compute_environments=[
                batch.OrderedComputeEnvironment(
                    compute_environment=compute_environment, order=1
                )
            ],
        )

        container = batch.EcsEc2ContainerDefinition(
            self,
            "embeddings-container-id",
            image=ecs.ContainerImage.from_docker_image_asset(image),
            cpu=instances.vcpus,
            memory=Size.gibibytes(instances.memory_gib),
            gpu=instances.gpus or None,
            job_role=self.create_job_role(),
            environment={
                # base, not deploy, which asks EC2 instance metadata for
                # the web server's IP when it's imported, or dev, which
                # needs debug_toolbar.
                "DJANGO_SETTINGS_MODULE": "lgsf_web.settings.base",
                "AWS_DEFAULT_REGION": "eu-west-2",
            },
            command=["python", "manage.py", "embed_documents", "--help"],
        )

        batch.EcsJobDefinition(
            self,
            "embeddings-job-definition-id",
            job_definition_name=JOB_DEFINITION_NAME,
            container=container,
            timeout=Duration.hours(12),
            retry_attempts=3,
            retry_strategies=[
                # A Spot instance taken back ("Host EC2 (instance ...)
                # terminated"). The next attempt skips what this one
                # finished, as each document's status.json says.
                batch.RetryStrategy.of(
                    batch.Action.RETRY, batch.Reason.SPOT_INSTANCE_RECLAIMED
                ),
                # Anything else is a problem to look at, not retry.
                batch.RetryStrategy.of(
                    batch.Action.EXIT, batch.Reason.custom(on_reason="*")
                ),
            ],
        )

        self.job_queue = job_queue

    def create_launch_template(self) -> ec2.LaunchTemplate:
        # The image is several GB, more than the AMI's root volume leaves
        # room for.
        return ec2.LaunchTemplate(
            self,
            "embeddings-launch-template-id",
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        100, volume_type=ec2.EbsDeviceVolumeType.GP3
                    ),
                )
            ],
        )

    def create_job_role(self) -> iam.Role:
        role = iam.Role(
            self,
            "embeddings-job-role-id",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[
                    f"arn:aws:s3:::{DATA_BUCKET}/data/*/Decisions/documents/*",
                    f"arn:aws:s3:::{DATA_BUCKET}/{RUNS_PREFIX}*",
                ],
            )
        )
        # Listing a council's documents needs this, and without it a
        # HeadObject of a missing key is a 403 rather than a 404.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:ListBucket"],
                resources=[f"arn:aws:s3:::{DATA_BUCKET}"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"], resources=[TITAN_V2]
            )
        )
        return role
