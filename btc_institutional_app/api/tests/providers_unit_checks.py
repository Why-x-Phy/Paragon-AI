from urllib.error import HTTPError

from app.services import providers


def test_extract_coinglass_rows_from_list_payload():
    rows = providers._extract_coinglass_rows({"data": [{"value": 1}, {"value": 2}]})
    assert len(rows) == 2


def test_extract_coinglass_rows_from_nested_payload():
    rows = providers._extract_coinglass_rows({"data": {"list": [{"openInterest": "100"}, {"openInterest": "110"}]}})
    assert len(rows) == 2


def test_change_pct_computes_expected_value():
    rows = [{"openInterest": "100"}, {"openInterest": "120"}]
    change = providers._change_pct(rows, ("openInterest",))
    assert round(change, 2) == 20.0


def test_event_calendar_parsing_uses_next_24h_window(monkeypatch):
    now = 1_700_000_000

    class _Now:
        @staticmethod
        def time():
            return now

        @staticmethod
        def sleep(_seconds):
            return None

    monkeypatch.setattr(providers, "time", _Now)
    monkeypatch.setenv("EVENT_CALENDAR_URL", "https://calendar.local/events")
    monkeypatch.setenv("EVENT_CALENDAR_KEYWORDS", "")

    monkeypatch.setattr(
        providers,
        "_read_json_retry",
        lambda *_args, **_kwargs: {
            "events": [
                {"timestamp": now + 3600, "severity": 1},
                {"timestamp": now + 7200, "severity": 3},
                {"timestamp": now + 172800, "severity": 2},
            ]
        },
    )

    result = providers.fetch_event_risk_context()
    assert result.source == "event_calendar"
    assert result.payload["event_severity"] == 3
    assert result.payload["calendar_sources_ok"] == 1
    assert result.payload["calendar_sources_tried"] == 1
    assert result.payload["calendar_sources_ok"] == 1
    assert result.degraded is False


def test_event_calendar_unconfigured_degrades(monkeypatch):
    monkeypatch.delenv("EVENT_CALENDAR_URL", raising=False)
    result = providers.fetch_event_risk_context()

    assert result.degraded is True
    assert result.source == "event_calendar_unconfigured"
    assert "event_calendar_url_missing" in result.notes


