-- Limit order book raw updates (columnar)
CREATE TABLE IF NOT EXISTS limitbook_updates (
  ts timestamptz NOT NULL,
  exchange text NOT NULL,
  symbol text NOT NULL,
  update_type text NOT NULL,
  is_buy boolean NOT NULL,
  price double precision NOT NULL,
  size bigint NOT NULL,
  order_id uuid NOT NULL
);
SELECT create_hypertable(
  'limitbook_updates','ts',
  chunk_time_interval => interval '6 hours',
  partitioning_column => 'symbol',
  number_partitions  => 8,
  if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_lbu_symbol_time_desc ON limitbook_updates(symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_lbu_exchange_time_desc ON limitbook_updates(exchange, ts DESC);

ALTER TABLE limitbook_updates SET (
  timescaledb.compress = true,
  timescaledb.compress_orderby = 'ts',
  timescaledb.compress_segmentby = 'exchange,symbol,is_buy,update_type'
);
SELECT add_compression_policy('limitbook_updates', interval '2 hours', if_not_exists => TRUE);

-- Top-of-book per second (continuous aggregate)
CREATE MATERIALIZED VIEW IF NOT EXISTS tob_1s
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1s', ts) AS bucket,
  exchange, symbol,
  max(price) FILTER (WHERE is_buy)     AS best_bid,
  min(price) FILTER (WHERE NOT is_buy) AS best_ask
FROM limitbook_updates
WHERE update_type = 'SNAPSHOT'
GROUP BY bucket, exchange, symbol;

SELECT add_continuous_aggregate_policy(
  'tob_1s',
  start_offset => INTERVAL '1 day',
  end_offset   => INTERVAL '5 minutes',
  schedule_interval => INTERVAL '5 minutes',
  if_not_exists => TRUE
);

-- Microstructure per-minute aggregate from limitbook_updates (continuous aggregate)
CREATE MATERIALIZED VIEW IF NOT EXISTS lbu_1m
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 minute', ts) AS bucket,
  exchange,
  symbol,
  COUNT(*)                                  AS lb_update_count,
  SUM(CASE WHEN is_buy THEN 1 ELSE 0 END)   AS lb_buy_updates,
  SUM(CASE WHEN NOT is_buy THEN 1 ELSE 0 END) AS lb_sell_updates,
  SUM(CASE WHEN is_buy THEN size ELSE 0 END)::bigint     AS lb_buy_vol,
  SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END)::bigint AS lb_sell_vol,
  -- size-weighted buy/sell prices
  SUM(CASE WHEN is_buy THEN price*size ELSE 0 END)    AS _buy_px_wsum,
  SUM(CASE WHEN is_buy THEN size ELSE 0 END)          AS _buy_sz_sum,
  SUM(CASE WHEN NOT is_buy THEN price*size ELSE 0 END) AS _sell_px_wsum,
  SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END)       AS _sell_sz_sum,
  -- best bid/ask from all updates (ADD/DELETE/SET/MATCH)
  MAX(price) FILTER (WHERE is_buy)     AS lb_best_bid,
  MIN(price) FILTER (WHERE NOT is_buy) AS lb_best_ask,
  -- derived metrics
  CASE WHEN (SUM(CASE WHEN is_buy THEN size ELSE 0 END)
            + SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END)) > 0
       THEN (SUM(CASE WHEN is_buy THEN size ELSE 0 END)
            - SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END))
          / NULLIF((SUM(CASE WHEN is_buy THEN size ELSE 0 END)
                   + SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END)),0)::numeric
       ELSE NULL END AS lb_imbalance,
  CASE WHEN SUM(CASE WHEN is_buy THEN size ELSE 0 END) > 0
       THEN (SUM(CASE WHEN is_buy THEN price*size ELSE 0 END)
            / NULLIF(SUM(CASE WHEN is_buy THEN size ELSE 0 END),0))
       ELSE NULL END AS lb_avg_buy_px,
  CASE WHEN SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END) > 0
       THEN (SUM(CASE WHEN NOT is_buy THEN price*size ELSE 0 END)
            / NULLIF(SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END),0))
       ELSE NULL END AS lb_avg_sell_px,
  CASE WHEN ( (MIN(price) FILTER (WHERE NOT is_buy))
            + (MAX(price) FILTER (WHERE is_buy)) ) > 0
       THEN ((MIN(price) FILTER (WHERE NOT is_buy))
            - (MAX(price) FILTER (WHERE is_buy)))
            / (((MIN(price) FILTER (WHERE NOT is_buy))
               + (MAX(price) FILTER (WHERE is_buy)))/2.0) * 1e4
       ELSE NULL END AS lb_spread_bps
