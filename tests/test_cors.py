"""CORS for the static web front end: only listed origins may call the API from a browser."""

WEB = "http://localhost:5500"


def test_preflight_from_listed_origin_is_allowed(make_api):
    client = make_api(cors_origins=f"{WEB}/, https://resumefit.example")
    response = client.options(
        "/analyze",
        headers={
            "Origin": WEB,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == WEB


def test_error_responses_carry_cors_headers(make_api):
    client = make_api(cors_origins=WEB)
    response = client.get("/auth/me", headers={"Origin": WEB})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == WEB
    assert response.json()["error"]["code"] == "not_authenticated"


def test_unlisted_origin_gets_no_cors_headers(make_api):
    client = make_api(cors_origins=WEB)
    response = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_is_off_when_no_origins_are_set(make_api):
    client = make_api(cors_origins="")  # explicit: a local .env may set origins
    response = client.get("/health", headers={"Origin": WEB})
    assert "access-control-allow-origin" not in response.headers
