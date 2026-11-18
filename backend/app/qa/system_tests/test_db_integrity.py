from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection

from app.core.config import settings

REQUIRED_TABLES = {"users", "services", "checks", "incidents", "actions", "ai_conversations",
                   "app_settings", "test_runs"}
REQUIRED_INDEXES = {
    "checks": {"ix_checks_service_checked"},
    "incidents": {"ix_incidents_service_status"},
    "users": {"ix_users_username"},
}


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection]:
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        yield connection
    engine.dispose()


def scalar(conn: Connection, sql: str) -> int:
    return int(conn.execute(text(sql)).scalar() or 0)


def test_tables_exist(conn: Connection) -> None:
    assert REQUIRED_TABLES <= set(inspect(conn).get_table_names())


@pytest.mark.parametrize("table", sorted(REQUIRED_INDEXES))
def test_indexes_exist(conn: Connection, table: str) -> None:
    names = {ix["name"] for ix in inspect(conn).get_indexes(table)}
    assert REQUIRED_INDEXES[table] <= names, f"missing indexes on {table}: {REQUIRED_INDEXES[table] - names}"


def test_foreign_keys(conn: Connection) -> None:
    fks = {fk["referred_table"] for fk in inspect(conn).get_foreign_keys("checks")}
    assert "services" in fks


def test_no_orphan_checks(conn: Connection) -> None:
    assert scalar(conn, "SELECT count(*) FROM checks c LEFT JOIN services s ON s.id = c.service_id "
                        "WHERE s.id IS NULL") == 0


def test_single_open_incident_per_service(conn: Connection) -> None:
    assert scalar(conn, "SELECT count(*) FROM (SELECT service_id FROM incidents WHERE status = 'open' "
                        "GROUP BY service_id HAVING count(*) > 1) t") == 0


def test_incident_timestamps_consistent(conn: Connection) -> None:
    assert scalar(conn, "SELECT count(*) FROM incidents WHERE status = 'resolved' AND "
                        "(resolved_at IS NULL OR resolved_at < started_at)") == 0
    assert scalar(conn, "SELECT count(*) FROM incidents WHERE status = 'open' AND resolved_at IS NOT NULL") == 0


def test_executed_actions_have_timestamp(conn: Connection) -> None:
    assert scalar(conn, "SELECT count(*) FROM actions WHERE status = 'executed' AND executed_at IS NULL") == 0


def test_admin_exists(conn: Connection) -> None:
    assert scalar(conn, "SELECT count(*) FROM users WHERE role = 'admin'") >= 1


def test_check_statuses_valid(conn: Connection) -> None:
    assert scalar(conn, "SELECT count(*) FROM checks WHERE status NOT IN ('up', 'degraded', 'down')") == 0
