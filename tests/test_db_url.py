"""PostgreSQL URLs from hosts such as Neon are switched to the psycopg 3 driver."""

import pytest

from app.db import make_engine, normalise_database_url


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            "postgresql://u:p@ep-x.us-east-1.aws.neon.tech/neondb?sslmode=require",
            "postgresql+psycopg://u:p@ep-x.us-east-1.aws.neon.tech/neondb?sslmode=require",
        ),
        ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("sqlite:///./resumefit.db", "sqlite:///./resumefit.db"),
    ],
)
def test_normalise_database_url(given, expected):
    assert normalise_database_url(given) == expected


def test_postgres_engine_uses_psycopg_and_checks_connections():
    # create_engine does not connect, so no server is needed
    engine = make_engine("postgresql://u:p@localhost:1/db")
    assert engine.dialect.driver == "psycopg"
    assert engine.pool._pre_ping is True
