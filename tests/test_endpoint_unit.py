
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from epc import api
from epc.api import (
    add_bearer,
    attach_ue,
    delete_bearer,
    detach_ue,
    get_traffic_stats,
    get_ue,
    get_ues_stats,
    list_ues,
    reset_all,
    start_traffic,
    stop_traffic,
)
from epc.models import (
    AddBearerRequest,
    AttachUERequest,
    BearerConfig,
    StartTrafficRequest,
    ThroughputStats,
    UEState,
)


@pytest.fixture
def repo():
    """A fully mocked repository (no real SQLite access)."""
    return MagicMock()


@pytest.fixture
def tm(monkeypatch):
    """Patch ``get_traffic_manager`` so handlers receive a mocked manager."""
    manager = MagicMock()
    manager.is_running.return_value = False
    monkeypatch.setattr(api, "get_traffic_manager", lambda _r: manager)
    return manager


# attach_ue
def test_attach_ue_success(repo):
    resp = attach_ue(AttachUERequest(ue_id=1), repo)

    repo.attach_ue.assert_called_once_with(1)
    assert resp.status == "attached"
    assert resp.ue_id == 1


def test_attach_ue_value_error_maps_to_400(repo):
    repo.attach_ue.side_effect = ValueError("UE already attached")

    with pytest.raises(HTTPException) as exc:
        attach_ue(AttachUERequest(ue_id=1), repo)

    assert exc.value.status_code == 400
    assert exc.value.detail == "UE already attached"


# list_ues
def test_list_ues_returns_ids(repo):
    repo.list_ues.return_value = [1, 2, 3]

    resp = list_ues(repo)

    assert resp.ues == [1, 2, 3]


# get_ue
def test_get_ue_success(repo):
    repo.get_ue.return_value = UEState(ue_id=5)

    resp = get_ue(5, repo)

    assert resp.ue_id == 5


def test_get_ue_not_found_maps_to_400(repo):
    repo.get_ue.side_effect = ValueError("UE not found")

    with pytest.raises(HTTPException) as exc:
        get_ue(5, repo)

    assert exc.value.status_code == 400
    assert exc.value.detail == "UE not found"


# detach_ue
def test_detach_ue_success(repo):
    resp = detach_ue(7, repo)

    repo.detach_ue.assert_called_once_with(7)
    assert resp.status == "detached"
    assert resp.ue_id == 7


def test_detach_ue_not_found_maps_to_400(repo):
    repo.detach_ue.side_effect = ValueError("UE not found")

    with pytest.raises(HTTPException) as exc:
        detach_ue(7, repo)

    assert exc.value.status_code == 400


# add_bearer
def test_add_bearer_success(repo):
    resp = add_bearer(1, AddBearerRequest(bearer_id=2), repo)

    repo.add_bearer.assert_called_once_with(1, 2)
    assert resp.status == "bearer_added"
    assert resp.ue_id == 1
    assert resp.bearer_id == 2


def test_add_bearer_value_error_maps_to_400(repo):
    repo.add_bearer.side_effect = ValueError("Bearer already exists")

    with pytest.raises(HTTPException) as exc:
        add_bearer(1, AddBearerRequest(bearer_id=2), repo)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Bearer already exists"


# delete_bearer
@pytest.mark.usefixtures("tm")
def test_delete_bearer_success(repo):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={2: BearerConfig(bearer_id=2)})

    resp = delete_bearer(1, 2, repo)

    repo.delete_bearer.assert_called_once_with(1, 2)
    assert resp.status == "bearer_deleted"
    assert resp.bearer_id == 2


def test_delete_bearer_stops_running_traffic_first(repo, tm):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={2: BearerConfig(bearer_id=2)})
    tm.is_running.return_value = True

    delete_bearer(1, 2, repo)

    tm.stop.assert_called_once_with(1, 2)
    repo.delete_bearer.assert_called_once_with(1, 2)


def test_delete_bearer_ue_not_found_maps_to_400(repo):
    repo.get_ue.side_effect = ValueError("UE not found")

    with pytest.raises(HTTPException) as exc:
        delete_bearer(1, 2, repo)

    assert exc.value.status_code == 400
    repo.delete_bearer.assert_not_called()


def test_delete_bearer_unknown_bearer_maps_to_400(repo):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={})

    with pytest.raises(HTTPException) as exc:
        delete_bearer(1, 2, repo)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Bearer not found"


@pytest.mark.usefixtures("tm")
def test_delete_bearer_default_bearer_protected_maps_to_400(repo):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={9: BearerConfig(bearer_id=9)})
    repo.delete_bearer.side_effect = ValueError("Cannot remove default bearer")

    with pytest.raises(HTTPException) as exc:
        delete_bearer(1, 9, repo)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Cannot remove default bearer"


