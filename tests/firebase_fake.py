"""A stand-in for Firebase in tests: a local RSA key whose public half is published
as a JWKS file, and a function that signs Firebase-shaped ID tokens with it.

The API verifies these exactly as it verifies real Firebase tokens; only the key
URL differs (a local HTTP server instead of Google's), so no internet is needed.
"""

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

PROJECT_ID = "resumefit-test"
KEY_ID = "test-key-1"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _serve_jwks() -> str:
    """Serve the public key set on 127.0.0.1 for the whole test session."""
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_PRIVATE_KEY.public_key()))
    jwk.update(kid=KEY_ID, alg="RS256", use="sig")
    body = json.dumps({"keys": [jwk]}).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}/jwks.json"


JWKS_URL = _serve_jwks()


def uid_for(email: str) -> str:
    """A stable fake Firebase uid for an email, so the same person gets the same uid."""
    return "uid-" + email.strip().lower().replace("@", "-at-").replace(".", "-")[:100]


def firebase_token(
    email: str = "student@example.com",
    uid: str | None = None,
    *,
    email_verified: bool = True,
    provider: str = "password",
    project_id: str = PROJECT_ID,
    issuer: str | None = None,
    now: datetime | None = None,
    auth_age: timedelta = timedelta(seconds=30),
    lifetime: timedelta = timedelta(hours=1),
    key=None,
    kid: str = KEY_ID,
    drop: tuple[str, ...] = (),
) -> str:
    now = now or datetime.now(timezone.utc)
    payload = {
        "iss": issuer or f"https://securetoken.google.com/{project_id}",
        "aud": project_id,
        "auth_time": int((now - auth_age).timestamp()),
        "user_id": uid if uid is not None else uid_for(email),
        "sub": uid if uid is not None else uid_for(email),
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "email": email,
        "email_verified": email_verified,
        "firebase": {"identities": {"email": [email]}, "sign_in_provider": provider},
    }
    for claim in drop:
        payload.pop(claim, None)
    return jwt.encode(payload, key or _PRIVATE_KEY, algorithm="RS256", headers={"kid": kid})
