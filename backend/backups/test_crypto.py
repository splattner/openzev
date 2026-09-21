"""Encryption envelope and destination-secret tests (ADR 0024)."""

import io
import os

from django.test import SimpleTestCase, override_settings

from backups import crypto

KEY_A = "A" * 40
KEY_B = "B" * 40


def roundtrip(data: bytes, chunk_size: int = 16) -> bytes:
    sealed = io.BytesIO()
    crypto.encrypt_stream(io.BytesIO(data), sealed, chunk_size=chunk_size)
    sealed.seek(0)
    plain = io.BytesIO()
    crypto.decrypt_stream(sealed, plain)
    return plain.getvalue()


def seal(data: bytes, chunk_size: int = 16) -> bytes:
    sealed = io.BytesIO()
    crypto.encrypt_stream(io.BytesIO(data), sealed, chunk_size=chunk_size)
    return sealed.getvalue()


def unseal(raw: bytes) -> bytes:
    plain = io.BytesIO()
    crypto.decrypt_stream(io.BytesIO(raw), plain)
    return plain.getvalue()


@override_settings(BACKUP_ENCRYPTION_KEYS=[KEY_A])
class EncryptionEnvelopeTests(SimpleTestCase):
    def test_a_multi_chunk_archive_round_trips(self):
        data = os.urandom(1000)
        self.assertEqual(roundtrip(data), data)

    def test_an_exact_multiple_of_the_chunk_size_round_trips(self):
        """The last full chunk must still be marked final, not followed by an empty one."""
        data = os.urandom(64)
        self.assertEqual(roundtrip(data, chunk_size=16), data)

    def test_an_empty_archive_round_trips(self):
        self.assertEqual(roundtrip(b""), b"")

    def test_output_is_larger_than_the_chunk_size_and_split_into_chunks(self):
        sealed = seal(os.urandom(100), chunk_size=16)
        # magic + header + 7 chunks (6 full, 1 partial), each with a length prefix and tag
        self.assertGreater(len(sealed), 100 + 7 * 20)
        self.assertTrue(sealed.startswith(crypto.MAGIC))

    def test_ciphertext_does_not_contain_the_plaintext(self):
        secret = b"plaintext-client-secret-value"
        self.assertNotIn(secret, seal(secret * 4, chunk_size=64))

    def test_a_truncated_archive_fails_authentication(self):
        sealed = seal(os.urandom(200), chunk_size=16)
        # Drop the whole last chunk: every remaining chunk is individually valid,
        # so only the final-chunk flag can catch this.
        chunk_bytes = 4 + (200 % 16 or 16) + 16  # length prefix + last partial chunk + tag
        with self.assertRaises(crypto.BackupEnvelopeError):
            unseal(sealed[:-chunk_bytes])

    def test_a_reordered_chunk_fails_authentication(self):
        chunk_size = 16
        sealed = bytearray(seal(os.urandom(chunk_size * 4), chunk_size=chunk_size))
        header_length = int.from_bytes(sealed[5:9], "big")
        start = 9 + header_length
        stride = 4 + chunk_size + 16
        first = bytes(sealed[start : start + stride])
        second = bytes(sealed[start + stride : start + 2 * stride])
        sealed[start : start + 2 * stride] = second + first
        with self.assertRaises(crypto.BackupEnvelopeError):
            unseal(bytes(sealed))

    def test_a_flipped_bit_fails_authentication(self):
        sealed = bytearray(seal(os.urandom(64), chunk_size=16))
        sealed[-1] ^= 0x01
        with self.assertRaises(crypto.BackupEnvelopeError):
            unseal(bytes(sealed))

    def test_an_edited_header_fails_authentication(self):
        sealed = bytearray(seal(os.urandom(64), chunk_size=16))
        # Flip a byte inside the nonce_prefix hex in the JSON header.
        marker = sealed.index(b"nonce_prefix") + len(b'nonce_prefix": "')
        sealed[marker] = ord("0") if sealed[marker] != ord("0") else ord("1")
        with self.assertRaises(crypto.BackupEnvelopeError):
            unseal(bytes(sealed))

    def test_not_an_envelope_is_refused(self):
        with self.assertRaises(crypto.BackupEnvelopeError):
            unseal(b"PK\x03\x04 a plain zip")

    def test_the_wrong_key_is_refused_and_the_required_fingerprint_named(self):
        sealed = seal(b"secret data")
        expected = crypto.key_fingerprint(KEY_A)
        with override_settings(BACKUP_ENCRYPTION_KEYS=[KEY_B]):
            with self.assertRaises(crypto.BackupKeyMissing) as raised:
                unseal(sealed)
        self.assertEqual(raised.exception.fingerprint, expected)
        self.assertIn(expected, str(raised.exception))

    def test_an_archive_written_with_an_old_key_still_opens_after_rotation(self):
        sealed = seal(b"written before the rotation")
        with override_settings(BACKUP_ENCRYPTION_KEYS=[KEY_B, KEY_A]):
            self.assertEqual(unseal(sealed), b"written before the rotation")
            # New archives use the first key.
            self.assertEqual(crypto.active_fingerprint(), crypto.key_fingerprint(KEY_B))

    def test_no_key_configured_refuses_to_encrypt(self):
        with override_settings(BACKUP_ENCRYPTION_KEYS=[]):
            with self.assertRaises(crypto.BackupKeysNotConfigured):
                crypto.encrypt_stream(io.BytesIO(b"x"), io.BytesIO())

    def test_a_short_key_is_rejected(self):
        with override_settings(BACKUP_ENCRYPTION_KEYS=["too-short"]):
            with self.assertRaises(crypto.BackupKeyRejected):
                crypto.configured_keys()

    def test_is_encrypted_detects_the_magic_and_leaves_the_position(self):
        sealed = io.BytesIO(seal(b"abc"))
        self.assertTrue(crypto.is_encrypted(sealed))
        self.assertEqual(sealed.tell(), 0)
        self.assertFalse(crypto.is_encrypted(io.BytesIO(b"PK\x03\x04")))

    def test_a_key_that_encrypts_the_archive_derives_a_different_secret_key(self):
        """Domain separation: the same configured string must not produce the same
        key for archives and for destination secrets."""
        self.assertNotEqual(
            crypto._derive(KEY_A, crypto._ARCHIVE_INFO),
            crypto._derive(KEY_A, crypto._SECRET_INFO),
        )


