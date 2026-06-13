"""Tests for the FastAPI app composition in ``main.py``."""

from __future__ import annotations

from unittest.mock import MagicMock

import main


def test_app_metadata_and_router_are_wired() -> None:
    assert main.app.title == "Simple EPC Simulator"

    paths = {route.path for route in main.app.routes}
    assert "/" in paths
    assert "/ues" in paths
    assert "/ues/stats" in paths
    assert "/reset" in paths


def test_shutdown_event_stops_all_traffic(monkeypatch) -> None:
    fake_manager = MagicMock()
    # Avoid touching SQLite / the real singleton during the lifecycle hook.
    monkeypatch.setattr(main, "EPCRepository", MagicMock())
    monkeypatch.setattr(main, "get_traffic_manager", lambda _repo: fake_manager)

    main.shutdown_event()

    fake_manager.stop_all.assert_called_once()