def test_read_json_retry_retries_transient_http_errors(monkeypatch):
    calls = {"n": 0}

    def _fake_read_json(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise HTTPError(url="https://x", code=503, msg="svc", hdrs=None, fp=None)
        return {"ok": True}

    monkeypatch.setattr(providers, "_read_json", _fake_read_json)
    monkeypatch.setattr(providers.time, "sleep", lambda *_args, **_kwargs: None)

    result = providers._read_json_retry("https://x", attempts=3)
    assert result["ok"] is True
    assert calls["n"] == 3


def test_fetch_derivatives_context_rate_limit_note(monkeypatch):
    monkeypatch.setenv("COINGLASS_API_KEY", "x")

    def _always_429(*_args, **_kwargs):
        raise HTTPError(url="https://x", code=429, msg="rate", hdrs=None, fp=None)

    monkeypatch.setattr(providers, "_read_json_retry", _always_429)
    result = providers.fetch_derivatives_context()

    assert result.degraded is True
    assert "coinglass_rate_limited" in result.notes


def test_calendar_multiple_sources_fallback_to_second(monkeypatch):
    now = 1_700_000_000

    class _Now:
        @staticmethod
        def time():
            return now

        @staticmethod
        def sleep(_seconds):
            return None

    monkeypatch.setattr(providers, "time", _Now)
    monkeypatch.setenv("EVENT_CALENDAR_URL", "https://primary.local, https://secondary.local")
    monkeypatch.setenv("EVENT_CALENDAR_KEYWORDS", "")

    def _mock_retry(url, **_kwargs):
        if "primary" in url:
            raise HTTPError(url=url, code=503, msg="down", hdrs=None, fp=None)
        return [{"timestamp": now + 3600, "impact": "High"}]

    monkeypatch.setattr(providers, "_read_json_retry", _mock_retry)
    result = providers.fetch_event_risk_context()

    assert result.source == "event_calendar"
    assert result.payload["event_severity"] == 3
    assert result.payload["calendar_sources_ok"] == 1


def test_liquidations_aggregation_from_mixed_keys():
    rows = [
        {"longLiquidationUsd": 1000, "shortLiquidationUsd": 1400},
        {"long_liquidation_usd": 500, "short_liquidation_usd": 600},
        {"buy": 200, "sell": 300},
    ]
    long_total, short_total = providers._liquidations_24h(rows)
    assert long_total == 1800
    assert short_total == 2200


def test_fetch_derivatives_context_maps_liquidations(monkeypatch):
    monkeypatch.setenv("COINGLASS_API_KEY", "x")

    funding = {"data": [{"fundingRate": "0.001"}]}
    oi = {"data": [{"openInterest": "100"}, {"openInterest": "110"}]}
    liq = {"data": [{"longLiquidationUsd": 1000000, "shortLiquidationUsd": 2500000}]}

    def _mock_retry(url, **_kwargs):
        if "fundingRate" in url:
            return funding
        if "openInterest" in url:
            return oi
        return liq

    monkeypatch.setattr(providers, "_read_json_retry", _mock_retry)

    result = providers.fetch_derivatives_context()
    assert result.source == "coinglass"
    assert result.payload["long_liq_usd_24h"] == 1000000.0
    assert result.payload["short_liq_usd_24h"] == 2500000.0


def test_close_series_from_klines_supports_list_and_dict_shapes():
    rows = [[0,0,0,0,"100"],[0,0,0,0,"101"]]
    assert providers._close_series_from_klines(rows) == [100.0, 101.0]

    rows2 = [{"close": "99"}, {"close": 98}]
    assert providers._close_series_from_klines(rows2) == [99.0, 98.0]


def test_fetch_mtf_candle_features_success(monkeypatch):
    def _mock_retry(url, **_kwargs):
        base = 100
        if "interval=1m" in url:
            base = 100
        if "interval=1d" in url:
            base = 200
        return [[0,0,0,0,str(base + i)] for i in range(80)]

    monkeypatch.setattr(providers, "_read_json_retry", _mock_retry)
    result = providers.fetch_mtf_candle_features()

    assert result.source == "binance_mtf"
    assert result.degraded is False
    assert result.payload["mtf_trend_score"] == 1.0
    assert result.payload["mtf_alignment_ratio"] == 1.0
    assert len(result.payload["mtf_timeframes"]) == 6


def test_fetch_mtf_candle_features_partial_failure(monkeypatch):
    def _mock_retry(url, **_kwargs):
        if "interval=4h" in url:
            raise RuntimeError("boom")
        return [[0,0,0,0,str(100 + i)] for i in range(80)]

    monkeypatch.setattr(providers, "_read_json_retry", _mock_retry)
    result = providers.fetch_mtf_candle_features()

    assert result.source == "binance_mtf"
    assert result.degraded is True
    assert any("mtf_4h_fetch_failed" == n for n in result.notes)


def test_session_from_time_mapping_weekday_and_weekend():
    assert providers._session_from_time(2, 1) == "asia"
    assert providers._session_from_time(9, 1) == "london"
    assert providers._session_from_time(15, 1) == "newyork"
    assert providers._session_from_time(15, 6) == "weekend"


def test_fetch_microstructure_context_success(monkeypatch):
    depth = {
        "bids": [["100", "10"], ["99", "8"]],
        "asks": [["101", "9"], ["102", "7"]],
    }
    klines = [[0, 0, 0, 0, str(100 + i)] for i in range(180)]

    def _mock_retry(url, **_kwargs):
        if "depth" in url:
            return depth
        return klines

    monkeypatch.setattr(providers, "_read_json_retry", _mock_retry)
    monkeypatch.setattr(providers.time, "gmtime", lambda: type("T", (), {"tm_hour": 10, "tm_wday": 2})())
    result = providers.fetch_microstructure_context()

    assert result.source == "binance_microstructure"
    assert result.degraded is False
    assert result.payload["session"] == "london"
    assert "anchored_vwap_dist_bps" in result.payload
    assert "orderbook_imbalance" in result.payload
    assert "depth_thinness" in result.payload


def test_fetch_microstructure_context_fallback(monkeypatch):
    monkeypatch.setattr(providers, "_read_json_retry", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("x")))
    result = providers.fetch_microstructure_context()

    assert result.source == "microstructure_fallback"
    assert result.degraded is True


