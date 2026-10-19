"""Stand-ins shared by the tests."""

import hashlib
import io
from pathlib import Path

from embeddings.embedders import EmbedderBase, Embedding


class FakeEmbedder(EmbedderBase):
    """Vectors made from each text's hash, keeping every text it's sent."""

    name = "fake"
    model = "fake-model-1"
    dimensions = 4

    def __init__(self):
        self.texts = []

    def vector(self, text):
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [byte / 255 for byte in digest[: self.dimensions]]

    def embed_documents(self, texts):
        self.texts.extend(texts)
        return [
            Embedding(vector=self.vector(text), token_count=len(text.split()))
            for text in texts
        ]

    def embed_query(self, text):
        return self.vector(text)


class FakeS3Client:
    """
    The calls S3Store makes, against a dict of keys. Each response has
    only the fields S3Store reads.
    """

    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self):
        self.objects = {}
        self.calls = []

    def _not_found(self, operation):
        from botocore.exceptions import ClientError

        return ClientError({"Error": {"Code": "404"}}, operation)

    def head_object(self, Bucket, Key):
        self.calls.append(("head_object", Key))
        if (Bucket, Key) not in self.objects:
            raise self._not_found("HeadObject")
        return {}

    def get_object(self, Bucket, Key):
        self.calls.append(("get_object", Key))
        if (Bucket, Key) not in self.objects:
            raise self.exceptions.NoSuchKey(Key)
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body):
        self.calls.append(("put_object", Key))
        self.objects[(Bucket, Key)] = bytes(Body)

    def copy(self, CopySource, Bucket, Key):
        self.calls.append(("copy", CopySource["Key"], Key))
        self.objects[(Bucket, Key)] = self.objects[
            (CopySource["Bucket"], CopySource["Key"])
        ]

    def download_file(self, Bucket, Key, Filename):
        self.calls.append(("download_file", Key))
        if (Bucket, Key) not in self.objects:
            raise self._not_found("HeadObject")
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])

    def get_paginator(self, operation):
        assert operation == "list_objects_v2"
        client = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                client.calls.append(("list_objects_v2", Prefix))
                keys = sorted(
                    key
                    for bucket, key in client.objects
                    if bucket == Bucket and key.startswith(Prefix)
                )
                # Two keys a page, to check the pages are joined.
                for start in range(0, max(len(keys), 1), 2):
                    page = keys[start : start + 2]
                    yield {"Contents": [{"Key": key} for key in page]}

        return Paginator()
