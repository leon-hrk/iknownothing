import pytest
from fastapi.testclient import TestClient

from iknownothing import accounts, api
from iknownothing.config import Settings


def test_accounts(tmp_path):
    accounts.add(tmp_path, "alice")
    accounts.add(tmp_path, "bob")
    (tmp_path / "bob" / "control").mkdir()
    assert accounts.names(tmp_path) == ["alice", "bob"]
    with pytest.raises(accounts.AccountError, match="exists"):
        accounts.add(tmp_path, "alice")
    with pytest.raises(accounts.AccountError, match="invalid"):
        accounts.add(tmp_path, "../x")
    accounts.remove(tmp_path, "bob")
    assert accounts.names(tmp_path) == ["alice"]
    with pytest.raises(accounts.AccountError, match="no such"):
        accounts.remove(tmp_path, "bob")


def test_choose_user(tmp_path, monkeypatch):
    (tmp_path / "alice" / "control").mkdir(parents=True)
    accounts.add(tmp_path, "bob")
    monkeypatch.setattr(api, "settings", Settings(tmp_path, "m", "m"))
    client = TestClient(api.app)
    assert client.get("/api/users").json() == ["alice", "bob"]
    assert client.get("/api/courses").status_code == 401
    assert client.post("/api/user", json={"name": "carol"}).status_code == 404
    assert client.post("/api/user", json={"name": "alice"}).status_code == 204
    assert client.get("/api/user").json() == {"name": "alice"}
    assert client.get("/api/courses").json() == [{"name": "control", "status": "not ingested"}]

    client.cookies.set(api.COOKIE, "..")
    assert client.get("/api/courses").status_code == 401
