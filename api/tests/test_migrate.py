from __future__ import annotations

from pathlib import Path

import pytest

from riffle.migrate import MigrationError, discover, split_statements


def test_split_drops_leading_comments_and_keeps_statements() -> None:
    sql = """
    -- a comment
    CREATE TABLE a (x String) ENGINE = Memory;

    -- another
    CREATE TABLE b (y String) ENGINE = Memory;
    """
    statements = split_statements(sql)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE a")
    assert not statements[1].endswith(";")


def test_split_keeps_multi_line_statements_whole() -> None:
    sql = "CREATE TABLE a\n(\n  x String\n)\nENGINE = Memory;"
    assert len(split_statements(sql)) == 1


def test_split_accepts_a_trailing_statement_without_a_semicolon() -> None:
    assert len(split_statements("SELECT 1;\nSELECT 2")) == 2


def test_discover_orders_by_version(tmp_path: Path) -> None:
    for name in ("002_second.sql", "001_first.sql", "010_tenth.sql"):
        (tmp_path / name).write_text("SELECT 1;")
    assert [m.version for m in discover(tmp_path)] == ["001", "002", "010"]


def test_discover_rejects_an_unnumbered_file(tmp_path: Path) -> None:
    (tmp_path / "raw_ingest.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="does not match"):
        discover(tmp_path)


def test_discover_rejects_duplicate_versions(tmp_path: Path) -> None:
    (tmp_path / "001_a.sql").write_text("SELECT 1;")
    (tmp_path / "001_b.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="duplicate"):
        discover(tmp_path)


def test_discover_rejects_a_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="not found"):
        discover(tmp_path / "nope")


def test_shipped_migrations_are_discoverable() -> None:
    directory = Path(__file__).resolve().parents[2] / "clickhouse" / "migrations"
    migrations = discover(directory)
    assert [m.name for m in migrations] == ["raw_ingest"]
    assert len(split_statements(migrations[0].path.read_text())) == 5
