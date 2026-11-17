import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.core import llm as llm_module
from app.core.llm import LLMUnavailable, OpenAICompatibleLLM, build_llm


class StubServer:
    """A local stand-in for a chat-completions server. `script` lists the replies in order."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append(
                    {"path": self.path, "auth": self.headers.get("Authorization"), "body": body}
                )
                status, payload = stub.script.pop(0) if stub.script else (500, "{}")
                data = (
                    payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
                )
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def ok(text):
    return 200, {"choices": [{"message": {"role": "assistant", "content": text}}]}


@pytest.fixture()
def stub(monkeypatch):
    monkeypatch.setattr(llm_module.time, "sleep", lambda seconds: None)
    servers = []

    def start(script):
        servers.append(StubServer(script))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


def test_successful_call_sends_messages_and_key(stub):
    server = stub([ok(" Add a Docker line [G3]. ")])
    client = OpenAICompatibleLLM(server.url, "test-model", api_key="secret-key")
    assert client.complete("system text", "user text") == "Add a Docker line [G3]."
    request = server.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["auth"] == "Bearer secret-key"
    assert request["body"]["model"] == "test-model"
    assert [m["role"] for m in request["body"]["messages"]] == ["system", "user"]
    assert client.name == "test-model"


def test_no_key_means_no_auth_header(stub):
    server = stub([ok("fine [G1]")])
    OpenAICompatibleLLM(server.url, "local-model").complete("s", "u")
    assert server.requests[0]["auth"] is None


def test_server_errors_are_retried_at_most_twice(stub):
    server = stub([(500, "{}"), (503, "{}"), ok("third time [G1]")])
    assert OpenAICompatibleLLM(server.url, "m").complete("s", "u") == "third time [G1]"
    assert len(server.requests) == 3

    server = stub([(500, "{}")] * 5)
    with pytest.raises(LLMUnavailable, match="HTTP 500"):
        OpenAICompatibleLLM(server.url, "m").complete("s", "u")
    assert len(server.requests) == 3  # first try + 2 retries


def test_client_errors_are_not_retried_and_do_not_leak_the_key(stub):
    server = stub([(401, '{"error": "bad key secret-key"}'), ok("never reached")])
    with pytest.raises(LLMUnavailable) as info:
        OpenAICompatibleLLM(server.url, "m", api_key="secret-key").complete("s", "u")
    assert len(server.requests) == 1
    assert "secret-key" not in str(info.value)


def test_malformed_or_empty_responses_fail_cleanly(stub):
    server = stub([(200, "not json")] * 3)
    with pytest.raises(LLMUnavailable, match="unexpected response"):
        OpenAICompatibleLLM(server.url, "m").complete("s", "u")
    server = stub([(200, {"choices": []})] * 3)
    with pytest.raises(LLMUnavailable):
        OpenAICompatibleLLM(server.url, "m").complete("s", "u")
    server = stub([ok("   ")] * 3)
    with pytest.raises(LLMUnavailable):
        OpenAICompatibleLLM(server.url, "m").complete("s", "u")


def test_unreachable_server(stub):
    server = stub([])
    url = server.url
    server.close()
    with pytest.raises(LLMUnavailable, match="connection failed"):
        OpenAICompatibleLLM(url, "m", timeout=1, max_retries=1).complete("s", "u")


def test_build_llm():
    assert build_llm("none", "", "") is None
    built = build_llm("openai-compatible", "http://localhost:1/v1", "some-model")
    assert isinstance(built, OpenAICompatibleLLM) and built.name == "some-model"
    with pytest.raises(ValueError):
        build_llm("openai-compatible", "", "")
    with pytest.raises(ValueError):
        build_llm("telepathy", "x", "y")
