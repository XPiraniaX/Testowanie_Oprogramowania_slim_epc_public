# Przygotował Kamil Gębala
from __future__ import annotations

import pytest


def test_root_health_check(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "EPC Simulator running"}


# ue


def test_ues_happy_path_response_shapes(client) -> None:
    assert client.get("/ues").json() == {"ues": []}

    attach_response = client.post("/ues", json={"ue_id": 5})
    assert attach_response.status_code == 200
    assert attach_response.json() == {"status": "attached", "ue_id": 5}

    list_response = client.get("/ues")
    assert list_response.status_code == 200
    assert list_response.json() == {"ues": [5]}

    get_response = client.get("/ues/5")
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["ue_id"] == 5
    assert "9" in body["bearers"]
    assert body["stats"] == {}


@pytest.mark.parametrize("ue_id", [0, 101, 1020, -1])
def test_attach_ue_api_rejects_out_of_range_ids(client, ue_id: int) -> None:
    response = client.post("/ues", json={"ue_id": ue_id})

    assert response.status_code == 422


def test_detach_removes_ue_from_api_state(client) -> None:
    client.post("/ues", json={"ue_id": 7})

    detach_response = client.delete("/ues/7")
    assert detach_response.status_code == 200
    assert detach_response.json() == {"status": "detached", "ue_id": 7}

    get_response = client.get("/ues/7")
    assert get_response.status_code == 400
    assert get_response.json()["detail"] == "UE not found"


# bearer


def test_bearer_happy_path_response_shapes(client) -> None:
    client.post("/ues", json={"ue_id": 1})

    add_response = client.post("/ues/1/bearers", json={"bearer_id": 2})
    assert add_response.status_code == 200
    assert add_response.json() == {"status": "bearer_added", "ue_id": 1, "bearer_id": 2}

    ue_response = client.get("/ues/1")
    assert ue_response.status_code == 200
    assert "2" in ue_response.json()["bearers"]

    delete_response = client.delete("/ues/1/bearers/2")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "bearer_deleted", "ue_id": 1, "bearer_id": 2}


# traffic


def test_traffic_start_read_stop_contract_without_async_loop(client, fake_traffic_manager) -> None:
    client.post("/ues", json={"ue_id": 1})
    client.post("/ues/1/bearers", json={"bearer_id": 3})

    start_response = client.post("/ues/1/bearers/3/traffic", json={"protocol": "tcp", "kbps": 64})
    assert start_response.status_code == 200
    assert start_response.json() == {
        "status": "traffic_started",
        "ue_id": 1,
        "bearer_id": 3,
        "target_bps": 64_000,
    }
    assert fake_traffic_manager.started == [(1, 3, 64_000, "tcp")]

    stats_response = client.get("/ues/1/bearers/3/traffic")
    assert stats_response.status_code == 200
    stats = stats_response.json()
    assert stats["ue_id"] == 1
    assert stats["bearer_id"] == 3
    assert stats["protocol"] == "tcp"
    assert stats["target_bps"] == 64_000
    assert isinstance(stats["tx_bps"], int)
    assert isinstance(stats["rx_bps"], int)
    assert isinstance(stats["duration"], float)

    stop_response = client.delete("/ues/1/bearers/3/traffic")
    assert stop_response.status_code == 200
    assert stop_response.json() == {"status": "traffic_stopped", "ue_id": 1, "bearer_id": 3}
    assert (1, 3) in fake_traffic_manager.stopped


def test_traffic_stats_for_bearer_without_stats_returns_zero_shape(client) -> None:
    client.post("/ues", json={"ue_id": 1})

    response = client.get("/ues/1/bearers/9/traffic")

    assert response.status_code == 200
    assert response.json() == {
        "ue_id": 1,
        "bearer_id": 9,
        "protocol": None,
        "target_bps": None,
        "tx_bps": 0,
        "rx_bps": 0,
        "duration": 0.0,
    }


def test_start_traffic_for_missing_bearer_returns_400(client) -> None:
    client.post("/ues", json={"ue_id": 1})

    response = client.post("/ues/1/bearers/3/traffic", json={"protocol": "tcp", "Mbps": 1})

    assert response.status_code == 400
    assert response.json()["detail"] == "Bearer not found"


def test_stop_traffic_for_missing_bearer_returns_400(client) -> None:
    client.post("/ues", json={"ue_id": 1})

    response = client.delete("/ues/1/bearers/3/traffic")

    assert response.status_code == 400
    assert response.json()["detail"] == "Bearer not found"


# full


