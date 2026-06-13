"""Repository tests for the SQLite-backed EPC state store."""

import pytest

from epc_poprawione.db import EPCRepository
from epc_poprawione.models import BearerConfig, ThroughputStats


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


# Borderline / edge cases
import sqlite3  # noqa: E402

from pydantic import ValidationError  # noqa: E402

from epc_poprawione.models import UEState  # noqa: E402


def test_ue_exists_and_list_ues_on_empty_db(repo):
    assert repo.ue_exists(1) is False
    assert list(repo.list_ues()) == []


def test_reset_all_on_empty_db_is_noop(repo):
    repo.reset_all()  # must not raise
    assert list(repo.list_ues()) == []


def test_add_bearer_out_of_range_raises_validation_error_not_value_error(repo):
    # The repository builds a ``BearerConfig`` internally, so an out-of-range
    # bearer id surfaces as a Pydantic ``ValidationError`` (NOT the domain
    # ``ValueError`` the API layer knows how to map to 400). This is a real gap
    # worth pinning down.
    repo.attach_ue(30)

    with pytest.raises(ValidationError):
        repo.add_bearer(30, 10)
    with pytest.raises(ValidationError):
        repo.add_bearer(30, 0)


def test_update_bearer_on_missing_ue_raises_value_error(repo):
    with pytest.raises(ValueError, match="UE not found"):
        repo.update_bearer(404, BearerConfig(bearer_id=1))


def test_update_stats_on_missing_ue_raises_value_error(repo):
    with pytest.raises(ValueError, match="UE not found"):
        repo.update_stats(404, ThroughputStats(ue_id=404, bearer_id=1))


def test_delete_bearer_on_missing_ue_raises_value_error(repo):
    with pytest.raises(ValueError, match="UE not found"):
        repo.delete_bearer(404, 2)


def test_delete_default_bearer_check_precedes_ue_existence_check(repo):
    # bearer_id == 9 is rejected before the UE is even looked up, so a missing
    # UE still produces the "Cannot remove default bearer" message.
    with pytest.raises(ValueError, match="Cannot remove default bearer"):
        repo.delete_bearer(999, 9)


def test_save_ue_overwrites_existing_row(repo, db_path):
    repo.attach_ue(40)

    state = repo.get_ue(40)
    state.bearers[2] = BearerConfig(bearer_id=2, protocol="udp", target_bps=42, active=True)
    repo.save_ue(state)

    reopened = EPCRepository(str(db_path))
    ue = reopened.get_ue(40)
    assert sorted(ue.bearers) == [2, 9]
    assert ue.bearers[2].target_bps == 42


def test_save_ue_can_create_a_row_for_a_new_ue(repo):
    # save_ue uses INSERT OR REPLACE, so it can persist a UE that was never
    # attached through attach_ue (no default bearer 9 in that case).
    repo.save_ue(UEState(ue_id=55))

    ue = repo.get_ue(55)
    assert ue.ue_id == 55
    assert ue.bearers == {}


def test_get_ue_with_corrupted_json_raises_validation_error(repo, db_path):
    repo.attach_ue(60)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("UPDATE ue_state SET data = ? WHERE ue_id = ?", ("not-json", 60))
        conn.commit()

    with pytest.raises(ValidationError):
        repo.get_ue(60)


def test_two_repositories_sharing_a_file_see_each_others_writes(repo, db_path):
    other = EPCRepository(str(db_path))

    repo.attach_ue(70)
    assert other.ue_exists(70) is True

    other.add_bearer(70, 1)
    assert sorted(repo.get_ue(70).bearers) == [1, 9]


def test_can_add_all_non_default_bearers_one_through_eight(repo):
    repo.attach_ue(80)
    for bearer_id in range(1, 9):
        repo.add_bearer(80, bearer_id)

    assert sorted(repo.get_ue(80).bearers) == list(range(1, 10))


def test_repository_uses_env_path_when_none_passed(tmp_path, monkeypatch):
    custom = tmp_path / "from_env.db"
    monkeypatch.setattr("epc.db.EPC_DB_PATH", str(custom))

    repo = EPCRepository()  # no explicit path -> falls back to module default
    repo.attach_ue(90)

    assert custom.exists()
    assert list(EPCRepository(str(custom)).list_ues()) == [90]
