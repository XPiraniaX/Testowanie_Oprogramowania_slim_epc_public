import pytest
from fastapi.testclient import TestClient

from main import app
from epc.db import EPCRepository
from epc.api import get_repo


@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_epc.db"
    repo = EPCRepository(str(test_db))

    app.dependency_overrides[get_repo] = lambda: repo

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def test_root_endpoint(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "EPC Simulator running"}


def test_attach_ue(client):
    response = client.post("/ues", json={"ue_id": 1})

    assert response.status_code == 200
    assert response.json()["status"] == "attached"
    assert response.json()["ue_id"] == 1


def test_list_ues_after_attach(client):
    client.post("/ues", json={"ue_id": 1})

    response = client.get("/ues")

    assert response.status_code == 200
    assert 1 in response.json()["ues"]


def test_attach_duplicate_ue_returns_400(client):
    client.post("/ues", json={"ue_id": 1})

    response = client.post("/ues", json={"ue_id": 1})

    assert response.status_code == 400


def test_invalid_ue_id_returns_422(client):
    response = client.post("/ues", json={"ue_id": 101})

    assert response.status_code == 422


def test_attach_creates_default_bearer_9(client):
    client.post("/ues", json={"ue_id": 1})

    response = client.get("/ues/1")

    assert response.status_code == 200
    data = response.json()
    assert "9" in data["bearers"] or 9 in data["bearers"]


def test_add_bearer(client):
    client.post("/ues", json={"ue_id": 1})

    response = client.post("/ues/1/bearers", json={"bearer_id": 1})

    assert response.status_code == 200


def test_delete_default_bearer_returns_400(client):
    client.post("/ues", json={"ue_id": 1})

    response = client.delete("/ues/1/bearers/9")

    assert response.status_code == 400


def test_start_traffic_with_mbps(client):
    client.post("/ues", json={"ue_id": 1})
    client.post("/ues/1/bearers", json={"bearer_id": 1})

    response = client.post(
        "/ues/1/bearers/1/traffic",
        json={"protocol": "tcp", "Mbps": 1}
    )

    assert response.status_code == 200


def test_start_traffic_invalid_protocol_returns_422(client):
    client.post("/ues", json={"ue_id": 1})
    client.post("/ues/1/bearers", json={"bearer_id": 1})

    response = client.post(
        "/ues/1/bearers/1/traffic",
        json={"protocol": "icmp", "Mbps": 1}
    )

    assert response.status_code == 422


def test_start_traffic_requires_exactly_one_speed_unit(client):
    client.post("/ues", json={"ue_id": 1})
    client.post("/ues/1/bearers", json={"bearer_id": 1})

    response = client.post(
        "/ues/1/bearers/1/traffic",
        json={"protocol": "tcp", "Mbps": 1, "kbps": 1000}
    )

    assert response.status_code == 422


def test_reset_clears_ues(client):
    client.post("/ues", json={"ue_id": 1})

    reset_response = client.post("/reset")
    list_response = client.get("/ues")

    assert reset_response.status_code == 200
    assert list_response.status_code == 200
    assert list_response.json()["ues"] == []