# start_traffic
def test_start_traffic_success(repo, tm):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={1: BearerConfig(bearer_id=1)})

    resp = start_traffic(1, 1, StartTrafficRequest(protocol="tcp", Mbps=1), repo)

    assert resp.status == "traffic_started"
    assert resp.target_bps == 1_000_000
    repo.update_bearer.assert_called_once()
    repo.update_stats.assert_called_once()
    tm.start.assert_called_once()


def test_start_traffic_ue_not_found_maps_to_400(repo, tm):
    repo.get_ue.side_effect = ValueError("UE not found")

    with pytest.raises(HTTPException) as exc:
        start_traffic(1, 1, StartTrafficRequest(protocol="tcp", Mbps=1), repo)

    assert exc.value.status_code == 400
    tm.start.assert_not_called()


def test_start_traffic_unknown_bearer_maps_to_400(repo):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={})

    with pytest.raises(HTTPException) as exc:
        start_traffic(1, 1, StartTrafficRequest(protocol="tcp", Mbps=1), repo)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Bearer not found"


def test_start_traffic_already_running_maps_to_400(repo, tm):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={1: BearerConfig(bearer_id=1)})
    tm.start.side_effect = ValueError("Traffic already running")

    with pytest.raises(HTTPException) as exc:
        start_traffic(1, 1, StartTrafficRequest(protocol="tcp", Mbps=1), repo)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Traffic already running"


# stop_traffic
def test_stop_traffic_success(repo, tm):
    repo.get_ue.return_value = UEState(
        ue_id=1, bearers={1: BearerConfig(bearer_id=1, active=True)}
    )

    resp = stop_traffic(1, 1, repo)

    tm.stop.assert_called_once_with(1, 1)
    repo.update_bearer.assert_called_once()
    assert resp.status == "traffic_stopped"


def test_stop_traffic_ue_not_found_maps_to_400(repo, tm):
    repo.get_ue.side_effect = ValueError("UE not found")

    with pytest.raises(HTTPException) as exc:
        stop_traffic(1, 1, repo)

    assert exc.value.status_code == 400
    tm.stop.assert_not_called()


def test_stop_traffic_unknown_bearer_maps_to_400(repo):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={})

    with pytest.raises(HTTPException) as exc:
        stop_traffic(1, 1, repo)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Bearer not found"


# get_traffic_stats
def test_get_traffic_stats_without_stats_returns_zeros(repo):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={1: BearerConfig(bearer_id=1)})

    resp = get_traffic_stats(1, 1, repo)

    assert resp.tx_bps == 0
    assert resp.rx_bps == 0
    assert resp.duration == 0
    assert resp.protocol is None


@pytest.mark.usefixtures("tm")
def test_get_traffic_stats_computes_throughput(repo):
    # 125000 bytes over 10 s -> 125000 * 8 / 10 = 100000 bps
    stats = ThroughputStats(
        bearer_id=1,
        ue_id=1,
        bytes_tx=125_000,
        bytes_rx=125_000,
        start_ts=1_000.0,
        last_update_ts=1_010.0,
        protocol="tcp",
        target_bps=100_000,
    )
    repo.get_ue.return_value = UEState(
        ue_id=1, bearers={1: BearerConfig(bearer_id=1)}, stats={1: stats}
    )

    resp = get_traffic_stats(1, 1, repo)

    assert resp.duration == 10
    assert resp.tx_bps == 100_000
    assert resp.rx_bps == 100_000
    assert resp.protocol == "tcp"
    assert resp.target_bps == 100_000


def test_get_traffic_stats_ue_not_found_maps_to_400(repo):
    repo.get_ue.side_effect = ValueError("UE not found")

    with pytest.raises(HTTPException) as exc:
        get_traffic_stats(1, 1, repo)

    assert exc.value.status_code == 400


# get_ues_stats (aggregation decisions)
def _stats(bytes_count: int) -> ThroughputStats:
    return ThroughputStats(
        bearer_id=1,
        ue_id=1,
        bytes_tx=bytes_count,
        bytes_rx=bytes_count,
        start_ts=1_000.0,
        last_update_ts=1_010.0,
    )


@pytest.mark.usefixtures("tm")
def test_get_ues_stats_aggregates_all_ues(repo):
    repo.list_ues.return_value = [1, 2]
    states = {
        1: UEState(ue_id=1, stats={1: _stats(125_000)}),
        2: UEState(ue_id=2, stats={}),
    }
    repo.get_ue.side_effect = lambda uid: states[uid]

    resp = get_ues_stats(repo)

    assert resp.scope == "all"
    assert resp.ue_count == 2
    assert resp.bearer_count == 1
    assert resp.total_tx_bps == 100_000
    assert resp.total_rx_bps == 100_000
    assert resp.details is None


