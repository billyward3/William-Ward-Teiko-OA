"""Shared pytest fixtures.

Repository layout is encoded here and nowhere else in the test suite, so a
change to the directory structure is a one-line edit rather than a search.

Library code deliberately does not derive paths this way. Functions take paths
as arguments so tests can supply synthetic fixtures, and `load_data.py` at the
repository root resolves the real locations from its own position.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from cellcount.db import connect

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """An empty in-memory database, opened the same way the app opens one."""
    connection = connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def cell_count_csv() -> Path:
    """The real input dataset.

    For characterization tests only. Behavioural tests should build small
    synthetic inputs instead, so they stay fast and their failures point at a
    bug rather than at the data.
    """
    return REPO_ROOT / "cell-count.csv"
