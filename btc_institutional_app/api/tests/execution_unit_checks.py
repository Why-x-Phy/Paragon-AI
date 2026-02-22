from app.services.execution import PionexClient, reconciliation_loop, reconcile_state, verify_exchange_connectivity


class _DummyClient:
    def __init__(self):
        self.calls = 0

    def get_open_orders(self, symbol: str):
        self.calls += 1
        return [{"orderId": "o1"}]

    def get_fills(self, symbol: str):
        return [{"orderId": "f1"}]

    def get_positions(self):
        return []


class _NoOrderClient:
    def get_open_orders(self, symbol: str):
        return []

    def get_fills(self, symbol: str):
        return [{"orderId": "x1"}]

    def get_positions(self):
        return []


def test_reconcile_detects_id_gap():
    result = reconcile_state(_DummyClient(), symbol="BTCUSDT")
    assert "FILL_OPEN_ORDER_ID_GAP" in result.mismatches


def test_reconcile_detects_fills_without_positions():
    result = reconcile_state(_NoOrderClient(), symbol="BTCUSDT")
    assert "FILLS_WITHOUT_OPEN_ORDERS_OR_POSITIONS" in result.mismatches


def test_reconciliation_loop_runs_multiple_cycles():
    client = _DummyClient()
    _ = reconciliation_loop(client, symbol="BTCUSDT", cycles=3, pause_s=0.0)
    assert client.calls == 3


def test_pionex_signing_is_deterministic(monkeypatch):
    monkeypatch.setenv("PIONEX_API_KEY", "k")
    monkeypatch.setenv("PIONEX_API_SECRET", "secret")
    c = PionexClient()
    sig = c._sign("symbol=BTCUSDT&timestamp=1")
    assert sig == "ef9d3d77a34d9a13a21a4c2d7f3e8cb091888a74ca62b5b62f430e78eded95ba"


def test_verify_exchange_connectivity_stub():
    client = _DummyClient()
    client.get_orderbook = lambda _symbol: {"best_bid": 1}
    client.get_balance = lambda: {"ok": True}
    out = verify_exchange_connectivity(client, symbol="BTCUSDT")
    assert out.reachable is True
    assert "ORDERBOOK_OK" in out.checks
