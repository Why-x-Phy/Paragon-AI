from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Protocol
from urllib import parse, request

from app.services.settings import SETTINGS, read_secret_value


class ExchangeClient(Protocol):
    def get_balance(self) -> dict: ...
    def get_positions(self) -> list[dict]: ...
    def get_orderbook(self, symbol: str) -> dict: ...
    def create_order(self, symbol: str, side: str, qty: float, order_type: str = "market") -> dict: ...
    def cancel_order(self, order_id: str) -> dict: ...
    def get_open_orders(self, symbol: str) -> list[dict]: ...
    def get_fills(self, symbol: str) -> list[dict]: ...


class PionexClientStub:
    def get_balance(self) -> dict:
        return {"currency": "USDT", "available": 0.0, "mode": "stub"}

    def get_positions(self) -> list[dict]:
        return []

    def get_orderbook(self, symbol: str) -> dict:
        return {"symbol": symbol, "best_bid": None, "best_ask": None, "mode": "stub"}

    def create_order(self, symbol: str, side: str, qty: float, order_type: str = "market") -> dict:
        return {
            "accepted": False,
            "reason": "EXECUTION_DISABLED",
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "order_type": order_type,
            "mode": "stub",
        }

    def cancel_order(self, order_id: str) -> dict:
        return {"cancelled": False, "order_id": order_id, "mode": "stub"}

    def get_open_orders(self, symbol: str) -> list[dict]:
        return []

    def get_fills(self, symbol: str) -> list[dict]:
        return []


class PionexClient:
    def __init__(self) -> None:
        self.base_url = read_secret_value("PIONEX_BASE_URL", "https://api.pionex.com")
        self.api_key = read_secret_value("PIONEX_API_KEY", "")
        self.api_secret = read_secret_value("PIONEX_API_SECRET", "")
        self.recv_window = int(read_secret_value("PIONEX_RECV_WINDOW_MS", "5000"))

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _timestamp(self) -> int:
        return int(time.time() * 1000)

    def _sign(self, query: str) -> str:
        return hmac.new(self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, params: dict | None = None) -> dict:
        if not self.configured:
            return {"ok": False, "reason": "PIONEX_NOT_CONFIGURED"}

        params = params or {}
        params["timestamp"] = self._timestamp()
        params["recvWindow"] = self.recv_window
        query = parse.urlencode(params)
        signature = self._sign(query)
        url = f"{self.base_url}{path}?{query}&signature={signature}"

        req = request.Request(url=url, method=method)
        req.add_header("X-PIONEX-KEY", self.api_key)
        req.add_header("Content-Type", "application/json")

        try:
            with request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": "PIONEX_REQUEST_FAILED", "error": str(exc)}

    def get_balance(self) -> dict:
        return self._request("GET", "/api/v1/account/balances")

    def get_positions(self) -> list[dict]:
        data = self._request("GET", "/api/v1/futures/positions")
        return data.get("data", []) if isinstance(data, dict) else []

    def get_orderbook(self, symbol: str) -> dict:
        return self._request("GET", "/api/v1/market/depth", {"symbol": symbol})

    def create_order(self, symbol: str, side: str, qty: float, order_type: str = "market") -> dict:
        return self._request(
            "POST",
            "/api/v1/trade/order",
            {"symbol": symbol, "side": side.upper(), "size": qty, "type": order_type.upper()},
        )

    def cancel_order(self, order_id: str) -> dict:
        return self._request("POST", "/api/v1/trade/cancel", {"orderId": order_id})

    def get_open_orders(self, symbol: str) -> list[dict]:
        data = self._request("GET", "/api/v1/trade/openOrders", {"symbol": symbol})
        return data.get("data", []) if isinstance(data, dict) else []

    def get_fills(self, symbol: str) -> list[dict]:
        data = self._request("GET", "/api/v1/trade/fills", {"symbol": symbol})
        return data.get("data", []) if isinstance(data, dict) else []


@dataclass
class ExecutionVerificationResult:
    exchange: str
    configured: bool
    reachable: bool
    checks: list[str]
    mismatches: list[str]


