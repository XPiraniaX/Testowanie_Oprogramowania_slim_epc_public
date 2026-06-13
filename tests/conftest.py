from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient

import epc.api as api_module
from epc.api import get_repo
from epc.db import EPCRepository
from main import app


class FakeTrafficManager:
    """Small synchronous fake used to avoid testing the async traffic loop."""

    def __init__(self) -> None:
        self.running: set[tuple[int, int]] = set()
        self.started: list[tuple[int, int, int, str]] = []
        self.stopped: list[tuple[int, int]] = []
        self.stop_all_called = False

    def start(self, ue_id: int, bearer) -> None:
        key = (ue_id, bearer.bearer_id)
        if key in self.running:
            raise ValueError("Traffic already running")
        if not bearer.target_bps or not bearer.protocol:
            raise ValueError("Bearer not configured for traffic")
        self.running.add(key)
        self.started.append((ue_id, bearer.bearer_id, bearer.target_bps, bearer.protocol))

    def stop(self, ue_id: int, bearer_id: int) -> None:
        key = (ue_id, bearer_id)
        self.running.discard(key)
        self.stopped.append(key)

    def stop_all(self) -> None:
        self.running.clear()
        self.stop_all_called = True

    def is_running(self, ue_id: int, bearer_id: int) -> bool:
        return (ue_id, bearer_id) in self.running


@pytest.fixture
def repo(tmp_path) -> EPCRepository:
    return EPCRepository(str(tmp_path / "epc_test.db"))


@pytest.fixture
def fake_traffic_manager(monkeypatch) -> FakeTrafficManager:
    fake = FakeTrafficManager()
    monkeypatch.setattr(api_module, "get_traffic_manager", lambda _repo: fake)
    return fake


@pytest.fixture
def client(repo: EPCRepository, fake_traffic_manager: FakeTrafficManager) -> Iterator[TestClient]:
    app.dependency_overrides[get_repo] = lambda: repo
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    fake_traffic_manager.stop_all()
