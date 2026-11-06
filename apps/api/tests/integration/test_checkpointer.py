"""LangGraph PostgresSaver: the checkpointer docker compose uses (AGENT_CHECKPOINTER=postgres).

Regression: the saver held a single long-lived connection, so after a database restart every
later agent run failed with "the connection is closed" until the worker was restarted.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from sqlalchemy import text

from nexus.application import agent_runs
from nexus.application.agent_runs import CHECKPOINTER_APP_NAME, execute_agent_run, get_checkpointer
from nexus.config import Settings
from nexus.infra.db import session_scope
from tests.integration.test_main_flow import _run_until_agents, _start

pytestmark = pytest.mark.integration


@pytest.fixture
def postgres_settings(settings: Settings) -> Iterator[Settings]:
    previous = agent_runs._checkpointer_holder.pop("saver", None)
    yield settings.model_copy(update={"agent_checkpointer": "postgres"})
    saver = agent_runs._checkpointer_holder.pop("saver", None)
    if saver is not None:
        saver.conn.close()  # the ConnectionPool
    if previous is not None:
        agent_runs._checkpointer_holder["saver"] = previous


def _checkpoint_count(factory, thread_id: str) -> int:
    with session_scope(factory) as s:
        return int(s.scalar(text("SELECT count(*) FROM checkpoints WHERE thread_id = :t"), {"t": thread_id}))


def _kill_checkpointer_connections(factory) -> int:
    """Simulate a database restart for the checkpointer: terminate its backends and wait until they are gone."""
    query = "SELECT pid FROM pg_stat_activity WHERE application_name = :n"
    with session_scope(factory) as s:
        pids = list(s.scalars(text(query), {"n": CHECKPOINTER_APP_NAME}))
        for pid in pids:
            s.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with session_scope(factory) as s:
            if not set(s.scalars(text(query), {"n": CHECKPOINTER_APP_NAME})) & set(pids):
                return len(pids)
        time.sleep(0.05)
    raise AssertionError("checkpointer backends were not terminated")


def _agent_run(factory, catalog, settings, make_tenant):
    run_id = _start(factory, catalog, settings, make_tenant())
    return _run_until_agents(factory, catalog, settings, run_id).agent_run_id


def test_postgres_checkpointer_persists_and_survives_lost_connections(
    factory, catalog, postgres_settings, make_tenant
) -> None:
    first = _agent_run(factory, catalog, postgres_settings, make_tenant)
    assert execute_agent_run(factory, postgres_settings, catalog, first) == "awaiting_approval"
    assert _checkpoint_count(factory, str(first)) > 0
    saver = get_checkpointer(postgres_settings)

    assert _kill_checkpointer_connections(factory) >= 1

    second = _agent_run(factory, catalog, postgres_settings, make_tenant)
    assert execute_agent_run(factory, postgres_settings, catalog, second) == "awaiting_approval"
    assert _checkpoint_count(factory, str(second)) > 0
    assert get_checkpointer(postgres_settings) is saver  # same process-wide saver, healed pool
