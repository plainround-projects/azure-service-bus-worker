"""Shared fixtures."""

from pathlib import Path

import pytest

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


@pytest.fixture
def sql_dir() -> Path:
    return SQL_DIR


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "orders.db"