class KeyFingerprintTests(SimpleTestCase):
    def test_a_fingerprint_identifies_a_key_without_revealing_it(self):
        fingerprint = crypto.key_fingerprint(KEY_A)
        self.assertEqual(len(fingerprint), 16)
        self.assertNotIn(KEY_A, fingerprint)
        self.assertEqual(fingerprint, crypto.key_fingerprint(KEY_A))
        self.assertNotEqual(fingerprint, crypto.key_fingerprint(KEY_B))

    @override_settings(BACKUP_ENCRYPTION_KEYS=[])
    def test_no_active_fingerprint_without_a_key(self):
        self.assertEqual(crypto.active_fingerprint(), "")
        self.assertFalse(crypto.encryption_configured())


@override_settings(BACKUP_ENCRYPTION_KEYS=[KEY_A])
class DestinationSecretTests(SimpleTestCase):
    def test_a_secret_round_trips(self):
        token = crypto.encrypt_secret("aws-secret-key")
        self.assertNotIn(b"aws-secret-key", token)
        self.assertEqual(crypto.decrypt_secret(token), "aws-secret-key")

    def test_a_secret_encrypted_under_a_retired_key_is_reported_not_garbled(self):
        token = crypto.encrypt_secret("aws-secret-key")
        with override_settings(BACKUP_ENCRYPTION_KEYS=[KEY_B]):
            with self.assertRaises(crypto.BackupKeyMissing):
                crypto.decrypt_secret(token)

    def test_a_secret_survives_key_rotation(self):
        token = crypto.encrypt_secret("aws-secret-key")
        with override_settings(BACKUP_ENCRYPTION_KEYS=[KEY_B, KEY_A]):
            self.assertEqual(crypto.decrypt_secret(token), "aws-secret-key")

    @override_settings(BACKUP_ENCRYPTION_KEYS=[])
    def test_a_secret_cannot_be_stored_without_a_key(self):
        with self.assertRaises(crypto.BackupKeysNotConfigured):
            crypto.encrypt_secret("aws-secret-key")
