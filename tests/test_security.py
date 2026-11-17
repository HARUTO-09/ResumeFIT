"""Firebase ID token verification (app/core/security.py), against a local test key."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from firebase_fake import JWKS_URL, OTHER_PRIVATE_KEY, PROJECT_ID, firebase_token

from app.core.security import FirebaseVerifier, KeysUnavailable, TokenError


@pytest.fixture(scope="module")
def verifier():
    return FirebaseVerifier(PROJECT_ID, jwks_url=JWKS_URL)


def test_valid_token(verifier):
    claims = verifier.verify(firebase_token("Student@Example.com", provider="google.com"))
    assert claims.uid == "uid-student-at-example-com"
    assert claims.email == "student@example.com"
    assert claims.email_verified is True
    assert claims.sign_in_provider == "google.com"
    assert claims.auth_time < datetime.now(timezone.utc) < claims.expires_at


def test_unverified_email_is_reported(verifier):
    assert verifier.verify(firebase_token(email_verified=False)).email_verified is False


@pytest.mark.parametrize(
    "token_kwargs",
    [
        {"project_id": "someone-elses-project"},  # wrong audience
        {"issuer": "https://securetoken.google.com/someone-elses-project"},
        {"issuer": "https://accounts.google.com"},
        {"now": datetime.now(timezone.utc) - timedelta(hours=3)},  # expired
        {"key": OTHER_PRIVATE_KEY},  # forged signature
        {"kid": "unknown-key"},
        {"drop": ("auth_time",)},
        {"drop": ("email",)},
        {"uid": ""},
        {"auth_age": timedelta(minutes=-10)},  # signed in "in the future"
    ],
)
def test_rejected_tokens(verifier, token_kwargs):
    with pytest.raises(TokenError):
        verifier.verify(firebase_token(**token_kwargs))


def test_issued_in_the_future_is_rejected(verifier):
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    with pytest.raises(TokenError):
        verifier.verify(firebase_token(now=later))


@pytest.mark.parametrize("token", ["", "garbage", "a.b.c"])
def test_garbage_is_rejected(verifier, token):
    with pytest.raises(TokenError):
        verifier.verify(token)


def test_symmetric_or_unsigned_tokens_are_rejected(verifier):
    payload = jwt.decode(firebase_token(), options={"verify_signature": False})
    hs256 = jwt.encode(payload, "a" * 40, algorithm="HS256", headers={"kid": "test-key-1"})
    unsigned = jwt.encode(payload, None, algorithm="none", headers={"kid": "test-key-1"})
    for token in (hs256, unsigned):
        with pytest.raises(TokenError):
            verifier.verify(token)


def test_unreachable_key_server_is_not_a_token_error():
    offline = FirebaseVerifier(PROJECT_ID, jwks_url="http://127.0.0.1:9/keys.json")
    with pytest.raises(KeysUnavailable):
        offline.verify(firebase_token())


def test_project_id_is_required():
    with pytest.raises(ValueError, match="FIREBASE_PROJECT_ID"):
        FirebaseVerifier("")
