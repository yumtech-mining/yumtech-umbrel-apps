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
        invalid_settings = client.put("/api/settings/test", headers={"X-CSRF-Token": csrf}, json={
            "active": True, "max_trade_try": "100", "daily_loss_limit_try": "50",
            "max_recovery_loss_try": "101"})
        assert invalid_settings.status_code == 422
        test_settings = client.put("/api/settings/test", headers={"X-CSRF-Token": csrf}, json={
            "active": True, "max_trade_try": "1000", "daily_loss_limit_try": "250",
            "max_recovery_loss_try": "100"})
        assert test_settings.status_code == 200 and test_settings.json()["active"] is True
        hb_control = client.post("/api/hummingbot/control", headers={"X-CSRF-Token": csrf},
                                 json={"action": "start_test"})
        assert hb_control.status_code == 200
        assert hb_control.json()["command"]["mode"] == "test"
        assert main.settings.hummingbot_control_path.exists()
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
        audit = client.get("/api/audit")
        assert audit.status_code == 200
        assert any(item["event"] == "hummingbot_control" for item in audit.json()["items"])
