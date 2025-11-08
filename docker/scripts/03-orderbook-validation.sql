-- Basic validation queries for orderbook_levels-derived aggregates
-- 1) Check row counts per day and symbol
SELECT
  date_trunc('day', ts) AS day,
  exchange, base, quote,
  COUNT(*) AS rows
FROM orderbook_levels
GROUP BY day, exchange, base, quote
ORDER BY day DESC, exchange, base, quote;

-- 2) Spot-check per-second top-of-book and spread sanity
SELECT *
FROM ob_tob_1s
WHERE base = 'BTC' AND quote = 'USDT'
ORDER BY bucket DESC
LIMIT 100;

-- 3) Ensure spreads are non-negative
SELECT COUNT(*) FILTER (WHERE spread_bps < 0) AS negative_spreads
FROM ob_tob_1s;

-- 4) Per-minute depth metrics for a symbol
SELECT *
FROM ob_depth_1m_k20
WHERE base = 'BTC' AND quote = 'USDT'
ORDER BY bucket DESC
LIMIT 100;

-- 5) Derived unix ms in queries (example)
SELECT
  (extract(epoch from bucket)*1000)::bigint AS bucket_unix_ms,
  exchange, base, quote, best_bid, best_ask, spread_bps
FROM ob_tob_1s
ORDER BY bucket DESC
LIMIT 100;