@pytest.mark.usefixtures("tm")
def test_get_ues_stats_single_ue_with_details(repo):
    repo.ue_exists.return_value = True
    repo.get_ue.return_value = UEState(ue_id=1, stats={1: _stats(125_000)})

    resp = get_ues_stats(repo, ue_id=1, include_details=True)

    assert resp.scope == "ue:1"
    assert resp.ue_count == 1
    assert resp.bearer_count == 1
    assert resp.details == {"1": {"1": 100_000}}


def test_get_ues_stats_unknown_ue_maps_to_400(repo):
    repo.ue_exists.return_value = False

    with pytest.raises(HTTPException) as exc:
        get_ues_stats(repo, ue_id=99)

    assert exc.value.status_code == 400
    assert exc.value.detail == "UE not found"


@pytest.mark.usefixtures("tm")
def test_get_ues_stats_empty_when_no_ues(repo):
    repo.list_ues.return_value = []

    resp = get_ues_stats(repo)

    assert resp.scope == "all"
    assert resp.ue_count == 0
    assert resp.bearer_count == 0
    assert resp.total_tx_bps == 0
    assert resp.total_rx_bps == 0


# reset_all
def test_reset_all_stops_traffic_and_clears_state(repo, tm):
    resp = reset_all(repo)

    tm.stop_all.assert_called_once()
    repo.reset_all.assert_called_once()
    assert resp.status == "reset"


# Edge / boundary cases
class _FixedClock:
    """Deterministic replacement for the ``time`` module used in ``epc.api``."""

    @staticmethod
    def time() -> float:
        return 1_010.0


@pytest.mark.usefixtures("tm")
def test_start_traffic_kbps_conversion(repo):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={1: BearerConfig(bearer_id=1)})

    resp = start_traffic(1, 1, StartTrafficRequest(protocol="udp", kbps=500), repo)

    assert resp.target_bps == 500_000


@pytest.mark.usefixtures("tm")
def test_start_traffic_bps_conversion(repo):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={1: BearerConfig(bearer_id=1)})

    resp = start_traffic(1, 1, StartTrafficRequest(protocol="tcp", bps=1000), repo)

    assert resp.target_bps == 1000


@pytest.mark.usefixtures("tm")
def test_start_traffic_fractional_mbps_truncates(repo):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={1: BearerConfig(bearer_id=1)})


    resp = start_traffic(1, 1, StartTrafficRequest(protocol="tcp", Mbps=1.5), repo)

    assert resp.target_bps == 1_500_000


@pytest.mark.usefixtures("tm")
def test_get_traffic_stats_zero_duration_no_division_error(repo):

    stats = ThroughputStats(
        bearer_id=1,
        ue_id=1,
        bytes_tx=999,
        bytes_rx=999,
        start_ts=1_000.0,
        last_update_ts=1_000.0,
    )
    repo.get_ue.return_value = UEState(
        ue_id=1, bearers={1: BearerConfig(bearer_id=1)}, stats={1: stats}
    )

    resp = get_traffic_stats(1, 1, repo)

    assert resp.duration == 0
    assert resp.tx_bps == 0
    assert resp.rx_bps == 0


def test_get_traffic_stats_while_running_uses_current_time(repo, tm, monkeypatch):
    monkeypatch.setattr(api, "time", _FixedClock)
    tm.is_running.return_value = True

    stats = ThroughputStats(
        bearer_id=1,
        ue_id=1,
        bytes_tx=125_000,
        bytes_rx=125_000,
        start_ts=1_000.0,
        last_update_ts=1_001.0,
    )
    repo.get_ue.return_value = UEState(
        ue_id=1, bearers={1: BearerConfig(bearer_id=1)}, stats={1: stats}
    )

    resp = get_traffic_stats(1, 1, repo)

    assert resp.duration == 10
    assert resp.tx_bps == 100_000


@pytest.mark.usefixtures("tm")
def test_get_ues_stats_single_ue_exists_but_fetch_raises_maps_to_400(repo):

    repo.ue_exists.return_value = True
    repo.get_ue.side_effect = ValueError("UE not found")

    with pytest.raises(HTTPException) as exc:
        get_ues_stats(repo, ue_id=1)

    assert exc.value.status_code == 400


@pytest.mark.usefixtures("tm")
def test_get_ues_stats_all_skips_ue_that_disappears(repo):

    repo.list_ues.return_value = [1, 2]

    def fake_get_ue(uid):
        if uid == 1:
            raise ValueError("UE not found")
        return UEState(ue_id=2, stats={1: _stats(125_000)})

    repo.get_ue.side_effect = fake_get_ue

    resp = get_ues_stats(repo)

    assert resp.ue_count == 2
    assert resp.bearer_count == 1
    assert resp.total_tx_bps == 100_000


