import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.core.settings import Settings

ISSUER = "https://auth.example.test/auth/v1"


def auth_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "supabase_url": "https://auth.example.test",
            "supabase_issuer": ISSUER,
            "supabase_jwks_url": ISSUER + "/.well-known/jwks.json",
        }
    )


class SigningFixture:
    def __init__(self, algorithm="ES256", kid="first"):
        self.algorithm, self.kid = algorithm, kid
        self.key = (
            ec.generate_private_key(ec.SECP256R1())
            if algorithm == "ES256"
            else rsa.generate_private_key(65537, 2048)
        )
        kind = jwt.algorithms.ECAlgorithm if algorithm == "ES256" else jwt.algorithms.RSAAlgorithm
        self.jwk = json.loads(kind.to_jwk(self.key.public_key()))
        self.jwk.update(kid=kid, alg=algorithm, use="sig", key_ops=["verify"])
        self.subject = str(uuid4())

    def token(self, claims=None, headers=None):
        now = int(datetime.now(UTC).timestamp())
        payload = {
            "iss": ISSUER,
            "aud": "authenticated",
            "sub": self.subject,
            "iat": now,
            "exp": now + 1800,
            "role": "authenticated",
            "is_anonymous": False,
        }
        payload.update(claims or {})
        return jwt.encode(
            payload,
            self.key,
            algorithm=self.algorithm,
            headers={"kid": self.kid, **(headers or {})},
        )


class KeysFixture:
    def __init__(self, *signers):
        self.data = {"keys": [signer.jwk for signer in signers]}
        self.calls = 0
        self.outage = False

    def fetch(self):
        self.calls += 1
        if self.outage:
            raise ValueError("private provider error")
        return self.data


class AuthClock:
    def __init__(self):
        self.now = datetime.now(UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)
