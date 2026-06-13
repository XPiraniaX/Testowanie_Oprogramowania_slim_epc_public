# Przygotował Kamil Gębala
from __future__ import annotations

import pytest
from pydantic import ValidationError

from epc_poprawione.models import (
    AddBearerRequest,
    AttachUERequest,
    BearerConfig,
    StartTrafficRequest,
    ThroughputStats,
    UEState,
)

# ue


@pytest.mark.parametrize("ue_id", [1, 100])
def test_attach_ue_request_accepts_boundary_ids(ue_id: int) -> None:
    request = AttachUERequest(ue_id=ue_id)

    assert request.ue_id == ue_id


@pytest.mark.parametrize("ue_id", [0, 101, 1020, -1])
def test_attach_ue_request_rejects_out_of_range_ids(ue_id: int) -> None:
    with pytest.raises(ValidationError):
        AttachUERequest(ue_id=ue_id)


# bearer


@pytest.mark.parametrize("bearer_id", [1, 9])
def test_add_bearer_request_accepts_boundary_ids(bearer_id: int) -> None:
    request = AddBearerRequest(bearer_id=bearer_id)

    assert request.bearer_id == bearer_id


@pytest.mark.parametrize("bearer_id", [0, 10, -1])
def test_add_bearer_request_rejects_out_of_range_ids(bearer_id: int) -> None:
    with pytest.raises(ValidationError):
        AddBearerRequest(bearer_id=bearer_id)


# traffic-


@pytest.mark.parametrize(
    ("payload", "expected_bps"),
    [
        ({"protocol": "tcp", "Mbps": 1.5}, 1_500_000),
        ({"protocol": "udp", "kbps": 250}, 250_000),
        ({"protocol": "tcp", "bps": 1234}, 1234),
    ],
)
def test_start_traffic_request_converts_units_to_target_bps(payload: dict, expected_bps: int) -> None:
    request = StartTrafficRequest(**payload)

    assert request.target_bps() == expected_bps


@pytest.mark.parametrize("protocol", ["icmp", "TCP", "", "http"])
def test_start_traffic_request_rejects_invalid_protocol(protocol: str) -> None:
    with pytest.raises(ValidationError):
        StartTrafficRequest(protocol=protocol, Mbps=1)


def test_start_traffic_request_requires_protocol() -> None:
    with pytest.raises(ValidationError):
        StartTrafficRequest(Mbps=1)


@pytest.mark.parametrize(
    "payload",
    [
        {"protocol": "tcp"},
        {"protocol": "tcp", "Mbps": 1, "kbps": 1000},
        {"protocol": "udp", "Mbps": 1, "kbps": 1000, "bps": 1000000},
    ],
)
def test_start_traffic_request_requires_exactly_one_throughput_unit(payload: dict) -> None:
    with pytest.raises(ValidationError):
        StartTrafficRequest(**payload)


# ue state


def test_ue_state_initializes_empty_defaults() -> None:
    state = UEState.model_validate({"ue_id": 7, "bearers": None, "stats": None})

    assert state.ue_id == 7
    assert state.bearers == {}
    assert state.stats == {}


# numeric coercion of integer id fields
def test_attach_ue_request_coerces_numeric_string_id() -> None:
    # Pydantic v2 (lax mode) coerces a numeric string to int.
    assert AttachUERequest(ue_id="5").ue_id == 5


@pytest.mark.parametrize("bad", [1.5, "abc", None, "5.5"])
def test_attach_ue_request_rejects_non_integer_values(bad) -> None:
    with pytest.raises(ValidationError):
        AttachUERequest(ue_id=bad)


# throughput conversion: borderline magnitudes
def test_start_traffic_request_zero_throughput_is_accepted_and_yields_zero() -> None:
    # 0 counts as a "provided" value (it is not None), so the exactly-one rule
    # passes and the canonical conversion is exactly 0.
    request = StartTrafficRequest(protocol="tcp", bps=0)

    assert request.target_bps() == 0


def test_start_traffic_request_allows_negative_throughput() -> None:
    # There is intentionally no lower-bound validation; this documents that a
    # negative value flows straight through the conversion unchanged.
    request = StartTrafficRequest(protocol="udp", bps=-100)

    assert request.target_bps() == -100


@pytest.mark.parametrize(
    ("payload", "expected_bps"),
    [
        ({"protocol": "tcp", "kbps": 1.2345}, 1234),       # truncates, not rounds
        ({"protocol": "tcp", "Mbps": 1.9999}, 1_999_900),
        ({"protocol": "udp", "Mbps": 0.0000004}, 0),       # sub-bit value floors to 0
        ({"protocol": "tcp", "bps": 999.99}, 999),         # float bps truncated
    ],
)
def test_start_traffic_request_truncates_fractional_values(payload: dict, expected_bps: int) -> None:
    assert StartTrafficRequest(**payload).target_bps() == expected_bps


def test_start_traffic_request_zero_value_still_counts_against_exactly_one_rule() -> None:
    # Providing bps=0 alongside another unit must still fail the exactly-one rule
    # (0 is a provided value, so this is "two values").
    with pytest.raises(ValidationError):
        StartTrafficRequest(protocol="tcp", bps=0, kbps=5)


# BearerConfig validation
def test_bearer_config_defaults() -> None:
    bearer = BearerConfig(bearer_id=1)

    assert bearer.protocol is None
    assert bearer.target_bps is None
    assert bearer.active is False


@pytest.mark.parametrize("bearer_id", [0, 10, -1])
def test_bearer_config_rejects_out_of_range_id(bearer_id: int) -> None:
    with pytest.raises(ValidationError):
        BearerConfig(bearer_id=bearer_id)


@pytest.mark.parametrize("protocol", ["icmp", "TCP", "UDP", "sctp", ""])
def test_bearer_config_rejects_invalid_protocol(protocol: str) -> None:
    with pytest.raises(ValidationError):
        BearerConfig(bearer_id=1, protocol=protocol)


# ThroughputStats defaults
def test_throughput_stats_defaults_are_zeroed() -> None:
    stats = ThroughputStats(ue_id=1, bearer_id=2)

    assert stats.bytes_tx == 0
    assert stats.bytes_rx == 0
    assert stats.start_ts is None
    assert stats.last_update_ts is None
    assert stats.protocol is None
    assert stats.target_bps is None


# UEState JSON round-trip (the contract relied upon by the SQLite repo)
def test_ue_state_json_round_trip_preserves_integer_dict_keys() -> None:
    state = UEState(
        ue_id=42,
        bearers={3: BearerConfig(bearer_id=3, protocol="tcp", target_bps=1000, active=True)},
        stats={3: ThroughputStats(ue_id=42, bearer_id=3, bytes_tx=10, bytes_rx=20)},
    )

    restored = UEState.model_validate_json(state.model_dump_json())

    # JSON object keys are strings on the wire, but must come back as ints.
    assert list(restored.bearers.keys()) == [3]
    assert isinstance(next(iter(restored.bearers.keys())), int)
    assert restored.bearers[3].protocol == "tcp"
    assert restored.stats[3].bytes_rx == 20
    assert restored == state


@pytest.mark.parametrize("ue_id", [0, 101, -1])
def test_ue_state_rejects_out_of_range_ue_id(ue_id: int) -> None:
    with pytest.raises(ValidationError):
        UEState(ue_id=ue_id)
