from functools import cache
from urllib.parse import urlparse

import boto3
from django.conf import settings
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

INDEX_NAME = "lgsf"
CHUNK = "chunk"
DECISION = "decision"
SEARCH_PIPELINE = "lgsf-hybrid"


@cache
def opensearch_client():
    http_auth = settings.OPENSEARCH_HTTP_AUTH
    extra = {}
    host = urlparse(settings.OPENSEARCH_URL).hostname or ""
    if host.endswith(".aoss.amazonaws.com"):
        # OpenSearch Serverless needs SigV4-signed requests.
        http_auth = AWSV4SignerAuth(
            boto3.Session().get_credentials(),
            settings.AWS_REGION,
            "aoss",
        )
        extra = {"connection_class": RequestsHttpConnection}

    return OpenSearch(
        hosts=[settings.OPENSEARCH_URL],
        http_auth=http_auth,
        verify_certs=settings.OPENSEARCH_VERIFY_TLS,
        ssl_show_warn=settings.OPENSEARCH_VERIFY_TLS,
        **extra,
    )
