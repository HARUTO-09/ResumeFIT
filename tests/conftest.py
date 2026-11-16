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