def test_calendar_relevance_filter_and_keyword_boost(monkeypatch):
    now = 1_700_000_000

    class _Now:
        @staticmethod
        def time():
            return now

        @staticmethod
        def sleep(_seconds):
            return None

    monkeypatch.setattr(providers, "time", _Now)
    monkeypatch.setenv("EVENT_CALENDAR_URL", "https://calendar.local/events")
    monkeypatch.setenv("EVENT_CALENDAR_CURRENCY", "USD")
    monkeypatch.setenv("EVENT_CALENDAR_KEYWORDS", "CPI,FOMC,NFP")

    monkeypatch.setattr(
        providers,
        "_read_json_retry",
        lambda *_args, **_kwargs: {
            "events": [
                {"timestamp": now + 1800, "severity": 1, "currency": "EUR", "name": "CPI y/y"},
                {"timestamp": now + 3600, "severity": 1, "currency": "USD", "name": "FOMC Minutes"},
            ]
        },
    )

    result = providers.fetch_event_risk_context()
    assert result.payload["event_severity"] == 2
    assert result.degraded is False


def test_calendar_no_relevant_events_note(monkeypatch):
    now = 1_700_000_000

    class _Now:
        @staticmethod
        def time():
            return now

        @staticmethod
        def sleep(_seconds):
            return None

    monkeypatch.setattr(providers, "time", _Now)
    monkeypatch.setenv("EVENT_CALENDAR_URL", "https://calendar.local/events")
    monkeypatch.setenv("EVENT_CALENDAR_CURRENCY", "USD")
    monkeypatch.setenv("EVENT_CALENDAR_KEYWORDS", "NFP")

    monkeypatch.setattr(
        providers,
        "_read_json_retry",
        lambda *_args, **_kwargs: {"events": [{"timestamp": now + 1000, "severity": 3, "currency": "JPY", "name": "BOJ"}]},
    )

    result = providers.fetch_event_risk_context()
    assert result.payload["event_severity"] == 0
    assert "event_calendar_no_relevant_events" in result.notes


def test_calendar_low_coverage_sets_degraded(monkeypatch):
    now = 1_700_000_000

    class _Now:
        @staticmethod
        def time():
            return now

        @staticmethod
        def sleep(_seconds):
            return None

    monkeypatch.setattr(providers, "time", _Now)
    monkeypatch.setenv("EVENT_CALENDAR_URL", "https://calendar.local/events")
    monkeypatch.setenv("EVENT_CALENDAR_CURRENCY", "USD")
    monkeypatch.setenv("EVENT_CALENDAR_KEYWORDS", "NFP")

    monkeypatch.setattr(
        providers,
        "_read_json_retry",
        lambda *_args, **_kwargs: {"events": [{"timestamp": now + 1000, "severity": 3, "currency": "JPY", "name": "BOJ"}]},
    )

    result = providers.fetch_event_risk_context()
    assert result.degraded is True
    assert result.payload["calendar_coverage_score"] == 0.0
    assert "event_calendar_low_coverage" in result.notes