def verify_exchange_connectivity(client: ExchangeClient, symbol: str = "BTCUSDT") -> ExecutionVerificationResult:
    checks: list[str] = []
    try:
        book = client.get_orderbook(symbol)
        checks.append("ORDERBOOK_OK" if isinstance(book, dict) else "ORDERBOOK_UNEXPECTED")
        _ = client.get_balance()
        checks.append("BALANCE_OK")
    except Exception:
        checks.append("CONNECTIVITY_FAILED")
        return ExecutionVerificationResult(exchange="pionex", configured=False, reachable=False, checks=checks, mismatches=["CONNECTIVITY_FAILED"])

    recon = reconcile_state(client, symbol=symbol)
    reachable = "CONNECTIVITY_FAILED" not in checks
    return ExecutionVerificationResult(
        exchange=recon.exchange,
        configured=not isinstance(client, PionexClientStub),
        reachable=reachable,
        checks=checks,
        mismatches=recon.mismatches,
    )


@dataclass
class ExecutionCheckResult:
    allowed: bool
    reason_codes: list[str]


@dataclass
class ReconciliationResult:
    exchange: str
    open_orders_count: int
    fills_count: int
    position_count: int
    mismatches: list[str]


def _order_id_from_row(row: dict) -> str:
    for key in ("orderId", "order_id", "id"):
        value = row.get(key)
        if value not in {None, ""}:
            return str(value)
    return ""


def pre_trade_check(
    spread_bps: float,
    expected_slippage_bps: float,
    volatility_spike: bool,
    thin_liquidity: bool,
    event_risk: str,
    data_degraded: bool,
) -> ExecutionCheckResult:
    reasons: list[str] = []

    if spread_bps > 12:
        reasons.append("SPREAD_TOO_WIDE")
    if expected_slippage_bps > 20:
        reasons.append("SLIPPAGE_TOO_HIGH")
    if volatility_spike and thin_liquidity:
        reasons.append("VOL_THIN_LIQUIDITY_BLOCK")
    if event_risk in {"high", "medium"}:
        reasons.append("EVENT_RISK_BLOCK")
    if data_degraded:
        reasons.append("DATA_DEGRADED_BLOCK")

    if not SETTINGS.execution_enabled:
        reasons.append("EXECUTION_DISABLED")

    return ExecutionCheckResult(allowed=len(reasons) == 0, reason_codes=reasons)


def build_exchange_client() -> ExchangeClient:
    pionex = PionexClient()
    if SETTINGS.execution_enabled and pionex.configured:
        return pionex
    return PionexClientStub()


def reconcile_state(client: ExchangeClient, symbol: str) -> ReconciliationResult:
    open_orders = client.get_open_orders(symbol)
    fills = client.get_fills(symbol)
    positions = client.get_positions()

    mismatches: list[str] = []
    if len(open_orders) > 20:
        mismatches.append("OPEN_ORDERS_LIMIT_WARNING")
    if len(positions) > 3:
        mismatches.append("POSITION_COUNT_WARNING")

    open_ids = {_order_id_from_row(x) for x in open_orders if isinstance(x, dict)}
    fill_ids = {_order_id_from_row(x) for x in fills if isinstance(x, dict)}
    open_ids.discard("")
    fill_ids.discard("")

    if fill_ids and open_ids and len(fill_ids.intersection(open_ids)) == 0:
        mismatches.append("FILL_OPEN_ORDER_ID_GAP")

    if len(fills) > 0 and len(open_orders) == 0 and len(positions) == 0:
        mismatches.append("FILLS_WITHOUT_OPEN_ORDERS_OR_POSITIONS")

    return ReconciliationResult(
        exchange=client.__class__.__name__,
        open_orders_count=len(open_orders),
        fills_count=len(fills),
        position_count=len(positions),
        mismatches=mismatches,
    )


def reconciliation_loop(client: ExchangeClient, symbol: str, cycles: int = 3, pause_s: float = 0.0) -> ReconciliationResult:
    final_result = reconcile_state(client, symbol)
    for _ in range(max(1, cycles) - 1):
        if pause_s > 0:
            time.sleep(pause_s)
        final_result = reconcile_state(client, symbol)
    return final_result
