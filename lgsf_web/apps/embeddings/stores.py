"""
Where documents and their sidecar files are read from and written to:
the local data directory, or the bucket it's a copy of.

Both stores take keys relative to the data directory, such as
"MAN/Decisions/documents/2026-08-06-1172-s65106.pdf". In the bucket,
that's under the data/ prefix.

A store is handed to worker processes, so S3Store makes its boto3
client when it's first used, and leaves it out when it's pickled.
"""

import os
import shutil
from enum import StrEnum
from pathlib import Path


class Source(StrEnum):
    LOCAL = "local"
    S3 = "s3"


class LocalStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def __repr__(self):
        return f"LocalStore({str(self.root)!r})"

    def path(self, key: str) -> Path:
        return self.root / key

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def list_prefix(self, prefix: str) -> list[str]:
        """
        Every key starting with `prefix`. Only a directory's files are
        listed, not those in directories below it.
        """
        directory, _, start = prefix.rpartition("/")
        path = self.path(directory)
        if not path.is_dir():
            return []
        return sorted(
            f"{directory}/{entry.name}" if directory else entry.name
            for entry in os.scandir(path)
            if entry.is_file() and entry.name.startswith(start)
        )

    def read_bytes(self, key: str) -> bytes:
        """Raises FileNotFoundError if there's nothing at `key`."""
        return self.path(key).read_bytes()

    def write_bytes(self, key: str, data: bytes):
        """
        Written to a temporary file that's then renamed over the old one,
        so a run that's stopped never leaves a file half written.
        """
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f"{path.name}.tmp")
        temp.write_bytes(data)
        temp.replace(path)

    def copy(self, source_key: str, target_key: str):
        target = self.path(target_key)
        temp = target.with_name(f"{target.name}.tmp")
        shutil.copyfile(self.path(source_key), temp)
        temp.replace(target)

    def download_to(self, key: str, directory: Path) -> Path:
        """The file's own path: nothing needs downloading."""
        path = self.path(key)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path


class S3Store:
    def __init__(self, bucket: str, prefix: str = "data/"):
        self.bucket = bucket
        self.prefix = prefix
        self._client = None

    def __repr__(self):
        return f"S3Store({self.bucket!r}, {self.prefix!r})"

    def __getstate__(self):
        return {**self.__dict__, "_client": None}

    @property
    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                # One connection for each thread reading statuses.
                config=Config(
                    max_pool_connections=32,
                    retries={"mode": "standard", "max_attempts": 10},
                ),
            )
        return self._client

    def url(self, key: str) -> str:
        return f"s3://{self.bucket}/{self.prefix}{key}"

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=self.prefix + key)
        except ClientError as error:
            if error.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise
        return True

    def list_prefix(self, prefix: str) -> list[str]:
        """
        Every key starting with `prefix`, including any under "directories"
        below it, as S3 has none.
        """
        keys = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=self.bucket, Prefix=self.prefix + prefix
        ):
            keys.extend(
                item["Key"].removeprefix(self.prefix)
                for item in page.get("Contents", [])
            )
        return sorted(keys)

    def read_bytes(self, key: str) -> bytes:
        """Raises FileNotFoundError if there's nothing at `key`."""
        try:
            response = self.client.get_object(
                Bucket=self.bucket, Key=self.prefix + key
            )
        except self.client.exceptions.NoSuchKey:
            raise FileNotFoundError(self.url(key)) from None
        return response["Body"].read()

    def write_bytes(self, key: str, data: bytes):
        """A PUT is written whole or not at all."""
        self.client.put_object(
            Bucket=self.bucket, Key=self.prefix + key, Body=data
        )

    def copy(self, source_key: str, target_key: str):
        self.client.copy(
            {"Bucket": self.bucket, "Key": self.prefix + source_key},
            self.bucket,
            self.prefix + target_key,
        )

    def download_to(self, key: str, directory: Path) -> Path:
        from botocore.exceptions import ClientError

        path = Path(directory) / Path(key).name
        try:
            self.client.download_file(self.bucket, self.prefix + key, str(path))
        except ClientError as error:
            if error.response["Error"]["Code"] in ("404", "NoSuchKey"):
                raise FileNotFoundError(self.url(key)) from None
            raise
        return path
