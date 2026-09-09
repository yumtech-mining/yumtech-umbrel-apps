from fastapi.testclient import TestClient

from app import main


def test_owner_session_csrf_and_separate_user(tmp_path):
    main.settings.data_dir = tmp_path
    with TestClient(main.app) as client:
        assert client.get("/api/health").json()["live_orders_enabled"] is False
        created = client.post("/api/bootstrap", json={"username": "owner", "password": "a-strong-local-password"})
        assert created.status_code == 201
        csrf = created.json()["csrf_token"]
        me = client.get("/api/me")
        assert me.status_code == 200 and me.json()["is_admin"] is True
        denied = client.post("/api/users", json={"username": "brother", "password": "another-long-password"})
        assert denied.status_code == 403
        added = client.post("/api/users", headers={"X-CSRF-Token": csrf},
                            json={"username": "brother", "password": "another-long-password"})
        assert added.status_code == 201
        live = client.post("/api/live/enable", headers={"X-CSRF-Token": csrf})
        assert live.status_code == 423
