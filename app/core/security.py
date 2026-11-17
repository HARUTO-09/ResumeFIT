"""Verify Firebase Authentication ID tokens (framework-free).

Sign-in itself (email and password, or Google) happens in Firebase; the UI sends
the resulting ID token with every request. This module checks that token the way
Firebase documents it, using only PyJWT:

- signed with RS256 by one of Google's current Firebase keys (fetched from Google
  and cached; the key id in the token header picks the key);
- audience is this Firebase project and issuer is
  https://securetoken.google.com/<project id>;
- not expired, not issued in the future, and `sub` (the Firebase uid) is non-empty;
- `auth_time` (when the user last actually signed in) is in the past.

No service account or Google SDK is needed to verify tokens.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import jwt

FIREBASE_JWKS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
)
ALGORITHM = "RS256"


class TokenError(Exception):
    """The token is missing, malformed, expired, for another project or badly signed."""


class KeysUnavailable(Exception):
    """Google's signing keys could not be fetched, so no token can be checked right now."""


@dataclass(frozen=True)
class FirebaseClaims:
    uid: str
    email: str
    email_verified: bool
    sign_in_provider: str
    auth_time: datetime
    expires_at: datetime


class FirebaseVerifier:
    def __init__(self, project_id: str, jwks_url: str = FIREBASE_JWKS_URL, leeway_s: int = 10):
        if not project_id:
            raise ValueError("Set RESUMEFIT_FIREBASE_PROJECT_ID to your Firebase project id.")
        self.project_id = project_id
        self._issuer = f"https://securetoken.google.com/{project_id}"
        self._leeway = leeway_s
        # Keys are cached for an hour and refetched when an unknown key id appears.
        self._keys = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)

    def verify(self, token: str, now: datetime | None = None) -> FirebaseClaims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise TokenError("malformed token") from None
        if header.get("alg") != ALGORITHM or not header.get("kid"):
            raise TokenError("unexpected token header")

        try:
            key = self._keys.get_signing_key(header["kid"]).key
        except jwt.PyJWKClientConnectionError:
            raise KeysUnavailable("could not fetch Firebase signing keys") from None
        except jwt.PyJWKClientError:
            raise TokenError("token signed with an unknown key") from None

        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                audience=self.project_id,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "aud", "iss", "sub", "auth_time"]},
            )
        except jwt.PyJWTError:
            raise TokenError("invalid or expired token") from None

        uid = payload.get("sub")
        if not isinstance(uid, str) or not uid or len(uid) > 128:
            raise TokenError("token has no valid user id")
        email = payload.get("email")
        if not isinstance(email, str) or "@" not in email:
            raise TokenError("token has no email address")

        now_ts = (now or datetime.now(timezone.utc)).timestamp()
        auth_time = payload["auth_time"]
        if not isinstance(auth_time, int | float) or auth_time > now_ts + self._leeway:
            raise TokenError("sign-in time is in the future")

        firebase = payload.get("firebase") or {}
        return FirebaseClaims(
            uid=uid,
            email=email.strip().lower(),
            email_verified=payload.get("email_verified") is True,
            sign_in_provider=str(firebase.get("sign_in_provider", "unknown")),
            auth_time=datetime.fromtimestamp(auth_time, timezone.utc),
            expires_at=datetime.fromtimestamp(payload["exp"], timezone.utc),
        )