def test_full_state_transition_attach_add_start_read_stop_detach(client) -> None:
    assert client.post("/ues", json={"ue_id": 11}).status_code == 200
    assert client.post("/ues/11/bearers", json={"bearer_id": 1}).status_code == 200
    assert client.post("/ues/11/bearers/1/traffic", json={"protocol": "udp", "bps": 8000}).status_code == 200
    assert client.get("/ues/11/bearers/1/traffic").status_code == 200
    assert client.delete("/ues/11/bearers/1/traffic").status_code == 200

    detach_response = client.delete("/ues/11")
    assert detach_response.status_code == 200
    assert detach_response.json() == {"status": "detached", "ue_id": 11}
    assert client.get("/ues").json() == {"ues": []}


# validation


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("post", "/ues/1/bearers", {"bearer_id": 0}),
        ("post", "/ues/1/bearers", {"bearer_id": 10}),
        ("post", "/ues/1/bearers/9/traffic", {"protocol": "icmp", "Mbps": 1}),
        ("post", "/ues/1/bearers/9/traffic", {"protocol": "tcp"}),
        ("post", "/ues/1/bearers/9/traffic", {"protocol": "tcp", "Mbps": 1, "kbps": 1000}),
    ],
)
def test_request_validation_errors_return_422(client, method: str, path: str, json_body: dict) -> None:
    if "/bearers" in path:
        client.post("/ues", json={"ue_id": 1})

    response = getattr(client, method)(path, json=json_body)

    assert response.status_code == 422


def test_domain_errors_return_400(client) -> None:
    assert client.get("/ues/1").status_code == 400
    assert client.delete("/ues/1").status_code == 400
    assert client.post("/ues/99/bearers", json={"bearer_id": 1}).status_code == 400

    assert client.post("/ues", json={"ue_id": 1}).status_code == 200

    duplicate_attach = client.post("/ues", json={"ue_id": 1})
    assert duplicate_attach.status_code == 400
    assert duplicate_attach.json()["detail"] == "UE already attached"

    duplicate_bearer = client.post("/ues/1/bearers", json={"bearer_id": 9})
    assert duplicate_bearer.status_code == 400
    assert duplicate_bearer.json()["detail"] == "Bearer already exists"

    missing_bearer = client.delete("/ues/1/bearers/4")
    assert missing_bearer.status_code == 400
    assert missing_bearer.json()["detail"] == "Bearer not found"

    default_bearer = client.delete("/ues/1/bearers/9")
    assert default_bearer.status_code == 400
    assert default_bearer.json()["detail"] == "Cannot remove default bearer"


# stats


def test_ues_stats_route_is_not_captured_by_ue_id_route(client) -> None:
    response = client.get("/ues/stats")

    assert response.status_code == 200
    assert response.json() == {
        "scope": "all",
        "ue_count": 0,
        "bearer_count": 0,
        "total_tx_bps": 0,
        "total_rx_bps": 0,
        "details": None,
    }


def test_ues_stats_with_filter_and_details_shape(client, repo) -> None:
    from epc.models import ThroughputStats

    client.post("/ues", json={"ue_id": 2})
    repo.update_stats(
        2,
        ThroughputStats(
            ue_id=2,
            bearer_id=9,
            bytes_tx=1000,
            bytes_rx=3000,
            start_ts=100.0,
            last_update_ts=110.0,
            protocol="tcp",
            target_bps=1000,
        ),
    )

    response = client.get("/ues/stats?ue_id=2&include_details=true")

    assert response.status_code == 200
    assert response.json() == {
        "scope": "ue:2",
        "ue_count": 1,
        "bearer_count": 1,
        "total_tx_bps": 800,
        "total_rx_bps": 2400,
        "details": {"2": {"9": 800}},
    }


def test_ues_stats_for_missing_ue_returns_400(client) -> None:
    response = client.get("/ues/stats?ue_id=99")

    assert response.status_code == 400
    assert response.json()["detail"] == "UE not found"


# reset


def test_reset_restores_clean_state(client, fake_traffic_manager) -> None:
    client.post("/ues", json={"ue_id": 1})
    client.post("/ues/1/bearers", json={"bearer_id": 1})

    start_response = client.post("/ues/1/bearers/1/traffic", json={"protocol": "tcp", "Mbps": 1})
    assert start_response.status_code == 200

    reset_response = client.post("/reset")

    assert reset_response.status_code == 200
    assert reset_response.json() == {"status": "reset"}
    assert client.get("/ues").json() == {"ues": []}
    assert fake_traffic_manager.stop_all_called is True


# Borderline / edge cases
def test_openapi_and_docs_endpoints_are_served(client) -> None:
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("put", "/ues"),
        ("delete", "/ues"),
        ("patch", "/ues/1"),
        ("put", "/reset"),
    ],
)
def test_unsupported_methods_return_405(client, method: str, path: str) -> None:
    response = getattr(client, method)(path)

    assert response.status_code == 405


