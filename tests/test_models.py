#Przygotował Kamil Gębala
from __future__ import annotations

import pytest
from pydantic import ValidationError

from epc.models import AddBearerRequest, AttachUERequest, StartTrafficRequest, UEState


@pytest.mark.parametrize("ue_id", [1, 100])
def test_attach_ue_request_accepts_boundary_ids(ue_id: int) -> None:
    assert AttachUERequest(ue_id=ue_id).ue_id == ue_id


@pytest.mark.parametrize("ue_id", [0, 101, 1020, -1])
def test_attach_ue_api_rejects_out_of_range_ids(client, ue_id: int) -> None:
    response = client.post("/ues", json={"ue_id": ue_id})
    assert response.status_code == 422

@pytest.mark.parametrize("bearer_id", [1, 9])
def test_add_bearer_request_accepts_boundary_ids(bearer_id: int) -> None:
    assert AddBearerRequest(bearer_id=bearer_id).bearer_id == bearer_id


@pytest.mark.parametrize("bearer_id", [0, 10, -1])
def test_add_bearer_request_rejects_out_of_range_ids(bearer_id: int) -> None:
    with pytest.raises(ValidationError):
        AddBearerRequest(bearer_id=bearer_id)


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


def test_ue_state_initializes_empty_defaults() -> None:
    state = UEState.model_validate({"ue_id": 7, "bearers": None, "stats": None})

    assert state.ue_id == 7
    assert state.bearers == {}
    assert state.stats == {}
