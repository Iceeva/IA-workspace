"""Stockage objet. S3 compatible (AWS, R2, MinIO) en production ; disque local pour le développement."""
import os
from abc import ABC, abstractmethod
from pathlib import Path


class Storage(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    @abstractmethod
    async def get(self, key: str) -> bytes: ...
    @abstractmethod
    async def delete(self, key: str) -> None: ...


class LocalStorage(Storage):
    """Développement uniquement : le disque d'une fonction serverless n'est pas persistant."""
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _p(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError("clé hors de la racine de stockage")
        return p

    async def put(self, key, data, content_type):
        p = self._p(key); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)

    async def get(self, key):
        return self._p(key).read_bytes()

    async def delete(self, key):
        self._p(key).unlink(missing_ok=True)


class S3Storage(Storage):
    def __init__(self, bucket: str, access_key: str, secret_key: str, endpoint: str | None):
        import boto3  # import tardif
        self.bucket = bucket
        self.s3 = boto3.client("s3", aws_access_key_id=access_key, aws_secret_access_key=secret_key,
                               endpoint_url=endpoint or None)

    async def put(self, key, data, content_type):
        import asyncio
        await asyncio.to_thread(self.s3.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    async def get(self, key):
        import asyncio
        r = await asyncio.to_thread(self.s3.get_object, Bucket=self.bucket, Key=key)
        return r["Body"].read()

    async def delete(self, key):
        import asyncio
        await asyncio.to_thread(self.s3.delete_object, Bucket=self.bucket, Key=key)


class StorageConfigError(RuntimeError):
    pass


def make_storage() -> Storage:
    prov = os.getenv("STORAGE_PROVIDER", "").lower()
    if prov == "local":
        return LocalStorage(os.getenv("STORAGE_LOCAL_DIR", "./.storage"))
    if prov == "s3":
        missing = [k for k in ("STORAGE_BUCKET", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY") if not os.getenv(k)]
        if missing:
            raise StorageConfigError("Variables manquantes: " + ", ".join(missing))
        return S3Storage(os.environ["STORAGE_BUCKET"], os.environ["STORAGE_ACCESS_KEY"],
                         os.environ["STORAGE_SECRET_KEY"], os.getenv("STORAGE_ENDPOINT_URL"))
    raise StorageConfigError("STORAGE_PROVIDER doit valoir 's3' ou 'local'")
