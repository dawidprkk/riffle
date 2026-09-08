"""Apply numbered ClickHouse migrations, once each, in order.

Migrations are plain SQL. Statements are separated by a semicolon at end of line;
the runner does not parse SQL, so a semicolon inside a string literal would split
a statement in two. Keep migrations to DDL and that never comes up.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from clickhouse_connect.driver.client import Client

from riffle.config import Settings, get_settings
from riffle.db import new_client

MIGRATIONS_TABLE = "schema_migrations"
FILENAME = re.compile(r"^(?P<version>\d+)_(?P<name>[a-z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


class MigrationError(RuntimeError):
    pass


def discover(directory: Path) -> list[Migration]:
    if not directory.is_dir():
        raise MigrationError(f"migrations directory not found: {directory}")

    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = FILENAME.match(path.name)
        if match is None:
            raise MigrationError(
                f"{path.name} does not match <version>_<name>.sql, e.g. 001_raw_ingest.sql"
            )
        found.append(Migration(match["version"], match["name"], path))

    versions = [m.version for m in found]
    duplicates = {v for v in versions if versions.count(v) > 1}
    if duplicates:
        raise MigrationError(f"duplicate migration versions: {', '.join(sorted(duplicates))}")
    return found


def split_statements(sql: str) -> list[str]:
    """Split on a semicolon at end of line, dropping comment-only blocks."""
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not buffer and (not stripped or stripped.startswith("--")):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            buffer = []
    tail = "\n".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def ensure_database(settings: Settings) -> None:
    admin = new_client(settings, database="default")
    try:
        admin.command(f"CREATE DATABASE IF NOT EXISTS {settings.clickhouse_database}")
    finally:
        admin.close()


def ensure_tracking_table(client: Client) -> None:
    client.command(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE}
        (
            version    String,
            name       String,
            checksum   String,
            applied_at DateTime64(3, 'UTC') DEFAULT now64(3, 'UTC')
        )
        ENGINE = MergeTree
        ORDER BY version
        """
    )


def applied_checksums(client: Client) -> dict[str, str]:
    rows = client.query(
        f"SELECT version, argMax(checksum, applied_at) FROM {MIGRATIONS_TABLE} GROUP BY version"
    ).result_rows
    return {str(version): str(checksum) for version, checksum in rows}


def apply(client: Client, migration: Migration) -> int:
    statements = split_statements(migration.path.read_text(encoding="utf-8"))
    for statement in statements:
        client.command(statement)
    client.insert(
        MIGRATIONS_TABLE,
        [[migration.version, migration.name, migration.checksum]],
        column_names=["version", "name", "checksum"],
    )
    return len(statements)


def run(directory: Path, settings: Settings, *, dry_run: bool = False) -> int:
    migrations = discover(directory)
    ensure_database(settings)
    client = new_client(settings)
    try:
        ensure_tracking_table(client)
        already = applied_checksums(client)

        drifted = [
            m.version
            for m in migrations
            if m.version in already and already[m.version] != m.checksum
        ]
        if drifted:
            raise MigrationError(
                "applied migrations changed on disk: "
                + ", ".join(drifted)
                + " — write a new migration instead of editing an applied one"
            )

        pending = [m for m in migrations if m.version not in already]
        if not pending:
            print(f"up to date — {len(migrations)} migration(s) applied")
            return 0

        for migration in pending:
            if dry_run:
                count = len(split_statements(migration.path.read_text(encoding="utf-8")))
                print(f"would apply {migration.version}_{migration.name} ({count} statement(s))")
                continue
            count = apply(client, migration)
            print(f"applied {migration.version}_{migration.name} ({count} statement(s))")
        return 0
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply ClickHouse migrations for Riffle.")
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("clickhouse/migrations"),
        help="directory of <version>_<name>.sql files (default: clickhouse/migrations)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would run without applying it"
    )
    args = parser.parse_args()

    try:
        return run(args.dir, get_settings(), dry_run=args.dry_run)
    except MigrationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
