import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _payload():
    return {
        "symbol": "BTCUSDT",
        "timeframe_set": "1m, 5m, 15m, 1h, 4h, 1d",
        "price": 64000,
        "ema20": 63800,
        "ema50": 63500,
        "ema200": 62000,
        "rsi": 58,
        "macd_hist": 12.3,
        "bb_width": 0.04,
        "atr_pct": 0.013,
        "vol_zscore": 1.4,
        "pattern_hints": ["ascending_triangle", "Ascending_Triangle"],
        "funding_rate": 0.0004,
        "oi_change_pct": 3.0,
        "squeeze_up_prob": 0.62,
        "squeeze_down_prob": 0.38,
        "macro_corr_ndx": 0.44,
        "macro_corr_spx": 0.51,
        "session": "newyork",
        "event_severity": 0,
        "data_degraded": False,
    }


def test_analysis_history_alerts_and_simulation_flow():
    analysis = client.post("/v1/analysis/run", json=_payload())
    assert analysis.status_code == 200

    snapshot = client.post("/v1/ingestion/snapshot?symbol=BTCUSDT&run_analysis=true")
    assert snapshot.status_code == 200

    precheck = client.post(
        "/v1/execution/precheck",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "qty": 0.01,
            "spread_bps": 8,
            "expected_slippage_bps": 9,
            "volatility_spike": False,
            "thin_liquidity": False,
            "event_risk": "low",
            "data_degraded": False,
        },
    )
    assert precheck.status_code == 200

    order = client.post(
        "/v1/execution/order",
        json={"symbol": "BTCUSDT", "side": "buy", "qty": 0.01, "order_type": "market"},
    )
    assert order.status_code == 200

    reconcile = client.get("/v1/execution/reconcile?symbol=BTCUSDT")
    assert reconcile.status_code == 200

    snapshots = client.get("/v1/raw_snapshots")
    assert snapshots.status_code == 200
    if snapshots.json():
        raw = snapshots.json()[0]
        assert "market" in raw["payload"]
        assert "macro" in raw["payload"]
        assert "derivatives" in raw["payload"]
        assert "event" in raw["payload"]

    cases = client.get("/v1/cases")
    assert cases.status_code == 200
    case_id = cases.json()[0]["id"]

    replay = client.get(f"/v1/cases/{case_id}")
    assert replay.status_code == 200

    features = client.get(f"/v1/cases/{case_id}/features")
    assert features.status_code == 200

    sim = client.post(f"/v1/cases/{case_id}/simulate?horizon=1h&chosen_scenario=primary")
    assert sim.status_code == 200

    sim2 = client.post(
        f"/v1/cases/{case_id}/simulate_realistic",
        json={"horizon":"1h","chosen_scenario":"primary","spread_bps":7,"expected_slippage_bps":9,"fee_bps":4},
    )
    assert sim2.status_code == 200

    kill = client.post("/v1/risk/kill_switch/check", json={"daily_loss_pct":-3.5,"consecutive_losses":5,"api_error_rate":0.2,"event_severity":3})
    assert kill.status_code == 200

    risk_events = client.get("/v1/risk/events")
    assert risk_events.status_code == 200

    gate = client.get("/v1/gates/status")
    assert gate.status_code == 200

    metrics = client.get("/v1/metrics")
    assert metrics.status_code == 200

    health_deep = client.get("/v1/health/deep")
    assert health_deep.status_code == 200

    timeline = client.get("/v1/timeline/events")
    assert timeline.status_code == 200
