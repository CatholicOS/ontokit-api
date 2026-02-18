"""Storage service for MinIO object storage integration."""

from io import BytesIO

from minio import Minio
from minio.error import S3Error

from axigraph.core.config import settings


class StorageError(Exception):
    """Exception raised for storage operation errors."""

    pass


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
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
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
            self.client.put_object(
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
            response = self.client.get_object(
                bucket_name=self.bucket,
                object_name=object_name,
            )
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
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
            self.client.remove_object(
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
            self.client.stat_object(
                bucket_name=self.bucket,
                object_name=object_name,
            )
            return True
        except S3Error:
            return False


def get_storage_service() -> StorageService:
    """Factory function for dependency injection."""
    return StorageService()
