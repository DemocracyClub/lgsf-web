"""
Running embed_documents on AWS Batch.

`embed_documents --remote` builds the tasks from the database, splits
them into shards (of about SHARD_BYTES each, unless --shards says how
many), and uploads them as a manifest:

    s3://<LGSF_DATA_BUCKET>/<EMBEDDINGS_RUNS_PREFIX><run id>/run.json
    s3://<LGSF_DATA_BUCKET>/<EMBEDDINGS_RUNS_PREFIX><run id>/shard-00000.jsonl
    ...

and submits one Batch job: an array job with a child for each shard, or
a plain job for one shard (Batch's smallest array is 2). Each child runs
`embed_documents --manifest s3://.../<run id>/ --source s3`, and reads
the shard numbered by AWS_BATCH_JOB_ARRAY_INDEX. The workers never
query the database.

The job queue and job definition are made by
cdk_stacks/stacks/embeddings_batch.py.
"""

import datetime
import math
import os
import secrets
import subprocess
from pathlib import Path

from embeddings.tasks import RUN_NAME, SHARD_NAME

#: When --shards isn't given, the files are split into shards of about
#: this many bytes. In October 2026 a g6.xlarge did 83MB of documents
#: (1,427 pages) in 534 seconds, so a shard is about ten minutes' work.
#: That's long enough that starting a child is a small part of it (a
#: 20-file run took 31 seconds in all), and short enough that Batch
#: shares the children out evenly between instances, and the last ones
#: don't keep the run going long after the rest have finished.
SHARD_BYTES = 100_000_000

#: Batch's largest array job.
MAX_SHARDS = 10_000


def new_run_id() -> str:
    now = datetime.datetime.now(datetime.UTC)
    return f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def array_index() -> int:
    """Which shard this Batch job, or array child, runs."""
    return int(os.environ.get("AWS_BATCH_JOB_ARRAY_INDEX", "0"))


def shard_count(tasks) -> int:
    """How many shards to split tasks into, if --shards isn't given."""
    size = sum(task.content_length for task in tasks)
    return max(1, min(math.ceil(size / SHARD_BYTES), len(tasks), MAX_SHARDS))


def manifest_url(bucket: str, prefix: str, run_id: str) -> str:
    return f"s3://{bucket}/{prefix}{run_id}/"


def upload_manifest(directory: Path, bucket: str, prefix: str, run_id: str):
    """Upload the shard files and run.json that write_manifest() wrote."""
    import boto3

    client = boto3.client("s3")
    names = sorted(
        path.name
        for path in directory.iterdir()
        if path.name == RUN_NAME
        or path.match(SHARD_NAME.replace("{index:05d}", "*"))
    )
    for name in names:
        client.upload_file(
            str(directory / name), bucket, f"{prefix}{run_id}/{name}"
        )
    return manifest_url(bucket, prefix, run_id)


def job_request(
    run_id: str,
    url: str,
    shards: int,
    job_queue: str,
    job_definition: str,
    arguments: list[str],
) -> dict:
    """
    The SubmitJob request. `arguments` are passed on to each worker's
    embed_documents, after --manifest and --source.
    """
    request = {
        "jobName": f"embed-documents-{run_id}",
        "jobQueue": job_queue,
        "jobDefinition": job_definition,
        "containerOverrides": {
            "command": [
                "python",
                "manage.py",
                "embed_documents",
                "--manifest",
                url,
                "--source",
                "s3",
                *arguments,
            ]
        },
    }
    if shards >= 2:
        request["arrayProperties"] = {"size": shards}
    return request


def submit_job(request: dict) -> str:
    import boto3

    return boto3.client("batch").submit_job(**request)["jobId"]