# Additional branch coverage
def test_delete_bearer_does_not_stop_when_traffic_not_running(repo, tm):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={2: BearerConfig(bearer_id=2)})
    tm.is_running.return_value = False

    delete_bearer(1, 2, repo)

    tm.stop.assert_not_called()
    repo.delete_bearer.assert_called_once_with(1, 2)


@pytest.mark.usefixtures("tm")
def test_delete_bearer_value_error_after_passing_presence_check_maps_to_400(repo):
    # Bearer is present in state, but repo.delete_bearer still raises (e.g. a
    # race / invariant violation) -> mapped to 400.
    repo.get_ue.return_value = UEState(ue_id=1, bearers={2: BearerConfig(bearer_id=2)})
    repo.delete_bearer.side_effect = ValueError("boom")

    with pytest.raises(HTTPException) as exc:
        delete_bearer(1, 2, repo)

    assert exc.value.status_code == 400
    assert exc.value.detail == "boom"


def test_start_traffic_does_not_recreate_stats_when_already_present(repo, tm):
    # When stats already exist for the bearer, start_traffic must NOT reset them
    # (only update_bearer is called, update_stats is skipped).
    existing = ThroughputStats(ue_id=1, bearer_id=1, bytes_tx=500, bytes_rx=500)
    repo.get_ue.return_value = UEState(
        ue_id=1, bearers={1: BearerConfig(bearer_id=1)}, stats={1: existing}
    )

    resp = start_traffic(1, 1, StartTrafficRequest(protocol="tcp", Mbps=1), repo)

    assert resp.status == "traffic_started"
    repo.update_bearer.assert_called_once()
    repo.update_stats.assert_not_called()
    tm.start.assert_called_once()


@pytest.mark.usefixtures("tm")
def test_start_traffic_lowercases_and_persists_protocol(repo):
    repo.get_ue.return_value = UEState(ue_id=1, bearers={1: BearerConfig(bearer_id=1)})

    start_traffic(1, 1, StartTrafficRequest(protocol="udp", bps=8000), repo)

    persisted_bearer = repo.update_bearer.call_args.args[1]
    assert persisted_bearer.protocol == "udp"
    assert persisted_bearer.target_bps == 8000
    assert persisted_bearer.active is True


def test_stop_traffic_marks_bearer_inactive_even_if_not_running(repo, tm):
    repo.get_ue.return_value = UEState(
        ue_id=1, bearers={1: BearerConfig(bearer_id=1, active=True)}
    )
    tm.is_running.return_value = False

    stop_traffic(1, 1, repo)

    tm.stop.assert_called_once_with(1, 1)
    persisted_bearer = repo.update_bearer.call_args.args[1]
    assert persisted_bearer.active is False


def test_get_ues_stats_running_bearer_uses_current_time(repo, tm, monkeypatch):
    # When the bearer is running, end_ts uses time.time() (not last_update_ts).
    monkeypatch.setattr(api, "time", _FixedClock)  # time.time() -> 1010.0
    tm.is_running.return_value = True
    stats = ThroughputStats(
        bearer_id=1,
        ue_id=1,
        bytes_tx=125_000,
        bytes_rx=125_000,
        start_ts=1_000.0,
        last_update_ts=1_001.0,  # would give a different number if used
    )
    repo.ue_exists.return_value = True
    repo.get_ue.return_value = UEState(ue_id=1, stats={1: stats})

    resp = get_ues_stats(repo, ue_id=1)

    # duration = 1010 - 1000 = 10 -> 125000 * 8 / 10 = 100000
    assert resp.total_tx_bps == 100_000


@pytest.mark.usefixtures("tm")
def test_get_ues_stats_details_across_multiple_ues(repo):
    repo.list_ues.return_value = [1, 2]
    states = {
        1: UEState(ue_id=1, stats={1: _stats(125_000)}),
        2: UEState(ue_id=2, stats={9: _stats(250_000)}),
    }
    repo.get_ue.side_effect = lambda uid: states[uid]

    resp = get_ues_stats(repo, include_details=True)

    assert resp.bearer_count == 2
    assert resp.details == {"1": {"1": 100_000}, "2": {"9": 200_000}}


@pytest.mark.usefixtures("tm")
def test_get_traffic_stats_stats_without_start_ts_yields_zero_duration(repo):
    # start_ts is None -> duration falls back to 0 (no division).
    stats = ThroughputStats(ue_id=1, bearer_id=1, bytes_tx=10, bytes_rx=10)
    repo.get_ue.return_value = UEState(
        ue_id=1, bearers={1: BearerConfig(bearer_id=1)}, stats={1: stats}
    )

    resp = get_traffic_stats(1, 1, repo)

    assert resp.duration == 0
    assert resp.tx_bps == 0
    assert resp.rx_bps == 0
