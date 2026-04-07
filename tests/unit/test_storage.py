"""Tests for StorageService (ontokit/services/storage.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import urllib3
from minio.error import S3Error

from ontokit.services.storage import StorageError, StorageService


def _make_s3_error(code: str = "TestError", message: str = "test") -> S3Error:
    """Create an S3Error with a properly mocked BaseHTTPResponse."""
    mock_response = MagicMock(spec=urllib3.BaseHTTPResponse)
    return S3Error(mock_response, code, message, "resource", "request-id", "host-id")


@pytest.fixture
def mock_minio_client() -> MagicMock:
    """Create a mock MinIO client."""
    return MagicMock()


@pytest.fixture
def storage(mock_minio_client: MagicMock) -> StorageService:
    """Create a StorageService with a mocked MinIO client."""
    with patch("ontokit.services.storage.Minio", return_value=mock_minio_client):
        svc = StorageService()
    svc.client = mock_minio_client
    svc.bucket = "test-bucket"
    return svc


class TestEnsureBucketExists:
    """Tests for ensure_bucket_exists()."""

    @pytest.mark.asyncio
    async def test_creates_bucket_when_missing(
        self, storage: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Creates the bucket when it does not exist."""
        mock_minio_client.bucket_exists.return_value = False
        await storage.ensure_bucket_exists()
        mock_minio_client.make_bucket.assert_called_once_with("test-bucket")

    @pytest.mark.asyncio
    async def test_skips_creation_when_exists(
        self, storage: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Does not create the bucket when it already exists."""
        mock_minio_client.bucket_exists.return_value = True
        await storage.ensure_bucket_exists()
        mock_minio_client.make_bucket.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_storage_error_on_s3_failure(
        self, storage: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Raises StorageError when S3Error occurs."""
        mock_minio_client.bucket_exists.side_effect = _make_s3_error()
        with pytest.raises(StorageError, match="Failed to ensure bucket exists"):
            await storage.ensure_bucket_exists()


class TestUploadFile:
    """Tests for upload_file()."""

    @pytest.mark.asyncio
    async def test_uploads_and_returns_path(
        self, storage: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Uploads data and returns the full object path."""
        mock_minio_client.bucket_exists.return_value = True
        result = await storage.upload_file("path/to/file.ttl", b"data", "text/turtle")
        assert result == "test-bucket/path/to/file.ttl"
        mock_minio_client.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_storage_error_on_failure(
        self, storage: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Raises StorageError when upload fails."""
        mock_minio_client.bucket_exists.return_value = True
        mock_minio_client.put_object.side_effect = _make_s3_error()
        with pytest.raises(StorageError, match="Failed to upload file"):
            await storage.upload_file("obj", b"data", "text/plain")


class TestDownloadFile:
    """Tests for download_file()."""

    @pytest.mark.asyncio
    async def test_downloads_and_returns_bytes(
        self, storage: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Downloads file content and returns bytes."""
        response_mock = MagicMock()
        response_mock.read.return_value = b"file content"
        mock_minio_client.get_object.return_value = response_mock

        result = await storage.download_file("path/to/file.ttl")
        assert result == b"file content"
        response_mock.close.assert_called_once()
        response_mock.release_conn.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_storage_error_on_failure(
        self, storage: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Raises StorageError when download fails."""
        mock_minio_client.get_object.side_effect = _make_s3_error()
        with pytest.raises(StorageError, match="Failed to download file"):
            await storage.download_file("missing.ttl")


class TestDeleteFile:
    """Tests for delete_file()."""

    @pytest.mark.asyncio
    async def test_deletes_object(
        self, storage: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Calls remove_object on the MinIO client."""
        await storage.delete_file("path/to/file.ttl")
        mock_minio_client.remove_object.assert_called_once_with(
            bucket_name="test-bucket", object_name="path/to/file.ttl"
        )

    @pytest.mark.asyncio
    async def test_raises_storage_error_on_failure(
        self, storage: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Raises StorageError when deletion fails."""
        mock_minio_client.remove_object.side_effect = _make_s3_error()
        with pytest.raises(StorageError, match="Failed to delete file"):
            await storage.delete_file("file.ttl")


class TestFileExists:
    """Tests for file_exists()."""

    @pytest.mark.asyncio
    async def test_returns_true_when_exists(
        self, storage: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Returns True when stat_object succeeds."""
        mock_minio_client.stat_object.return_value = MagicMock()
        result = await storage.file_exists("path/to/file.ttl")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(
        self, storage: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Returns False when stat_object raises S3Error."""
        mock_minio_client.stat_object.side_effect = _make_s3_error()
        result = await storage.file_exists("missing.ttl")
        assert result is False
