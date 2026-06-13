"""Tests for ``epc/traffic.py`` (the background traffic generator).

This module was previously untested. The synchronous bookkeeping in
``TrafficGeneratorManager`` (start guards, stop/stop_all, is_running, the
singleton accessor) is covered with fast unit tests that monkeypatch the
asyncio scheduling so no real coroutine runs. A single ``@pytest.mark.slow``
integration test exercises the real background event loop end-to-end.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

import epc.traffic as traffic
from epc.db import EPCRepository
from epc.models import BearerConfig
from epc.traffic import TrafficGeneratorManager, get_traffic_manager


@pytest.fixture
def manager() -> TrafficGeneratorManager:
    return TrafficGeneratorManager(MagicMock())


@pytest.fixture
def no_real_scheduling(monkeypatch):
    """Replace ``run_coroutine_threadsafe`` so ``start`` never touches the loop.

    The created coroutine is closed immediately to avoid "coroutine was never
    awaited" warnings, and a sentinel future is returned for bookkeeping.
    """
    created: list = []

    def fake_schedule(coro, _loop):
        coro.close()
        fut = MagicMock(name="future")
        created.append(fut)
        return fut

    monkeypatch.setattr(traffic.asyncio, "run_coroutine_threadsafe", fake_schedule)
    return created


# start() guard clauses
def test_start_raises_when_traffic_already_running(manager):
    manager.tasks[(1, 1)] = MagicMock()  # pretend a task is already scheduled
    bearer = BearerConfig(bearer_id=1, protocol="tcp", target_bps=1000)

    with pytest.raises(ValueError, match="Traffic already running"):
        manager.start(1, bearer)


@pytest.mark.parametrize(
    "bearer",
    [
        BearerConfig(bearer_id=1, protocol=None, target_bps=1000),  # no protocol
        BearerConfig(bearer_id=1, protocol="tcp", target_bps=None),  # no rate
        BearerConfig(bearer_id=1, protocol="tcp", target_bps=0),     # falsy rate
    ],
)
def test_start_raises_when_bearer_not_configured(manager, bearer):
    with pytest.raises(ValueError, match="Bearer not configured for traffic"):
        manager.start(1, bearer)


def test_start_records_task_and_marks_running(manager, no_real_scheduling):
    bearer = BearerConfig(bearer_id=2, protocol="udp", target_bps=2000)

    manager.start(7, bearer)

    assert manager.is_running(7, 2) is True
    assert manager.tasks[(7, 2)] is no_real_scheduling[0]


# stop() / stop_all()
@pytest.mark.usefixtures("no_real_scheduling")
def test_stop_cancels_future_and_removes_task(manager):
    bearer = BearerConfig(bearer_id=3, protocol="tcp", target_bps=3000)
    manager.start(1, bearer)
    future = manager.tasks[(1, 3)]

    manager.stop(1, 3)

    future.cancel.assert_called_once()
    assert manager.is_running(1, 3) is False


def test_stop_unknown_task_is_a_noop(manager):
    manager.stop(99, 9)  # must not raise
    assert manager.tasks == {}


@pytest.mark.usefixtures("no_real_scheduling")
def test_stop_all_cancels_every_future(manager):
    manager.start(1, BearerConfig(bearer_id=1, protocol="tcp", target_bps=1000))
    manager.start(2, BearerConfig(bearer_id=2, protocol="udp", target_bps=2000))
    futures = list(manager.tasks.values())

    manager.stop_all()

    for fut in futures:
        fut.cancel.assert_called_once()
    assert manager.tasks == {}


def test_is_running_false_for_unknown_key(manager):
    assert manager.is_running(1, 1) is False


# get_traffic_manager() singleton
def test_get_traffic_manager_is_a_singleton(monkeypatch):
    monkeypatch.setattr(traffic, "traffic_manager", None)
    repo_a = MagicMock()
    repo_b = MagicMock()

    first = get_traffic_manager(repo_a)
    second = get_traffic_manager(repo_b)

    assert first is second
    assert first.repo is repo_a


# End-to-end: the real asyncio background loop actually moves byte counters.
@pytest.mark.slow
def test_real_loop_increments_byte_counters(tmp_path):
    repo = EPCRepository(str(tmp_path / "traffic.db"))
    repo.attach_ue(1)
    mgr = TrafficGeneratorManager(repo)
    bearer = BearerConfig(bearer_id=9, protocol="tcp", target_bps=8000)  # 1000 bytes/s

    try:
        mgr.start(1, bearer)
        deadline = time.time() + 4.0
        bytes_tx = 0
        while time.time() < deadline:
            stats = repo.get_ue(1).stats.get(9)
            if stats and stats.bytes_tx >= 1000:
                bytes_tx = stats.bytes_tx
                break
            time.sleep(0.1)
    finally:
        mgr.stop(1, 9)

    assert bytes_tx >= 1000
    final = repo.get_ue(1).stats[9]
    assert final.bytes_rx == final.bytes_tx  # UL and DL incremented together
    assert final.protocol == "tcp"
    assert final.target_bps == 8000
    assert mgr.is_running(1, 9) is False
