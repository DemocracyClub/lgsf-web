import os

from aws_cdk import App, Environment, Tags

from cdk_stacks.stacks.code_deploy import CodeDeployment
from cdk_stacks.stacks.embeddings_batch import EmbeddingsBatch

valid_environments = (
    "development",
    "staging",
    "production",
)

app_wide_context = {}
if dc_env := os.environ.get("DC_ENVIRONMENT"):
    app_wide_context["dc-environment"] = dc_env

app = App(context=app_wide_context)

env = Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region="eu-west-2")

# Set the DC Environment early on. This is important to be able to conditionally
# change the stack configurations
dc_environment = app.node.try_get_context("dc-environment") or None
assert dc_environment in valid_environments, (
    f"context `dc-environment` must be one of {valid_environments}"
)


CodeDeployment(app, "LGSFCodeDeployment", env=env)

# For `manage.py embed_documents --remote`. Deployed by hand: see
# cdk_stacks/stacks/embeddings_batch.py.
if dc_environment == "development":
    EmbeddingsBatch(app, "LGSFEmbeddingsBatch", env=env)


Tags.of(app).add("dc-product", "lgsf")
Tags.of(app).add("dc-environment", dc_environment)

app.synth()
