"""Tests for Fernet encryption helpers (ontokit/core/encryption.py)."""

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from ontokit.core.encryption import decrypt_token, encrypt_token, get_fernet

# A valid Fernet key for testing
TEST_FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure a valid encryption key is set for all tests."""
    monkeypatch.setattr(
        "ontokit.core.encryption.settings",
        type("S", (), {"github_token_encryption_key": TEST_FERNET_KEY})(),
    )


class TestGetFernet:
    """Tests for get_fernet()."""

    def test_returns_fernet_instance(self) -> None:
        """get_fernet returns a Fernet instance when key is configured."""
        f = get_fernet()
        assert isinstance(f, Fernet)

    def test_missing_key_raises_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_fernet raises HTTPException 500 when key is empty."""
        monkeypatch.setattr(
            "ontokit.core.encryption.settings",
            type("S", (), {"github_token_encryption_key": ""})(),
        )
        with pytest.raises(HTTPException) as exc_info:
            get_fernet()
        assert exc_info.value.status_code == 500
        assert "not configured" in str(exc_info.value.detail)

    def test_none_key_raises_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_fernet raises HTTPException 500 when key is None."""
        monkeypatch.setattr(
            "ontokit.core.encryption.settings",
            type("S", (), {"github_token_encryption_key": None})(),
        )
        with pytest.raises(HTTPException) as exc_info:
            get_fernet()
        assert exc_info.value.status_code == 500

    def test_get_fernet_instances_are_compatible(self) -> None:
        """Successive calls produce Fernet instances that can decrypt each other's output."""
        f1 = get_fernet()
        f2 = get_fernet()
        # Both should be valid Fernet instances that can decrypt each other's output
        plaintext = b"cache-test"
        cipher = f1.encrypt(plaintext)
        assert f2.decrypt(cipher) == plaintext


class TestEncryptDecrypt:
    """Tests for encrypt_token() and decrypt_token()."""

    def test_round_trip(self) -> None:
        """Encrypting then decrypting returns the original plaintext."""
        original = "ghp_abc123def456"
        ciphertext = encrypt_token(original)
        assert ciphertext != original
        assert decrypt_token(ciphertext) == original

    def test_round_trip_empty_string(self) -> None:
        """Round-trip works with an empty string."""
        ciphertext = encrypt_token("")
        assert decrypt_token(ciphertext) == ""

    def test_round_trip_unicode(self) -> None:
        """Round-trip works with unicode content."""
        original = "token-with-unicode-\u00e9\u00e8\u00ea"
        assert decrypt_token(encrypt_token(original)) == original

    def test_corrupted_ciphertext_raises_500(self) -> None:
        """Decrypting corrupted ciphertext raises HTTPException 500."""
        with pytest.raises(HTTPException) as exc_info:
            decrypt_token("not-valid-fernet-ciphertext")
        assert exc_info.value.status_code == 500
        assert "decrypt" in str(exc_info.value.detail).lower()

    def test_wrong_key_raises_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Decrypting with a different key raises HTTPException 500."""
        ciphertext = encrypt_token("my-secret-token")

        # Switch to a different key
        different_key = Fernet.generate_key().decode()
        monkeypatch.setattr(
            "ontokit.core.encryption.settings",
            type("S", (), {"github_token_encryption_key": different_key})(),
        )
        with pytest.raises(HTTPException) as exc_info:
            decrypt_token(ciphertext)
        assert exc_info.value.status_code == 500

    def test_encrypt_produces_different_ciphertexts(self) -> None:
        """Each call to encrypt_token produces a different ciphertext (Fernet uses random IV)."""
        plaintext = "same-token"
        c1 = encrypt_token(plaintext)
        c2 = encrypt_token(plaintext)
        assert c1 != c2
        # But both decrypt to the same value
        assert decrypt_token(c1) == plaintext
        assert decrypt_token(c2) == plaintext
