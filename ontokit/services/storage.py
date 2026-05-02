"""Storage service for MinIO object storage integration."""

import asyncio
from io import BytesIO
from typing import Any

from minio import Minio
from minio.error import S3Error

from ontokit.core.config import settings


class StorageError(Exception):
    """Exception raised for storage operation errors."""

    pass


def _read_and_release(response: Any) -> bytes:
    # urllib3's release_conn() can do socket I/O; combine with read() so the
    # whole response lifecycle stays off the event loop.
    try:
        data: bytes = response.read()
        return data
    finally:
        response.close()
        response.release_conn()


class StorageService:
    """Service for interacting with MinIO object storage."""

    def __init__(self) -> None:
        self.client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket = settings.minio_bucket

    async def ensure_bucket_exists(self) -> None:
        """Ensure the bucket exists, creating it if necessary."""
        try:
            # MinIO's Python client is synchronous (urllib3); run in a thread
            # so it never blocks the asyncio event loop.
            exists = await asyncio.to_thread(self.client.bucket_exists, self.bucket)
            if not exists:
                await asyncio.to_thread(self.client.make_bucket, self.bucket)
        except S3Error as e:
            raise StorageError(f"Failed to ensure bucket exists: {e}") from e

    async def upload_file(self, object_name: str, data: bytes, content_type: str) -> str:
        """
        Upload a file to MinIO storage.

        Args:
            object_name: The object name/path in the bucket
            data: The file content as bytes
            content_type: The MIME type of the file

        Returns:
            The full path to the stored object

        Raises:
            StorageError: If the upload fails
        """
        try:
            await self.ensure_bucket_exists()
            await asyncio.to_thread(
                self.client.put_object,
                bucket_name=self.bucket,
                object_name=object_name,
                data=BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return f"{self.bucket}/{object_name}"
        except S3Error as e:
            raise StorageError(f"Failed to upload file: {e}") from e

    async def download_file(self, object_name: str) -> bytes:
        """
        Download a file from MinIO storage.

        Args:
            object_name: The object name/path in the bucket

        Returns:
            The file content as bytes

        Raises:
            StorageError: If the download fails
        """
        try:
            response = await asyncio.to_thread(
                self.client.get_object,
                bucket_name=self.bucket,
                object_name=object_name,
            )
            return await asyncio.to_thread(_read_and_release, response)
        except S3Error as e:
            raise StorageError(f"Failed to download file: {e}") from e

    async def delete_file(self, object_name: str) -> None:
        """
        Delete a file from MinIO storage.

        Args:
            object_name: The object name/path in the bucket

        Raises:
            StorageError: If the deletion fails
        """
        try:
            await asyncio.to_thread(
                self.client.remove_object,
                bucket_name=self.bucket,
                object_name=object_name,
            )
        except S3Error as e:
            raise StorageError(f"Failed to delete file: {e}") from e

    async def file_exists(self, object_name: str) -> bool:
        """
        Check if a file exists in MinIO storage.

        Args:
            object_name: The object name/path in the bucket

        Returns:
            True if the file exists, False otherwise
        """
        try:
            await asyncio.to_thread(
                self.client.stat_object,
                bucket_name=self.bucket,
                object_name=object_name,
            )
            return True
        except S3Error:
            return False


def get_storage_service() -> StorageService:
    """Factory function for dependency injection."""
    return StorageService()
