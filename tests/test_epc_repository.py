"""Repository tests for the SQLite-backed EPC state store."""

import pytest

from epc.db import EPCRepository
from epc.models import BearerConfig, ThroughputStats


@pytest.fixture
def db_path(tmp_path):
    """Use an isolated SQLite file per test."""
    return tmp_path / "epc.db"


@pytest.fixture
def repo(db_path):
    return EPCRepository(str(db_path))


def test_attach_get_list_and_detach_ue_flow(repo):
    repo.attach_ue(2)
    repo.attach_ue(1)

    assert list(repo.list_ues()) == [1, 2]

    ue = repo.get_ue(1)
    assert ue.ue_id == 1
    assert sorted(ue.bearers) == [9]
    assert ue.bearers[9] == BearerConfig(bearer_id=9)
    assert ue.stats == {}

    repo.detach_ue(1)

    assert list(repo.list_ues()) == [2]
    with pytest.raises(ValueError, match="UE not found"):
        repo.get_ue(1)


def test_attach_rejects_duplicate_ue_and_detach_requires_existing_ue(repo):
    repo.attach_ue(7)

    with pytest.raises(ValueError, match="UE already attached"):
        repo.attach_ue(7)

    with pytest.raises(ValueError, match="UE not found"):
        repo.detach_ue(8)

    assert list(repo.list_ues()) == [7]


def test_add_bearer_persists_new_bearer_and_rejects_duplicate(repo, db_path):
    repo.attach_ue(10)
    repo.add_bearer(10, 3)

    reopened = EPCRepository(str(db_path))
    ue = reopened.get_ue(10)

    assert sorted(ue.bearers) == [3, 9]
    assert ue.bearers[3] == BearerConfig(bearer_id=3)

    with pytest.raises(ValueError, match="Bearer already exists"):
        reopened.add_bearer(10, 3)


def test_add_bearer_requires_attached_ue(repo):
    with pytest.raises(ValueError, match="UE not found"):
        repo.add_bearer(99, 1)


def test_delete_bearer_removes_config_and_stats_but_keeps_default_bearer(repo):
    repo.attach_ue(12)
    repo.add_bearer(12, 4)
    repo.update_stats(
        12,
        ThroughputStats(
            ue_id=12,
            bearer_id=4,
            bytes_tx=100,
            bytes_rx=200,
            protocol="tcp",
            target_bps=1_000,
        ),
    )

    repo.delete_bearer(12, 4)

    ue = repo.get_ue(12)
    assert sorted(ue.bearers) == [9]
    assert 4 not in ue.stats


def test_delete_bearer_requires_existing_bearer(repo):
    repo.attach_ue(13)

    with pytest.raises(ValueError, match="Bearer not found"):
        repo.delete_bearer(13, 5)


def test_default_bearer_9_is_created_and_cannot_be_deleted_or_added_again(repo):
    repo.attach_ue(14)

    with pytest.raises(ValueError, match="Cannot remove default bearer"):
        repo.delete_bearer(14, 9)

    with pytest.raises(ValueError, match="Bearer already exists"):
        repo.add_bearer(14, 9)

    assert sorted(repo.get_ue(14).bearers) == [9]


def test_update_bearer_and_update_stats_are_persisted(repo, db_path):
    repo.attach_ue(20)
    repo.add_bearer(20, 2)

    repo.update_bearer(
        20,
        BearerConfig(
            bearer_id=2,
            protocol="udp",
            target_bps=2_500,
            active=True,
        ),
    )
    repo.update_stats(
        20,
        ThroughputStats(
            ue_id=20,
            bearer_id=2,
            bytes_tx=321,
            bytes_rx=654,
            start_ts=1.5,
            last_update_ts=2.5,
            protocol="udp",
            target_bps=2_500,
        ),
    )

    reopened = EPCRepository(str(db_path))
    ue = reopened.get_ue(20)

    assert ue.bearers[2] == BearerConfig(
        bearer_id=2,
        protocol="udp",
        target_bps=2_500,
        active=True,
    )
    assert ue.stats[2] == ThroughputStats(
        ue_id=20,
        bearer_id=2,
        bytes_tx=321,
        bytes_rx=654,
        start_ts=1.5,
        last_update_ts=2.5,
        protocol="udp",
        target_bps=2_500,
    )


def test_reset_all_removes_every_persisted_ue(repo, db_path):
    for ue_id in [3, 1, 2]:
        repo.attach_ue(ue_id)
    repo.add_bearer(1, 5)
    repo.update_stats(1, ThroughputStats(ue_id=1, bearer_id=5, bytes_tx=50))

    repo.reset_all()

    assert list(repo.list_ues()) == []

    reopened = EPCRepository(str(db_path))
    assert list(reopened.list_ues()) == []
    for ue_id in [1, 2, 3]:
        with pytest.raises(ValueError, match="UE not found"):
            reopened.get_ue(ue_id)
