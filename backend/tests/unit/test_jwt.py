from datetime import timedelta
from unittest.mock import MagicMock, patch

import httpx2
import jwt
import pytest

from app.auth.jwt import HttpJwksSource, JwtVerifier
from app.core.settings import Settings
from app.domain.learning import LearningError
from tests.auth_fixtures import AuthClock, KeysFixture, SigningFixture, auth_settings


@pytest.fixture
def fixture(settings):
    clock = AuthClock()
    signer = SigningFixture(clock=clock)
    keys = KeysFixture(signer)
    return signer, keys, clock, JwtVerifier(auth_settings(settings), keys, clock)


@pytest.mark.parametrize("algorithm", ["ES256", "RS256"])
def test_asymmetric_valid_signature_and_required_claims(settings, algorithm):
    signer = SigningFixture(algorithm)
    verifier = JwtVerifier(auth_settings(settings), KeysFixture(signer))
    identity = verifier.authorization("Bearer " + signer.token())
    assert identity.subject == signer.subject
    assert identity.issuer == auth_settings(settings).supabase_issuer


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://other.example/auth/v1"},
        {"aud": "other"},
        {"aud": 23},
        {"exp": 1},
        {"exp": "2000000000"},
        {"exp": True},
        {"exp": 9e99},
        {"iat": "invalid"},
        {"iat": 9999999999},
        {"nbf": 9999999999},
        {"nbf": "tomorrow"},
        {"sub": None},
        {"sub": 42},
        {"sub": "not-a-uuid"},
        {"role": "service_role"},
        {"is_anonymous": True},
        {"is_anonymous": "false"},
    ],
)
def test_invalid_claims_rejected(fixture, claims):
    signer, _, _, verifier = fixture
    with pytest.raises(LearningError, match="invalid or expired") as error:
        verifier.verify(signer.token(claims))
    assert error.value.code == "unauthenticated"


@pytest.mark.parametrize("claim", ["iss", "aud", "exp", "iat", "sub", "role"])
def test_missing_claim_rejected(fixture, claim):
    signer, _, _, verifier = fixture
    payload = jwt.decode(signer.token(), options={"verify_signature": False})
    del payload[claim]
    with pytest.raises(LearningError):
        verifier.verify(
            jwt.encode(payload, signer.key, algorithm="ES256", headers={"kid": signer.kid})
        )


@pytest.mark.parametrize(
    "token",
    [
        "",
        "nonsense",
        "a.b.c",
        "x" * 16385,
        jwt.encode(
            {"sub": "forged"}, key="fixture-key-for-unsupported-algorithm", algorithm="HS256"
        ),
        jwt.encode({"sub": "forged"}, key="", algorithm="none"),
    ],
)
def test_malformed_or_unsupported_never_fetches_keys(fixture, token):
    _, keys, _, verifier = fixture
    with pytest.raises(LearningError):
        verifier.verify(token)
    assert keys.calls == 0


@pytest.mark.parametrize("header", ["", "Basic abc", "Bearer", "Bearer  abc", "Bearer abc extra"])
def test_bad_authorization(fixture, header):
    with pytest.raises(LearningError):
        fixture[3].authorization(header)


def test_signature_and_header_constraints(fixture):
    signer, keys, _, verifier = fixture
    other = SigningFixture(kid=signer.kid)
    for token in [
        other.token(),
        signer.token(headers={"kid": ""}),
        signer.token(headers={"typ": "other"}),
        signer.token(headers={"crit": ["x"]}),
    ]:
        with pytest.raises(LearningError):
            verifier.verify(token)
    assert keys.calls == 1


def test_cache_rotation_unknown_kid_outage_and_refresh_cooldown(fixture):
    signer, keys, clock, verifier = fixture
    verifier.verify(signer.token())
    for _ in range(10):
        verifier.verify(signer.token())
    assert keys.calls == 1
    rotated = SigningFixture(kid="rotated", clock=clock)
    with pytest.raises(LearningError):
        verifier.verify(rotated.token())
    assert keys.calls == 1  # random kid storms cannot cause unbounded fetches
    clock.advance(5)
    keys.data = {"keys": [signer.jwk, rotated.jwk]}
    assert verifier.verify(rotated.token()).subject == rotated.subject
    assert keys.calls == 2
    clock.advance(301)
    keys.outage = True
    for _ in range(5):
        with pytest.raises(LearningError) as error:
            verifier.verify(signer.token())
        assert error.value.code == "dependency_unavailable"
    assert keys.calls == 3
    keys.outage = False
    clock.advance(5)
    verifier.verify(rotated.token())
    assert keys.calls == 4