FROM limitbook_updates
GROUP BY bucket, exchange, symbol;

-- Fix: Recreate lbu_1m with all update types (not just SNAPSHOT)
DROP MATERIALIZED VIEW IF EXISTS lbu_1m CASCADE;

-- Microstructure per-minute aggregate from limitbook_updates (continuous aggregate)
CREATE MATERIALIZED VIEW IF NOT EXISTS lbu_1m
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 minute', ts) AS bucket,
  exchange,
  symbol,
  COUNT(*)                                  AS lb_update_count,
  SUM(CASE WHEN is_buy THEN 1 ELSE 0 END)   AS lb_buy_updates,
  SUM(CASE WHEN NOT is_buy THEN 1 ELSE 0 END) AS lb_sell_updates,
  SUM(CASE WHEN is_buy THEN size ELSE 0 END)::bigint     AS lb_buy_vol,
  SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END)::bigint AS lb_sell_vol,
  -- size-weighted buy/sell prices
  SUM(CASE WHEN is_buy THEN price*size ELSE 0 END)    AS _buy_px_wsum,
  SUM(CASE WHEN is_buy THEN size ELSE 0 END)          AS _buy_sz_sum,
  SUM(CASE WHEN NOT is_buy THEN price*size ELSE 0 END) AS _sell_px_wsum,
  SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END)       AS _sell_sz_sum,
  -- FIXED: Use median prices to avoid impossible bid > ask situations
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) FILTER (WHERE is_buy)     AS lb_best_bid,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) FILTER (WHERE NOT is_buy) AS lb_best_ask,
  -- derived metrics
  CASE WHEN (SUM(CASE WHEN is_buy THEN size ELSE 0 END)
            + SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END)) > 0
       THEN (SUM(CASE WHEN is_buy THEN size ELSE 0 END)
            - SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END))
          / NULLIF((SUM(CASE WHEN is_buy THEN size ELSE 0 END)
                   + SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END)),0)::numeric
       ELSE NULL END AS lb_imbalance,
  CASE WHEN SUM(CASE WHEN is_buy THEN size ELSE 0 END) > 0
       THEN (SUM(CASE WHEN is_buy THEN price*size ELSE 0 END)
            / NULLIF(SUM(CASE WHEN is_buy THEN size ELSE 0 END),0))
       ELSE NULL END AS lb_avg_buy_px,
  CASE WHEN SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END) > 0
       THEN (SUM(CASE WHEN NOT is_buy THEN price*size ELSE 0 END)
            / NULLIF(SUM(CASE WHEN NOT is_buy THEN size ELSE 0 END),0))
       ELSE NULL END AS lb_avg_sell_px,
  -- FIXED: Ensure spread calculation uses median prices to avoid negative spreads
  CASE WHEN (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) FILTER (WHERE NOT is_buy) >
             PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) FILTER (WHERE is_buy))
       THEN (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) FILTER (WHERE NOT is_buy) -
             PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) FILTER (WHERE is_buy))
            / ((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) FILTER (WHERE NOT is_buy) +
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) FILTER (WHERE is_buy))/2.0) * 1e4
       ELSE 0 END AS lb_spread_bps
FROM limitbook_updates
GROUP BY bucket, exchange, symbol;

SELECT add_continuous_aggregate_policy(
  'lbu_1m',
  start_offset => INTERVAL '3 days',
  end_offset   => INTERVAL '5 minutes',
  schedule_interval => INTERVAL '5 minutes'
);

CREATE INDEX IF NOT EXISTS idx_lbu_1m_symbol_time ON lbu_1m(symbol, bucket DESC);
CREATE INDEX IF NOT EXISTS idx_lbu_1m_exchange_time ON lbu_1m(exchange, bucket DESC);

-- To refresh historical data, use the refresh_lbu_1m.py script
