import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.embeddings import HashingEmbedder  # noqa: E402
from app.core.params import DocumentLimits  # noqa: E402
from app.core.skills import load_skills  # noqa: E402


@pytest.fixture(scope="session")
def embedder():
    # Deterministic and needs no model download, so the suite runs anywhere.
    return HashingEmbedder()


@pytest.fixture(scope="session")
def skills_db():
    return load_skills()


@pytest.fixture()
def limits():
    return DocumentLimits()


@pytest.fixture()
def make_api(tmp_path, embedder):
    """Build API test clients on one temporary database. Clients start signed out.

    make_api(llm=None, **settings_overrides) -> an entered TestClient.
    """
    from fastapi.testclient import TestClient
    from helpers import AUTH_SETTINGS

    from app.config import Settings
    from app.main import create_app

    opened = []

    def build(llm=None, **overrides):
        settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'api.db'}",
            embedding_backend="hashing",
            coach_min_similarity=0.05,  # the hashing embedder scores lower than a real model
            **{**AUTH_SETTINGS, **overrides},
        )
        client = TestClient(create_app(settings, embedder=embedder, llm=llm))
        client.__enter__()
        opened.append(client)
        return client

    yield build
    for client in opened:
        client.__exit__(None, None, None)
