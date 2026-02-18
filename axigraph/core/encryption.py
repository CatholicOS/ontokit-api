"""Fernet encryption helpers for storing sensitive tokens at rest."""

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status

from axigraph.core.config import settings


def get_fernet() -> Fernet:
    """Get a Fernet instance using the configured encryption key.

    Raises:
        HTTPException: 500 if the encryption key is not configured.
    """
    key = settings.github_token_encryption_key
    if not key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub token encryption key is not configured",
        )
    return Fernet(key.encode())


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token string using Fernet symmetric encryption."""
    f = get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted token string.

    Raises:
        HTTPException: 500 if the ciphertext is invalid or the key has changed.
    """
    f = get_fernet()
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt token — encryption key may have changed",
        ) from e
