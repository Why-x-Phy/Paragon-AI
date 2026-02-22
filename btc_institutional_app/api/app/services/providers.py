from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib import request
from urllib.error import HTTPError, URLError


@dataclass
class ProviderResult:
    source: str
    payload: dict
    degraded: bool
    notes: list[str]


def _read_json(url: str, timeout: int = 10, headers: dict | None = None) -> dict:
    req_headers = {"User-Agent": "btc-institutional-app/0.1"}
    if headers:
        req_headers.update(headers)
    req = request.Request(url, headers=req_headers)
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _read_json_retry(url: str, timeout: int = 10, headers: dict | None = None, attempts: int = 3) -> dict:
    last_error: Exception | None = None
    for idx in range(max(1, attempts)):
        try:
            return _read_json(url, timeout=timeout, headers=headers)
        except HTTPError as exc:
            last_error = exc
            if exc.code in {429, 500, 502, 503, 504} and idx < attempts - 1:
                time.sleep(0.25 * (idx + 1))
                continue
            raise
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if idx < attempts - 1:
                time.sleep(0.25 * (idx + 1))
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("retry loop exhausted")


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_epoch(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        ts = int(value)
        return ts // 1000 if ts > 10_000_000_000 else ts
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return 0
        if raw.isdigit():
            return _parse_epoch(int(raw))
        iso = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            return 0
    return 0


def _impact_to_severity(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        v = int(value)
        if v <= 0:
            return 0
        return min(3, v)
    text = str(value).strip().lower()
    if "high" in text or text == "3":
        return 3
    if "medium" in text or "med" in text or text == "2":
        return 2
    if "low" in text or text == "1":
        return 1
    return 0


def fetch_binance_snapshot(symbol: str = "BTCUSDT") -> ProviderResult:
    ticker = _read_json(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}")
    depth = _read_json(f"https://api.binance.com/api/v3/depth?symbol={symbol}&limit=20")

    bid_liq = sum(float(px) * float(sz) for px, sz in depth.get("bids", [])[:10])
    ask_liq = sum(float(px) * float(sz) for px, sz in depth.get("asks", [])[:10])

    payload = {
        "symbol": symbol,
        "price": float(ticker.get("lastPrice", 0.0)),
        "open": float(ticker.get("openPrice", 0.0)),
        "high": float(ticker.get("highPrice", 0.0)),
        "low": float(ticker.get("lowPrice", 0.0)),
        "volume": float(ticker.get("volume", 0.0)),
        "quote_volume": float(ticker.get("quoteVolume", 0.0)),
        "bid_liquidity_10": bid_liq,
        "ask_liquidity_10": ask_liq,
        "timestamp_ms": int(time.time() * 1000),
    }
    return ProviderResult(source="binance", payload=payload, degraded=False, notes=[])


def fetch_coinbase_snapshot() -> ProviderResult:
    data = _read_json("https://api.exchange.coinbase.com/products/BTC-USD/ticker")
    payload = {
        "symbol": "BTCUSD",
        "price": float(data.get("price", 0.0)),
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "volume": float(data.get("volume", 0.0)),
        "quote_volume": 0.0,
        "bid_liquidity_10": 0.0,
        "ask_liquidity_10": 0.0,
        "timestamp_ms": int(time.time() * 1000),
    }
    notes = ["depth_unavailable_on_fallback", "ohlc_unavailable_on_fallback"]
    return ProviderResult(source="coinbase_fallback", payload=payload, degraded=True, notes=notes)


def _daily_closes(symbol: str, days: int = 30) -> list[float]:
    data = _read_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={days}d&interval=1d")
    closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    return [float(c) for c in closes if c is not None]


def _corr(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 5:
        return 0.0
    x, y = a[-n:], b[-n:]
    mx, my = statistics.mean(x), statistics.mean(y)
    sx = sum((v - mx) ** 2 for v in x) ** 0.5
    sy = sum((v - my) ** 2 for v in y) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    return max(-1.0, min(1.0, cov / (sx * sy)))


def fetch_macro_context() -> ProviderResult:
    try:
        btc = _daily_closes("BTC-USD")
        spx = _daily_closes("^GSPC")
        ndx = _daily_closes("^NDX")
        payload = {
            "macro_corr_spx": round(_corr(btc, spx), 3),
            "macro_corr_ndx": round(_corr(btc, ndx), 3),
            "source_ts": int(time.time()),
        }
        return ProviderResult(source="yahoo_macro", payload=payload, degraded=False, notes=[])
    except Exception:
        return ProviderResult(
            source="macro_fallback",
            payload={"macro_corr_spx": 0.0, "macro_corr_ndx": 0.0, "source_ts": int(time.time())},
            degraded=True,
            notes=["macro_provider_failed"],
        )


def _extract_coinglass_rows(response: dict) -> list[dict]:
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("list", "history", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _latest_value(rows: list[dict], keys: tuple[str, ...]) -> float:
    if not rows:
        return 0.0
    row = rows[-1]
    for key in keys:
        if key in row:
            return _to_float(row.get(key), 0.0)
    return 0.0


def _change_pct(rows: list[dict], keys: tuple[str, ...]) -> float:
    if len(rows) < 2:
        return 0.0
    prev = _latest_value(rows[:-1], keys)
    now = _latest_value(rows, keys)
    if prev == 0:
        return 0.0
    return ((now - prev) / abs(prev)) * 100.0




def _liquidations_24h(rows: list[dict]) -> tuple[float, float]:
    long_total = 0.0
    short_total = 0.0
    for row in rows:
        long_total += _to_float(row.get("longLiquidationUsd"), 0.0)
        long_total += _to_float(row.get("long_liquidation_usd"), 0.0)
        short_total += _to_float(row.get("shortLiquidationUsd"), 0.0)
        short_total += _to_float(row.get("short_liquidation_usd"), 0.0)

        # Fallback generic keys used by some endpoints.
        buy_liq = _to_float(row.get("buy"), 0.0)
        sell_liq = _to_float(row.get("sell"), 0.0)
        short_total += max(buy_liq, 0.0)
        long_total += max(sell_liq, 0.0)
    return long_total, short_total

def fetch_derivatives_context() -> ProviderResult:
    api_key = os.getenv("COINGLASS_API_KEY", "")
    if not api_key:
        return ProviderResult(
            source="derivatives_fallback",
            payload={"funding_rate": 0.0, "oi_change_pct": 0.0, "squeeze_up_prob": 0.5, "squeeze_down_prob": 0.5, "long_liq_usd_24h": 0.0, "short_liq_usd_24h": 0.0},
            degraded=True,
            notes=["coinglass_api_key_missing"],
        )

    try:
        funding_resp = _read_json_retry(
            "https://open-api-v3.coinglass.com/api/futures/fundingRate/history?symbol=BTC&exchange=Binance&interval=1h&limit=5",
            headers={"CG-API-KEY": api_key},
            attempts=3,
        )
        oi_resp = _read_json_retry(
            "https://open-api-v3.coinglass.com/api/futures/openInterest/history?symbol=BTC&exchange=Binance&interval=1h&limit=5",
            headers={"CG-API-KEY": api_key},
            attempts=3,
        )
        liq_resp = _read_json_retry(
            "https://open-api-v3.coinglass.com/api/futures/liquidation/history?symbol=BTC&interval=1h&limit=24",
            headers={"CG-API-KEY": api_key},
            attempts=3,
        )
        funding_rows = _extract_coinglass_rows(funding_resp)
        oi_rows = _extract_coinglass_rows(oi_resp)
        liq_rows = _extract_coinglass_rows(liq_resp)

        funding_rate = _latest_value(funding_rows, ("fundingRate", "funding_rate", "value"))
        oi_change_pct = _change_pct(oi_rows, ("openInterest", "open_interest", "value"))

        long_liq_usd_24h, short_liq_usd_24h = _liquidations_24h(liq_rows)

        squeeze_up_prob = max(0.0, min(1.0, 0.5 + (funding_rate * 30.0) + (oi_change_pct / 500.0) + ((short_liq_usd_24h - long_liq_usd_24h) / max(long_liq_usd_24h + short_liq_usd_24h, 1.0)) * 0.08))
        squeeze_down_prob = max(0.0, min(1.0, 1.0 - squeeze_up_prob))

        notes: list[str] = []
        if not funding_rows:
            notes.append("coinglass_funding_empty")
        if not oi_rows:
            notes.append("coinglass_oi_empty")
        if not liq_rows:
            notes.append("coinglass_liquidations_empty")

        return ProviderResult(
            source="coinglass",
            payload={
                "funding_rate": round(funding_rate, 6),
                "oi_change_pct": round(oi_change_pct, 3),
                "squeeze_up_prob": round(squeeze_up_prob, 3),
                "squeeze_down_prob": round(squeeze_down_prob, 3),
                "long_liq_usd_24h": round(long_liq_usd_24h, 2),
                "short_liq_usd_24h": round(short_liq_usd_24h, 2),
            },
            degraded=bool(notes),
            notes=notes,
        )
    except HTTPError as exc:
        note = "coinglass_provider_failed"
        if exc.code == 429:
            note = "coinglass_rate_limited"
        return ProviderResult(
            source="derivatives_fallback",
            payload={"funding_rate": 0.0, "oi_change_pct": 0.0, "squeeze_up_prob": 0.5, "squeeze_down_prob": 0.5, "long_liq_usd_24h": 0.0, "short_liq_usd_24h": 0.0},
            degraded=True,
            notes=[note],
        )
    except Exception:
        return ProviderResult(
            source="derivatives_fallback",
            payload={"funding_rate": 0.0, "oi_change_pct": 0.0, "squeeze_up_prob": 0.5, "squeeze_down_prob": 0.5, "long_liq_usd_24h": 0.0, "short_liq_usd_24h": 0.0},
            degraded=True,
            notes=["coinglass_provider_failed"],
        )


def _extract_calendar_events(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("events"), list):
            return [x for x in payload["events"] if isinstance(x, dict)]
        if isinstance(payload.get("data"), list):
            return [x for x in payload["data"] if isinstance(x, dict)]
        if isinstance(payload.get("calendar"), list):
            return [x for x in payload["calendar"] if isinstance(x, dict)]
    return []


def _calendar_event_ts(event: dict) -> int:
    for key in ("timestamp", "time", "date", "datetime", "eventTime", "event_time"):
        ts = _parse_epoch(event.get(key))
        if ts > 0:
            return ts
    return 0


def _calendar_event_severity(event: dict) -> int:
    for key in ("severity", "impact", "importance", "priority"):
        sev = _impact_to_severity(event.get(key))
        if sev > 0:
            return sev
    return 0



def _calendar_keywords() -> list[str]:
    raw = os.getenv("EVENT_CALENDAR_KEYWORDS", "CPI,FOMC,NFP,Non-Farm Payroll,Interest Rate")
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def _calendar_currency() -> str:
    return os.getenv("EVENT_CALENDAR_CURRENCY", "USD").strip().upper()


def _calendar_event_name(event: dict) -> str:
    for key in ("name", "event", "title", "indicator"):
        value = event.get(key)
        if value:
            return str(value)
    return ""


def _calendar_event_currency(event: dict) -> str:
    for key in ("currency", "ccy", "countryCurrency"):
        value = event.get(key)
        if value:
            return str(value).upper()
    return ""


def _calendar_event_relevant(event: dict, target_currency: str, keywords: list[str]) -> bool:
    ccy = _calendar_event_currency(event)
    name = _calendar_event_name(event).lower()

    currency_ok = not ccy or ccy == target_currency
    keyword_ok = True if not keywords else any(k in name for k in keywords)
    return currency_ok and keyword_ok


def _calendar_event_severity_adjusted(event: dict) -> int:
    sev = _calendar_event_severity(event)
    name = _calendar_event_name(event).lower()
    if any(tag in name for tag in ("cpi", "fomc", "interest rate", "non-farm payroll", "nfp")):
        sev = min(3, max(sev, 2))
    return sev

def _calendar_sources() -> list[str]:
    raw = os.getenv("EVENT_CALENDAR_URL", "").strip()
    if not raw:
        return []
    return [u.strip() for u in raw.split(",") if u.strip()]


def fetch_event_risk_context() -> ProviderResult:
    urls = _calendar_sources()
    if not urls:
        return ProviderResult(
            source="event_calendar_unconfigured",
            payload={"event_severity": 0, "calendar_coverage_score": 0.0, "calendar_sources_ok": 0, "calendar_sources_tried": 0},
            degraded=True,
            notes=["event_calendar_url_missing"],
        )

    now_ts = int(time.time())
    horizon_ts = now_ts + (24 * 60 * 60)
    target_currency = _calendar_currency()
    keywords = _calendar_keywords()

    errors: list[str] = []
    source_results: list[tuple[int, int, int]] = []
    max_severity = 0
    total_matched = 0
    total_relevant = 0

    for url in urls:
        try:
            data = _read_json_retry(url, attempts=3)
            events = _extract_calendar_events(data)
            matched = 0
            relevant = 0
            local_max = 0
            for event in events:
                ts = _calendar_event_ts(event)
                if ts <= 0 or ts < now_ts or ts > horizon_ts:
                    continue
                matched += 1
                if not _calendar_event_relevant(event, target_currency, keywords):
                    continue
                relevant += 1
                local_max = max(local_max, _calendar_event_severity_adjusted(event))

            source_results.append((matched, relevant, local_max))
            total_matched += matched
            total_relevant += relevant
            max_severity = max(max_severity, local_max)
        except HTTPError as exc:
            if exc.code == 429:
                errors.append("event_calendar_rate_limited")
            else:
                errors.append("event_calendar_http_error")
        except Exception:
            errors.append("event_calendar_provider_failed")

    successful_sources = len(source_results)
    coverage_score = 0.0 if total_matched == 0 else min(1.0, total_relevant / max(total_matched, 1))

    notes: list[str] = []
    if total_matched == 0:
        notes.append("event_calendar_no_events_in_window")
    elif total_relevant == 0:
        notes.append("event_calendar_no_relevant_events")
    if successful_sources < len(urls):
        notes.extend(errors)

    payload = {
        "event_severity": max_severity,
        "calendar_coverage_score": round(coverage_score, 3),
        "calendar_sources_ok": successful_sources,
        "calendar_sources_tried": len(urls),
    }

    degraded = successful_sources == 0 or coverage_score < 0.25
    if degraded and not errors and successful_sources == 0:
        errors.append("event_calendar_provider_failed")

    if successful_sources == 0:
        return ProviderResult(
            source="event_calendar_fallback",
            payload=payload,
            degraded=True,
            notes=errors or ["event_calendar_provider_failed"],
        )

    if degraded:
        notes.append("event_calendar_low_coverage")

    return ProviderResult(
        source="event_calendar",
        payload=payload,
        degraded=degraded,
        notes=notes,
    )



def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return var ** 0.5


def _close_series_from_klines(data: object) -> list[float]:
    if not isinstance(data, list):
        return []
    closes: list[float] = []
    for row in data:
        if isinstance(row, list) and len(row) >= 5:
            closes.append(_to_float(row[4], 0.0))
        elif isinstance(row, dict):
            closes.append(_to_float(row.get("close"), 0.0))
    return [c for c in closes if c > 0]


def fetch_mtf_candle_features(symbol: str = "BTCUSDT") -> ProviderResult:
    intervals = ["1m", "5m", "15m", "1h", "4h", "1d"]
    trend_votes = 0
    sampled = 0
    total_vol = 0.0
    notes: list[str] = []

    for tf in intervals:
        try:
            payload = _read_json_retry(
                f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={tf}&limit=80",
                attempts=2,
            )
            closes = _close_series_from_klines(payload)
            if len(closes) < 20:
                notes.append(f"mtf_{tf}_insufficient_bars")
                continue

            sampled += 1
            trend_votes += 1 if closes[-1] > closes[0] else 0
            returns = []
            for idx in range(1, len(closes)):
                prev = closes[idx - 1]
                if prev <= 0:
                    continue
                returns.append((closes[idx] - prev) / prev)
            total_vol += _stdev(returns)
        except Exception:
            notes.append(f"mtf_{tf}_fetch_failed")

    if sampled == 0:
        return ProviderResult(
            source="mtf_fallback",
            payload={"mtf_trend_score": 0.5, "mtf_volatility": 0.0, "mtf_timeframes": []},
            degraded=True,
            notes=notes or ["mtf_all_fetches_failed"],
        )

    trend_score = trend_votes / sampled
    mtf_volatility = total_vol / sampled
    alignment_ratio = sampled / len(intervals)
    trend_bias = "bull" if trend_score >= 0.55 else "bear" if trend_score <= 0.45 else "neutral"
    return ProviderResult(
        source="binance_mtf",
        payload={
            "mtf_trend_score": round(trend_score, 3),
            "mtf_volatility": round(mtf_volatility, 6),
            "mtf_alignment_ratio": round(alignment_ratio, 3),
            "mtf_trend_bias": trend_bias,
            "mtf_timeframes": intervals,
        },
        degraded=sampled < len(intervals),
        notes=notes,
    )


def _session_from_time(hour: int, weekday: int) -> str:
    # UTC weekday: Monday=0 ... Sunday=6
    if weekday >= 5:
        return "weekend"
    if 0 <= hour < 8:
        return "asia"
    if 8 <= hour < 13:
        return "london"
    return "newyork"


def fetch_microstructure_context(symbol: str = "BTCUSDT") -> ProviderResult:
    notes: list[str] = []
    try:
        depth = _read_json_retry(f"https://api.binance.com/api/v3/depth?symbol={symbol}&limit=50", attempts=2)
        klines = _read_json_retry(
            f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=180",
            attempts=2,
        )
        closes = _close_series_from_klines(klines)
        if len(closes) < 20:
            return ProviderResult(
                source="microstructure_fallback",
                payload={
                    "session": "london",
                    "anchored_vwap_dist_bps": 0.0,
                    "vp_balance": 0.0,
                    "absorption_score": 0.0,
                    "sweep_risk_score": 0.0,
                    "orderbook_imbalance": 0.0,
                    "depth_thinness": 1.0,
                    "vp_value_acceptance": 0.0,
                    "vwap_slope_bps": 0.0,
                },
                degraded=True,
                notes=["microstructure_insufficient_klines"],
            )

        bids = depth.get("bids", []) if isinstance(depth, dict) else []
        asks = depth.get("asks", []) if isinstance(depth, dict) else []

        bid_liq = sum(_to_float(px) * _to_float(sz) for px, sz in bids[:20])
        ask_liq = sum(_to_float(px) * _to_float(sz) for px, sz in asks[:20])
        liq_total = max(bid_liq + ask_liq, 1.0)
        vp_balance = (bid_liq - ask_liq) / liq_total

        low = min(closes)
        high = max(closes)
        price = closes[-1]
        if high <= low:
            high = low + 1e-6

        # Anchored VWAP proxy: volume-unaware center with session anchor simplification for baseline.
        anchored_vwap = sum(closes) / len(closes)
        anchored_vwap_dist_bps = ((price - anchored_vwap) / max(anchored_vwap, 1e-6)) * 10000

        top_bid = _to_float(bids[0][0], price) if bids else price
        top_ask = _to_float(asks[0][0], price) if asks else price
        spread_bps = ((top_ask - top_bid) / max(price, 1e-6)) * 10000

        absorption_score = max(0.0, min(1.0, (min(bid_liq, ask_liq) / max(max(bid_liq, ask_liq), 1.0))))
        sweep_risk_score = max(0.0, min(1.0, (spread_bps / 12.0) + (1.0 - absorption_score) * 0.5))
        orderbook_imbalance = (bid_liq - ask_liq) / liq_total
        depth_thinness = max(0.0, min(1.0, spread_bps / 25.0))
        vp_value_acceptance = max(0.0, min(1.0, 1.0 - abs(vp_balance)))
        vwap_slope_bps = ((closes[-1] - closes[-20]) / max(closes[-20], 1e-6)) * 10000

        now = time.gmtime()
        session = _session_from_time(int(now.tm_hour), int(now.tm_wday))

        if spread_bps > 10:
            notes.append("microstructure_wide_spread")
        if depth_thinness > 0.6:
            notes.append("microstructure_thin_depth")

        return ProviderResult(
            source="binance_microstructure",
            payload={
                "session": session,
                "anchored_vwap_dist_bps": round(anchored_vwap_dist_bps, 2),
                "vp_balance": round(vp_balance, 4),
                "absorption_score": round(absorption_score, 4),
                "sweep_risk_score": round(sweep_risk_score, 4),
                "orderbook_imbalance": round(orderbook_imbalance, 4),
                "depth_thinness": round(depth_thinness, 4),
                "vp_value_acceptance": round(vp_value_acceptance, 4),
                "vwap_slope_bps": round(vwap_slope_bps, 2),
            },
            degraded=False,
            notes=notes,
        )
    except Exception:
        return ProviderResult(
            source="microstructure_fallback",
            payload={
                "session": "london",
                "anchored_vwap_dist_bps": 0.0,
                "vp_balance": 0.0,
                "absorption_score": 0.0,
                "sweep_risk_score": 0.0,
                "orderbook_imbalance": 0.0,
                "depth_thinness": 1.0,
                "vp_value_acceptance": 0.0,
                "vwap_slope_bps": 0.0,
            },
            degraded=True,
            notes=["microstructure_provider_failed"],
        )

def fetch_market_snapshot(symbol: str = "BTCUSDT") -> ProviderResult:
    try:
        return fetch_binance_snapshot(symbol=symbol)
    except (URLError, HTTPError, TimeoutError, ValueError):
        fallback = fetch_coinbase_snapshot()
        fallback.notes.append("primary_provider_failed")
        return fallback
