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
        main.scanner.opportunities = [{
            "pair": "BTC/TRY", "buy_exchange": "BTCTürk", "sell_exchange": "Binance TR",
            "base_amount": "0.001", "buy_vwap": "1000000", "sell_vwap": "1010000",
            "gross_profit_try": "10", "fees_try": "3.015", "safety_buffer_try": "1",
            "net_profit_try": "5.985", "net_profit_pct": "0.005985", "executable": True,
        }]
        paper = client.post("/api/paper/execute", headers={"X-CSRF-Token": csrf}, json={
            "pair": "BTC/TRY", "buy_exchange": "BTCTürk", "sell_exchange": "Binance TR"})
        assert paper.status_code == 201
        assert paper.json()["state"] == "BALANCED_FILL"
        history = client.get("/api/executions")
        assert history.status_code == 200
        assert history.json()["items"][0]["id"] == paper.json()["intent_id"]
