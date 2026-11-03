"""Additional public-JWKS/privacy and concurrent refresh regressions, offline."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.auth.jwt import JwtVerifier
from app.domain.learning import LearningError
from tests.auth_fixtures import AuthClock, KeysFixture, SigningFixture, auth_settings


@pytest.mark.parametrize("field", ["dp", "dq", "qi", "oth"])
def test_public_jwks_rejects_all_rsa_private_crt_fields(settings, field, capsys, caplog):
    signer = SigningFixture("RS256")
    keys = KeysFixture(signer)
    keys.data = {"keys": [dict(signer.jwk, **{field: "synthetic-private-fragment-canary"})]}
    verifier = JwtVerifier(auth_settings(settings), keys)
    with pytest.raises(LearningError) as error:
        verifier.verify(signer.token())
    assert error.value.code == "dependency_unavailable"
    assert "private-fragment-canary" not in str(error.value) + capsys.readouterr().err + caplog.text


@pytest.mark.parametrize("kind", ["rsa1024", "p384-with-es256"])
def test_unapproved_key_strength_or_curve_fails_before_signature_validation(settings, kind):
    signer = SigningFixture("RS256" if kind == "rsa1024" else "ES256")
    public = (
        rsa.generate_private_key(65537, 1024).public_key()
        if kind == "rsa1024"
        else ec.generate_private_key(ec.SECP384R1()).public_key()
    )
    algorithm = jwt.algorithms.RSAAlgorithm if kind == "rsa1024" else jwt.algorithms.ECAlgorithm
    raw = json.loads(algorithm.to_jwk(public))
    raw.update(kid=signer.kid, alg=signer.algorithm, use="sig", key_ops=["verify"])
    keys = KeysFixture()
    keys.data = {"keys": [raw]}
    with pytest.raises(LearningError) as error:
        JwtVerifier(auth_settings(settings), keys).verify(signer.token())
    assert error.value.code == "dependency_unavailable"


@pytest.mark.parametrize("header", ["jku", "x5u", "jwk"])
def test_token_headers_cannot_replace_the_configured_public_key_source(settings, header):
    signer = SigningFixture()
    keys = KeysFixture(signer)
    value = (
        {"kty": "oct", "k": "synthetic-untrusted-key"}
        if header == "jwk"
        else "https://attacker.invalid/keys"
    )
    verifier = JwtVerifier(auth_settings(settings), keys)
    assert verifier.verify(signer.token(headers={header: value})).subject == signer.subject
    assert keys.calls == 1


@pytest.mark.parametrize("expired", [False, True])
def test_simultaneous_requests_coalesce_one_jwks_refresh(settings, expired):
    clock = AuthClock()
    signer = SigningFixture(clock=clock)
    entered, release, duplicate = Event(), Event(), Event()
    barrier = Barrier(8)

    class ControlledSource:
        def __init__(self):
            self.calls = 0
            self.phase_calls = 0
            self.block = False
            self.lock = Lock()

        def fetch(self):
            with self.lock:
                self.calls += 1
                if self.block:
                    self.phase_calls += 1
                    if self.phase_calls > 1:
                        duplicate.set()
            if self.block:
                entered.set()
                assert release.wait(5)
            return {"keys": [signer.jwk]}

    source = ControlledSource()
    verifier = JwtVerifier(auth_settings(settings), source, clock)
    if expired:
        verifier.verify(signer.token())
        clock.advance(301)
    source.block = True
    token = signer.token()

    def verify():
        barrier.wait(timeout=5)
        return verifier.verify(token)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(verify) for _ in range(8)]
        try:
            assert entered.wait(5)
            assert not duplicate.wait(0.1)
        finally:
            release.set()
        assert all(future.result(timeout=5).subject == signer.subject for future in futures)
    assert source.phase_calls == 1


def test_unexpired_cached_key_remains_usable_without_an_outage_fetch(settings):
    clock = AuthClock()
    signer = SigningFixture(clock=clock)
    keys = KeysFixture(signer)
    verifier = JwtVerifier(auth_settings(settings), keys, clock)
    verifier.verify(signer.token())
    keys.outage = True
    clock.advance(10)
    assert verifier.verify(signer.token()).subject == signer.subject and keys.calls == 1


def test_closed_verifier_cannot_release_cached_identity(settings):
    signer = SigningFixture()
    keys = KeysFixture(signer)
    verifier = JwtVerifier(auth_settings(settings), keys)
    verifier.verify(signer.token())
    verifier.close()
    with pytest.raises(LearningError) as error:
        verifier.verify(signer.token())
    assert error.value.code == "dependency_unavailable"
    assert verifier.closed and not verifier._keys and keys.calls == 1


def test_cleanup_failure_cannot_reveal_provider_diagnostics_or_leave_cached_keys(settings):
    signer = SigningFixture()

    class BrokenClose(KeysFixture):
        def close(self):
            raise RuntimeError("private-source-credential-canary")

    source = BrokenClose(signer)
    verifier = JwtVerifier(auth_settings(settings), source)
    verifier.verify(signer.token())
    with pytest.raises(RuntimeError, match="Authentication cleanup failed") as error:
        verifier.close()
    assert "private-source" not in str(error.value)
    assert verifier.closed and not verifier._keys
