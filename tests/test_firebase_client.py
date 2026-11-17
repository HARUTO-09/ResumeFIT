"""The UI's Firebase REST client, against a local stub of the Firebase endpoints."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from ui.firebase_client import FirebaseClient, FirebaseError, FirebaseSession


class StubFirebase:
    """Answers like Firebase. `replies` maps an endpoint name to (status, body)."""

    def __init__(self):
        self.replies: dict[str, tuple[int, dict]] = {}
        self.requests: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                url = urlparse(self.path)
                raw = self.rfile.read(int(self.headers["Content-Length"])).decode()
                if self.headers.get("Content-Type", "").startswith("application/json"):
                    body = json.loads(raw)
                else:
                    body = {k: v[0] for k, v in parse_qs(raw).items()}
                name = url.path.rsplit("/", 1)[-1]
                stub.requests.append(
                    {"name": name, "key": parse_qs(url.query).get("key", [None])[0], "body": body}
                )
                status, payload = stub.replies.get(name, (404, {"error": {"message": "NOT_FOUND"}}))
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        base = f"http://127.0.0.1:{self.server.server_port}"
        self.client = FirebaseClient(
            "web-key", identity_url=f"{base}/v1", token_url=f"{base}/v1/token"
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture()
def stub():
    s = StubFirebase()
    yield s
    s.server.shutdown()
    s.server.server_close()


TOKENS = {"idToken": "id-1", "refreshToken": "refresh-1", "expiresIn": "3600"}


def test_sign_up_and_sign_in_return_a_session(stub):
    stub.replies["accounts:signUp"] = (200, TOKENS)
    stub.replies["accounts:signInWithPassword"] = (200, TOKENS)
    for session in (
        stub.client.sign_up(" s@example.com ", "pw123456"),
        stub.client.sign_in("s@example.com", "pw123456"),
    ):
        assert session.id_token == "id-1" and session.refresh_token == "refresh-1"
        assert not session.expires_soon()
    first = stub.requests[0]
    assert first["key"] == "web-key"
    assert first["body"] == {
        "email": "s@example.com",
        "password": "pw123456",
        "returnSecureToken": True,
    }


@pytest.mark.parametrize(
    ("firebase_message", "expected"),
    [
        ("EMAIL_EXISTS", "already exists"),
        ("INVALID_LOGIN_CREDENTIALS", "incorrect"),
        ("WEAK_PASSWORD : Password should be at least 6 characters", "at least 6"),
        ("TOO_MANY_ATTEMPTS_TRY_LATER : Access disabled", "Too many attempts"),
        ("OPERATION_NOT_ALLOWED", "not enabled"),
        ("SOMETHING_NEW", "SOMETHING_NEW"),
    ],
)
def test_firebase_errors_become_readable(stub, firebase_message, expected):
    stub.replies["accounts:signInWithPassword"] = (400, {"error": {"message": firebase_message}})
    with pytest.raises(FirebaseError, match=expected):
        stub.client.sign_in("s@example.com", "wrong")


def test_refresh_keeps_the_provider(stub):
    stub.replies["token"] = (
        200,
        {"id_token": "id-2", "refresh_token": "refresh-2", "expires_in": "3600"},
    )
    old = FirebaseSession("id-1", "refresh-1", expires_at=0, provider="google.com")
    assert old.expires_soon()
    new = stub.client.refresh(old)
    assert (new.id_token, new.refresh_token, new.provider) == ("id-2", "refresh-2", "google.com")
    assert stub.requests[0]["body"] == {"grant_type": "refresh_token", "refresh_token": "refresh-1"}


def test_reset_verify_and_delete_calls(stub):
    stub.replies["accounts:sendOobCode"] = (200, {})
    stub.replies["accounts:delete"] = (200, {})
    session = FirebaseSession("id-1", "refresh-1", expires_at=9e12)
    stub.client.send_password_reset("s@example.com")
    stub.client.send_verification_email(session)
    stub.client.delete_account(session)
    assert [r["body"] for r in stub.requests] == [
        {"requestType": "PASSWORD_RESET", "email": "s@example.com"},
        {"requestType": "VERIFY_EMAIL", "idToken": "id-1"},
        {"idToken": "id-1"},
    ]


def test_network_failure_is_a_readable_error():
    client = FirebaseClient(
        "k", identity_url="http://127.0.0.1:9/v1", token_url="http://127.0.0.1:9/t"
    )
    with pytest.raises(FirebaseError, match="Cannot reach Firebase"):
        client.sign_in("s@example.com", "pw")