def test_fixture_tokens_follow_shared_clock_across_wall_clock_boundaries(fixture):
    signer, keys, clock, verifier = fixture
    with patch("tests.auth_fixtures.datetime") as wall_clock:
        for seconds in (1, 2, 3601):
            wall_clock.now.return_value = clock() + timedelta(seconds=seconds)
            assert verifier.verify(signer.token()).subject == signer.subject
        clock.advance(5)
        claims = jwt.decode(signer.token(), options={"verify_signature": False})
        assert claims["iat"] == int(clock().timestamp())
        assert claims["exp"] == claims["iat"] + 1800
        assert verifier.verify(signer.token()).subject == signer.subject
    assert keys.calls == 1


def test_shared_fixture_clock_does_not_allow_future_issued_at(fixture):
    signer, _, clock, verifier = fixture
    with pytest.raises(LearningError) as error:
        verifier.verify(signer.token({"iat": int(clock().timestamp()) + 1}))
    assert error.value.code == "unauthenticated"


@pytest.mark.parametrize(
    "keys",
    [
        None,
        [],
        [{}],
        [1],
        [{"alg": "HS256"}],
        [{"alg": "ES256", "kid": "a", "d": "private"}],
        [{"alg": "ES256", "kid": "a", "use": "enc"}],
        [{"alg": "ES256", "kid": "a", "key_ops": ["sign"]}],
        [{"alg": "ES256", "kid": "a", "kty": "RSA"}],
        [{}] * 17,
    ],
)
def test_bad_jwks_fails_closed(fixture, keys):
    signer, source, _, verifier = fixture
    source.data = {"keys": keys}
    with pytest.raises(LearningError) as error:
        verifier.verify(signer.token())
    assert error.value.code == "dependency_unavailable"


def test_duplicate_or_algorithm_mismatched_key(fixture):
    signer, source, clock, verifier = fixture
    source.data = {"keys": [signer.jwk, signer.jwk]}
    with pytest.raises(LearningError):
        verifier.verify(signer.token())
    clock.advance(5)
    rsa_signer = SigningFixture("RS256", kid=signer.kid)
    source.data = {"keys": [rsa_signer.jwk]}
    with pytest.raises(LearningError):
        verifier.verify(signer.token())


def test_unconfigured_fails_closed(settings):
    with pytest.raises(LearningError, match="not configured"):
        JwtVerifier(settings).verify("any")


@pytest.mark.parametrize("body", [b'{"keys": []}', b"[]", b"invalid", b"x" * 65537])
def test_http_source_bounds_response_and_checks_structure(body):
    response = MagicMock()
    response.iter_bytes.return_value = [body]
    client = MagicMock()
    client.__enter__.return_value.stream.return_value.__enter__.return_value = response
    with patch("app.auth.jwt.httpx2.Client", return_value=client) as factory:
        if body == b'{"keys": []}':
            assert HttpJwksSource("https://auth.example.test/keys").fetch() == {"keys": []}
        else:
            with pytest.raises(ValueError):
                HttpJwksSource("https://auth.example.test/keys").fetch()
        factory.assert_called_once_with(timeout=3, follow_redirects=False, trust_env=False)


def test_transport_outage_is_safe(fixture):
    signer, keys, _, verifier = fixture
    keys.fetch = MagicMock(side_effect=httpx2.ConnectError("private endpoint detail"))
    with pytest.raises(LearningError) as error:
        verifier.verify(signer.token())
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "updates",
    [
        {"supabase_url": "https://auth.example.test"},
        {"supabase_issuer": "https://evil.example/auth/v1"},
        {"supabase_jwks_url": "https://evil.example/jwks"},
        {"supabase_url": "https://user:password@auth.example.test"},
        {"supabase_url": "http://auth.example.test"},
        {"supabase_audience": ""},
    ],
)
def test_inconsistent_provider_settings_rejected(settings, updates):
    from pydantic import ValidationError

    values = auth_settings(settings).model_dump()
    if updates == {"supabase_url": "https://auth.example.test"}:
        values = settings.model_dump()
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(values | updates))
