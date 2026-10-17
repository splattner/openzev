"""Software WebAuthn ceremonies shared by authentication regression tests."""

import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url

REGISTER_BEGIN_URL = "/api/v1/auth/me/passkeys/register/begin/"
REGISTER_COMPLETE_URL = "/api/v1/auth/me/passkeys/register/complete/"
PASSKEYS_URL = "/api/v1/auth/me/passkeys/"
AUTH_BEGIN_URL = "/api/v1/auth/passkeys/authenticate/begin/"
AUTH_COMPLETE_URL = "/api/v1/auth/passkeys/authenticate/complete/"
RP_ID = "localhost"
ORIGIN = "http://localhost:5173"
FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_AT = 0x40


class SoftAuthenticator:
    """A minimal ES256 platform authenticator.

    ``user_verified`` and ``sign_count`` are attributes so a test can make it
    misbehave in exactly the ways real hardware can.
    """

    def __init__(self, *, user_verified=True):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.user_verified = user_verified
        self.sign_count = 0

    def _cose_public_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({
            1: 2, 3: -7, -1: 1,
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        })

    def _flags(self, *, attested=False) -> int:
        return FLAG_UP | (FLAG_UV if self.user_verified else 0) | (FLAG_AT if attested else 0)

    def _client_data(self, kind, challenge_b64, origin=ORIGIN) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge_b64, "origin": origin, "crossOrigin": False}).encode()

    def register(self, options) -> dict:
        client_data = self._client_data("webauthn.create", options["challenge"])
        auth_data = (
            hashlib.sha256(RP_ID.encode()).digest()
            + bytes([self._flags(attested=True)])
            + struct.pack(">I", self.sign_count)
            + bytes(16)  # AAGUID: all zeros, "unknown authenticator"
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_public_key()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def assert_(self, options, *, origin=ORIGIN) -> dict:
        self.sign_count += 1
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        auth_data = (
            hashlib.sha256(RP_ID.encode()).digest()
            + bytes([self._flags()])
            + struct.pack(">I", self.sign_count)
        )
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
            },
            "clientExtensionResults": {},
        }


def register_passkey(client, authenticator, name="Test key"):
    options = client.post(REGISTER_BEGIN_URL).data
    return client.post(
        REGISTER_COMPLETE_URL,
        {"credential": authenticator.register(options), "name": name},
        format="json",
    )


def sign_in_with(client, authenticator, **kwargs):
    options = client.post(AUTH_BEGIN_URL, {}, format="json").data
    return client.post(
        AUTH_COMPLETE_URL,
        {"credential": authenticator.assert_(options, **kwargs)},
        format="json",
    )