def test_unknown_route_returns_404(client) -> None:
    assert client.get("/does-not-exist").status_code == 404


@pytest.mark.parametrize("ue_path", ["/ues/abc", "/ues/1.5", "/ues/true"])
def test_non_integer_ue_path_param_returns_422(client, ue_path: str) -> None:
    assert client.get(ue_path).status_code == 422


@pytest.mark.parametrize("ue_id", [0, -5, 99999])
def test_out_of_range_ue_path_param_is_not_validated_and_maps_to_400(client, ue_id: int) -> None:
    # Path parameters are plain ``int`` (no Field range), so out-of-range ids are
    # NOT rejected with 422 the way request bodies are; they reach the repo and
    # come back as a domain 400 ("UE not found").
    response = client.get(f"/ues/{ue_id}")

    assert response.status_code == 400
    assert response.json()["detail"] == "UE not found"


@pytest.mark.parametrize("bearer_path", ["/ues/1/bearers/abc/traffic", "/ues/1/bearers/x"])
def test_non_integer_bearer_path_param_returns_422(client, bearer_path: str) -> None:
    client.post("/ues", json={"ue_id": 1})

    # GET for stats path, DELETE for the plain bearer path.
    response = client.get(bearer_path) if bearer_path.endswith("traffic") else client.delete(bearer_path)

    assert response.status_code == 422


def test_malformed_json_body_returns_422(client) -> None:
    response = client.post(
        "/ues",
        content="{not valid json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


def test_attach_ue_with_missing_body_field_returns_422(client) -> None:
    assert client.post("/ues", json={}).status_code == 422


def test_zero_throughput_is_rejected_by_traffic_manager_with_400(client) -> None:
    # The model accepts bps=0, but the traffic manager treats a falsy target_bps
    # as "not configured" -> 400 at the API boundary.
    client.post("/ues", json={"ue_id": 1})

    response = client.post("/ues/1/bearers/9/traffic", json={"protocol": "tcp", "bps": 0})

    assert response.status_code == 400
    assert response.json()["detail"] == "Bearer not configured for traffic"


def test_negative_throughput_is_accepted_at_http_layer(client, fake_traffic_manager) -> None:
    # A negative target_bps is truthy, so it passes the manager's guard and the
    # request succeeds (documents the lack of a lower-bound check).
    client.post("/ues", json={"ue_id": 1})

    response = client.post("/ues/1/bearers/9/traffic", json={"protocol": "udp", "bps": -1000})

    assert response.status_code == 200
    assert response.json()["target_bps"] == -1000
    assert (1, 9, -1000, "udp") in fake_traffic_manager.started


def test_starting_traffic_twice_on_same_bearer_returns_400(client) -> None:
    client.post("/ues", json={"ue_id": 1})

    first = client.post("/ues/1/bearers/9/traffic", json={"protocol": "tcp", "Mbps": 1})
    assert first.status_code == 200

    second = client.post("/ues/1/bearers/9/traffic", json={"protocol": "tcp", "Mbps": 1})
    assert second.status_code == 400
    assert second.json()["detail"] == "Traffic already running"


def test_aggregated_stats_across_multiple_ues_with_details(client, repo) -> None:
    from epc.models import ThroughputStats

    for ue_id in (1, 2):
        client.post("/ues", json={"ue_id": ue_id})
        repo.update_stats(
            ue_id,
            ThroughputStats(
                ue_id=ue_id,
                bearer_id=9,
                bytes_tx=1250,
                bytes_rx=2500,
                start_ts=100.0,
                last_update_ts=110.0,
                protocol="tcp",
                target_bps=1000,
            ),
        )

    response = client.get("/ues/stats?include_details=true")

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "all"
    assert body["ue_count"] == 2
    assert body["bearer_count"] == 2
    # each bearer: 1250 * 8 / 10 = 1000 tx -> total 2000
    assert body["total_tx_bps"] == 2000
    assert body["total_rx_bps"] == 4000
    assert body["details"] == {"1": {"9": 1000}, "2": {"9": 1000}}


def test_detaching_ue_removes_it_from_aggregated_stats(client) -> None:
    client.post("/ues", json={"ue_id": 3})
    client.delete("/ues/3")

    response = client.get("/ues/stats")

    assert response.status_code == 200
    assert response.json()["ue_count"] == 0


def test_reset_on_empty_state_is_idempotent(client) -> None:
    assert client.post("/reset").status_code == 200
    assert client.post("/reset").status_code == 200
    assert client.get("/ues").json() == {"ues": []}
