-- ===========================================================================
-- Calvin AI Vault Trading Database Migration
-- Adds enhanced tracking for vault trading operations
-- FIXED TO MATCH MAIN SCHEMA EXACTLY
-- ===========================================================================

-- Note: No transaction wrapper due to TimescaleDB materialized view limitations

-- ===========================================================================
-- 1. ENHANCE TRADES TABLE WITH VAULT-SPECIFIC COLUMNS
-- ===========================================================================

-- Add new columns to existing trades table (EXACT MATCH TO MAIN SCHEMA)
ALTER TABLE trades 
    ADD COLUMN IF NOT EXISTS signal_confidence DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS model_version VARCHAR(50),
    ADD COLUMN IF NOT EXISTS signal_strength VARCHAR(20),
    ADD COLUMN IF NOT EXISTS predicted_change_pct DECIMAL(8,4),
    ADD COLUMN IF NOT EXISTS cycle_timestamp TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS jupiter_operation_id INTEGER;

-- Add constraints for new columns (EXACT MATCH TO MAIN SCHEMA)
DO $$
BEGIN
    BEGIN
        ALTER TABLE trades ADD CONSTRAINT check_signal_confidence 
            CHECK (signal_confidence IS NULL OR (signal_confidence >= 0 AND signal_confidence <= 100));
    EXCEPTION WHEN duplicate_object THEN
        RAISE NOTICE 'Constraint check_signal_confidence already exists, skipping';
    END;
    
    BEGIN
        ALTER TABLE trades ADD CONSTRAINT check_signal_strength 
            CHECK (signal_strength IS NULL OR signal_strength IN ('STRONG', 'MODERATE', 'WEAK'));
    EXCEPTION WHEN duplicate_object THEN
        RAISE NOTICE 'Constraint check_signal_strength already exists, skipping';
    END;
END $$;

-- Create indexes for new columns (EXACT MATCH TO MAIN SCHEMA)
CREATE INDEX IF NOT EXISTS idx_trades_cycle_timestamp ON trades(cycle_timestamp DESC) WHERE cycle_timestamp IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trades_model_version ON trades(model_version) WHERE model_version IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trades_signal_confidence ON trades(signal_confidence DESC) WHERE signal_confidence IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trades_jupiter_operation ON trades(jupiter_operation_id) WHERE jupiter_operation_id IS NOT NULL;

-- ===========================================================================
-- 2. CREATE PORTFOLIO_CYCLES TABLE (EXACT MATCH TO MAIN SCHEMA)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS portfolio_cycles (
    cycle_id SERIAL PRIMARY KEY,
    cycle_timestamp TIMESTAMPTZ NOT NULL,         -- Cycle start time (partitioning column)
    
    -- Cycle metrics
    tokens_analyzed INTEGER NOT NULL DEFAULT 0,   -- Number of tokens analyzed
    signals_generated INTEGER NOT NULL DEFAULT 0, -- Total signals generated
    buy_signals INTEGER NOT NULL DEFAULT 0,       -- Buy signals count
    sell_signals INTEGER NOT NULL DEFAULT 0,      -- Sell signals count
    trades_executed INTEGER NOT NULL DEFAULT 0,   -- Actual trades executed
    
    -- Portfolio risk assessment
    portfolio_risk_score DECIMAL(5,2),            -- Overall portfolio risk (0-100)
    max_position_size_pct DECIMAL(5,2),           -- Largest position as % of portfolio
    diversification_score DECIMAL(5,2),           -- Portfolio diversification (0-100)
    correlation_risk DECIMAL(5,2),                -- Asset correlation risk (0-100)
    
    -- Performance metrics
    total_portfolio_value_usdc DECIMAL(20,8),     -- Total portfolio value at cycle start
    available_cash_usdc DECIMAL(20,8),            -- Available cash for trading
    execution_priority VARCHAR(20),               -- 'HIGH', 'MEDIUM', 'LOW'
    
    -- Execution timing
    data_fetch_duration_ms INTEGER,               -- Time to fetch and process data
    inference_duration_ms INTEGER,                -- Time for LSTM inference
    signal_processing_duration_ms INTEGER,        -- Time for signal processing
    trade_execution_duration_ms INTEGER,          -- Time for trade execution
    total_cycle_duration_ms INTEGER,              -- Total cycle time
    
    -- Status and metadata
    cycle_status VARCHAR(20) NOT NULL DEFAULT 'completed', -- 'running', 'completed', 'failed'
    error_message TEXT,                           -- Error details if failed
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT check_cycle_status CHECK (cycle_status IN ('running', 'completed', 'failed')),
    CONSTRAINT check_execution_priority CHECK (execution_priority IS NULL OR execution_priority IN ('HIGH', 'MEDIUM', 'LOW')),
    CONSTRAINT check_signal_counts CHECK (signals_generated >= buy_signals + sell_signals)
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('portfolio_cycles', 'cycle_timestamp', chunk_time_interval => INTERVAL '1 week', if_not_exists => TRUE);

-- Create indexes for portfolio cycles (EXACT MATCH TO MAIN SCHEMA)
CREATE INDEX IF NOT EXISTS idx_portfolio_cycles_timestamp ON portfolio_cycles(cycle_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_portfolio_cycles_status ON portfolio_cycles(cycle_status, cycle_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_portfolio_cycles_risk_score ON portfolio_cycles(portfolio_risk_score DESC) WHERE portfolio_risk_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_portfolio_cycles_execution_priority ON portfolio_cycles(execution_priority, cycle_timestamp DESC) WHERE execution_priority IS NOT NULL;

-- Enable compression for older portfolio cycle data
ALTER TABLE portfolio_cycles SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'cycle_status,execution_priority',
    timescaledb.compress_orderby = 'cycle_timestamp DESC'
);
SELECT add_compression_policy('portfolio_cycles', INTERVAL '30 days', if_not_exists => TRUE);

-- ===========================================================================
-- 3. CREATE JUPITER_OPERATIONS TABLE (EXACT MATCH TO MAIN SCHEMA)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS jupiter_operations (
    operation_id SERIAL PRIMARY KEY,
    operation_timestamp TIMESTAMPTZ NOT NULL,     -- Operation time (partitioning column)
    
    -- Operation details
    operation_type VARCHAR(20) NOT NULL,          -- 'quote', 'swap', 'route_discovery'
    input_mint VARCHAR(44) NOT NULL,              -- Input token mint address
    output_mint VARCHAR(44) NOT NULL,             -- Output token mint address
    
    -- Trade amounts
    input_amount BIGINT NOT NULL,                 -- Input amount (in token's smallest unit)
    output_amount BIGINT,                         -- Expected/actual output amount
    slippage_bps INTEGER NOT NULL,                -- Slippage tolerance in basis points
    
    -- Execution results
    actual_output_amount BIGINT,                  -- Actual amount received (for swaps)
    price_impact_pct DECIMAL(8,4),                -- Price impact percentage
    fee_amount BIGINT,                            -- Fee paid (in input token)
    fee_mint VARCHAR(44),                         -- Fee token mint
    
    -- Route information
    route_plan JSONB,                             -- Jupiter route plan (AMMs used)
    market_infos JSONB,                           -- Market information from Jupiter
    
    -- Execution details
    tx_hash VARCHAR(88),                          -- Transaction hash (for swaps)
    success BOOLEAN DEFAULT NULL,                 -- Operation success (NULL for quotes)
    error_message TEXT,                           -- Error details if failed
    
    -- Performance metrics
    quote_response_time_ms INTEGER,               -- Time to get quote
    swap_execution_time_ms INTEGER,               -- Time to execute swap
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT check_operation_type CHECK (operation_type IN ('quote', 'swap', 'route_discovery')),
    CONSTRAINT check_amounts CHECK (input_amount > 0 AND (output_amount IS NULL OR output_amount > 0)),
    CONSTRAINT check_slippage CHECK (slippage_bps >= 0 AND slippage_bps <= 10000) -- Max 100% slippage
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('jupiter_operations', 'operation_timestamp', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);

-- Create indexes for jupiter operations (EXACT MATCH TO MAIN SCHEMA)
CREATE INDEX IF NOT EXISTS idx_jupiter_operations_timestamp ON jupiter_operations(operation_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jupiter_operations_type ON jupiter_operations(operation_type, operation_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jupiter_operations_input_mint ON jupiter_operations(input_mint, operation_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jupiter_operations_output_mint ON jupiter_operations(output_mint, operation_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jupiter_operations_success ON jupiter_operations(success, operation_timestamp DESC) WHERE success IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jupiter_operations_tx_hash ON jupiter_operations(tx_hash) WHERE tx_hash IS NOT NULL;

-- Enable compression for older Jupiter operations
ALTER TABLE jupiter_operations SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'operation_type,input_mint,output_mint',
    timescaledb.compress_orderby = 'operation_timestamp DESC'
);
SELECT add_compression_policy('jupiter_operations', INTERVAL '7 days', if_not_exists => TRUE);

-- ===========================================================================
-- 4. CREATE EMERGENCY_EVENTS TABLE (EXACT MATCH TO MAIN SCHEMA)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS emergency_events (
    event_id SERIAL PRIMARY KEY,
    event_timestamp TIMESTAMPTZ NOT NULL,         -- Event time (partitioning column)
    
    -- Event classification
    event_type VARCHAR(30) NOT NULL,              -- 'stop_loss', 'portfolio_stop', 'volatility_halt', etc.
    severity VARCHAR(20) NOT NULL,                -- 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    token_id INTEGER,                             -- Affected token (NULL for portfolio-wide events)
    
    -- Trigger conditions
    trigger_condition JSONB NOT NULL,             -- Condition that triggered the event
    current_metrics JSONB,                        -- Current portfolio/position metrics
    threshold_breached JSONB,                     -- Threshold values that were breached
    
    -- Response actions
    action_taken VARCHAR(50),                     -- 'position_exit', 'trading_halt', 'alert_only', etc.
    positions_affected INTEGER DEFAULT 0,         -- Number of positions affected
    total_value_affected_usdc DECIMAL(20,8),      -- Total value of affected positions
    
    -- Execution results
    action_successful BOOLEAN,                    -- Whether the response action succeeded
    execution_time_ms INTEGER,                    -- Time to execute response
    tx_hashes TEXT[],                             -- Transaction hashes (if trades executed)
    
    -- Recovery information
    resolved_timestamp TIMESTAMPTZ,               -- When the emergency condition was resolved
    resolution_method VARCHAR(50),                -- How the emergency was resolved
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT fk_emergency_events_token FOREIGN KEY (token_id) REFERENCES tokens(token_id),
    CONSTRAINT check_event_severity CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    CONSTRAINT check_positions_affected CHECK (positions_affected >= 0)
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('emergency_events', 'event_timestamp', chunk_time_interval => INTERVAL '1 week', if_not_exists => TRUE);

-- Create indexes for emergency events (EXACT MATCH TO MAIN SCHEMA)
CREATE INDEX IF NOT EXISTS idx_emergency_events_timestamp ON emergency_events(event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_emergency_events_type ON emergency_events(event_type, event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_emergency_events_severity ON emergency_events(severity, event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_emergency_events_token ON emergency_events(token_id, event_timestamp DESC) WHERE token_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_emergency_events_unresolved ON emergency_events(event_timestamp DESC) WHERE resolved_timestamp IS NULL;

-- Enable compression for older emergency events
ALTER TABLE emergency_events SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'event_type,severity',
    timescaledb.compress_orderby = 'event_timestamp DESC'
);
SELECT add_compression_policy('emergency_events', INTERVAL '90 days', if_not_exists => TRUE);

-- ===========================================================================
-- 5. CREATE MATERIALIZED VIEWS FOR MONITORING (EXACT MATCH TO MAIN SCHEMA)
-- ===========================================================================

-- Trading performance hourly view (regular materialized view since trades is not a hypertable)
DROP MATERIALIZED VIEW IF EXISTS trading_performance_hourly;
CREATE MATERIALIZED VIEW trading_performance_hourly AS
SELECT 
    date_trunc('hour', t.execution_time) AS hour,
    t.token_id,
    tk.symbol,
    count(*) as trade_count,
    sum(CASE WHEN t.trade_type = 'buy' THEN 1 ELSE 0 END) as buy_count,
    sum(CASE WHEN t.trade_type = 'sell' THEN 1 ELSE 0 END) as sell_count,
    sum(t.value_usdc) as total_volume_usdc,
    avg(t.signal_confidence) as avg_confidence,
    avg(t.slippage_bps) as avg_slippage_bps,
    avg(t.processing_time_ms) as avg_execution_time_ms,
    count(DISTINCT t.cycle_timestamp) as unique_cycles
FROM trades t
JOIN tokens tk ON t.token_id = tk.token_id
WHERE t.cycle_timestamp IS NOT NULL  -- Only vault trades
  AND t.execution_time >= NOW() - INTERVAL '7 days'  -- Last 7 days only
GROUP BY date_trunc('hour', t.execution_time), t.token_id, tk.symbol
ORDER BY hour DESC;

-- Create index for performance
CREATE INDEX IF NOT EXISTS idx_trading_performance_hourly_hour ON trading_performance_hourly(hour DESC);

-- Portfolio Risk Hourly View (EXACT MATCH TO MAIN SCHEMA)
CREATE MATERIALIZED VIEW IF NOT EXISTS portfolio_risk_hourly
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 hour', cycle_timestamp) AS hour,
    count(*) as cycle_count,
    avg(portfolio_risk_score) as avg_risk_score,
    max(portfolio_risk_score) as max_risk_score,
    avg(diversification_score) as avg_diversification,
    avg(correlation_risk) as avg_correlation_risk,
    avg(total_portfolio_value_usdc) as avg_portfolio_value,
    avg(total_cycle_duration_ms) as avg_cycle_duration_ms,
    sum(trades_executed) as total_trades_executed,
    count(CASE WHEN cycle_status = 'failed' THEN 1 END) as failed_cycles
FROM portfolio_cycles
GROUP BY hour;

-- Auto-refresh portfolio risk view
SELECT add_continuous_aggregate_policy('portfolio_risk_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

-- Emergency Events Daily View (EXACT MATCH TO MAIN SCHEMA)
CREATE MATERIALIZED VIEW IF NOT EXISTS emergency_events_daily
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 day', event_timestamp) AS day,
    event_type,
    severity,
    count(*) as event_count,
    sum(positions_affected) as total_positions_affected,
    sum(total_value_affected_usdc) as total_value_affected,
    count(CASE WHEN action_successful = true THEN 1 END) as successful_responses,
    count(CASE WHEN resolved_timestamp IS NULL THEN 1 END) as unresolved_events,
    avg(execution_time_ms) as avg_response_time_ms
FROM emergency_events
GROUP BY day, event_type, severity;

-- Auto-refresh emergency events view (increased window size)
SELECT add_continuous_aggregate_policy('emergency_events_daily',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => TRUE);

-- ===========================================================================
-- 6. CREATE HELPER FUNCTIONS (EXACT MATCH TO MAIN SCHEMA)
-- ===========================================================================

-- Function to get portfolio performance summary (EXACT MATCH TO MAIN SCHEMA)
CREATE OR REPLACE FUNCTION get_portfolio_performance_summary(
    p_hours_back INTEGER DEFAULT 24
) RETURNS JSONB AS $$
DECLARE
    result JSONB;
    start_time TIMESTAMPTZ;
BEGIN
    start_time := NOW() - (p_hours_back || ' hours')::INTERVAL;
    
    SELECT jsonb_build_object(
        'period_hours', p_hours_back,
        'start_time', start_time,
        'end_time', NOW(),
        'cycles', jsonb_build_object(
            'total_cycles', COALESCE(COUNT(*), 0),
            'successful_cycles', COALESCE(COUNT(*) FILTER (WHERE cycle_status = 'completed'), 0),
            'failed_cycles', COALESCE(COUNT(*) FILTER (WHERE cycle_status = 'failed'), 0),
            'avg_cycle_duration_ms', COALESCE(AVG(total_cycle_duration_ms), 0),
            'avg_risk_score', COALESCE(AVG(portfolio_risk_score), 0)
        ),
        'trading', jsonb_build_object(
            'total_trades', COALESCE(SUM(trades_executed), 0),
            'total_signals', COALESCE(SUM(signals_generated), 0),
            'signal_execution_rate', CASE 
                WHEN SUM(signals_generated) > 0 THEN 
                    ROUND((SUM(trades_executed)::DECIMAL / SUM(signals_generated)) * 100, 2)
                ELSE 0 
            END
        ),
        'portfolio_metrics', jsonb_build_object(
            'avg_portfolio_value', COALESCE(AVG(total_portfolio_value_usdc), 0),
            'avg_available_cash', COALESCE(AVG(available_cash_usdc), 0),
            'avg_diversification', COALESCE(AVG(diversification_score), 0),
            'max_correlation_risk', COALESCE(MAX(correlation_risk), 0)
        )
    ) INTO result
    FROM portfolio_cycles
    WHERE cycle_timestamp >= start_time;
    
    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- Function to get trading performance by token (EXACT MATCH TO MAIN SCHEMA)
CREATE OR REPLACE FUNCTION get_trading_performance_by_token(
    p_hours_back INTEGER DEFAULT 24
) RETURNS TABLE (
    symbol VARCHAR(20),
    trade_count BIGINT,
    total_volume_usdc DECIMAL(20,8),
    avg_confidence DECIMAL(5,2),
    avg_slippage_bps DECIMAL(8,2),
    avg_execution_time_ms DECIMAL(8,2),
    unique_cycles BIGINT
) AS $$
DECLARE
    start_time TIMESTAMPTZ;
BEGIN
    start_time := NOW() - (p_hours_back || ' hours')::INTERVAL;
    
    RETURN QUERY
    SELECT 
        tk.symbol,
        COUNT(t.trade_id) as trade_count,
        COALESCE(SUM(t.value_usdc), 0) as total_volume_usdc,
        COALESCE(AVG(t.signal_confidence), 0) as avg_confidence,
        COALESCE(AVG(t.slippage_bps), 0) as avg_slippage_bps,
        COALESCE(AVG(t.processing_time_ms), 0) as avg_execution_time_ms,
        COUNT(DISTINCT t.cycle_timestamp) as unique_cycles
    FROM trades t
    JOIN tokens tk ON t.token_id = tk.token_id
    WHERE t.execution_time >= start_time
      AND t.cycle_timestamp IS NOT NULL  -- Only vault trades
    GROUP BY tk.symbol
    ORDER BY total_volume_usdc DESC;
END;
$$ LANGUAGE plpgsql;

-- Function to get emergency events summary (EXACT MATCH TO MAIN SCHEMA)
CREATE OR REPLACE FUNCTION get_emergency_events_summary(
    p_days_back INTEGER DEFAULT 7
) RETURNS JSONB AS $$
DECLARE
    result JSONB;
    start_time TIMESTAMPTZ;
BEGIN
    start_time := NOW() - (p_days_back || ' days')::INTERVAL;
    
    SELECT jsonb_build_object(
        'period_days', p_days_back,
        'start_time', start_time,
        'end_time', NOW(),
        'total_events', COALESCE(COUNT(*), 0),
        'by_severity', jsonb_object_agg(
            severity, 
            COUNT(*)
        ),
        'by_type', jsonb_object_agg(
            event_type,
            COUNT(*)
        ),
        'response_metrics', jsonb_build_object(
            'successful_responses', COALESCE(COUNT(*) FILTER (WHERE action_successful = true), 0),
            'failed_responses', COALESCE(COUNT(*) FILTER (WHERE action_successful = false), 0),
            'avg_response_time_ms', COALESCE(AVG(execution_time_ms), 0),
            'total_value_affected', COALESCE(SUM(total_value_affected_usdc), 0)
        ),
        'unresolved_events', COALESCE(COUNT(*) FILTER (WHERE resolved_timestamp IS NULL), 0)
    ) INTO result
    FROM emergency_events
    WHERE event_timestamp >= start_time;
    
    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- ===========================================================================
-- 7. GRANT PERMISSIONS
-- ===========================================================================

-- Grant permissions to development user
GRANT SELECT, INSERT, UPDATE, DELETE ON portfolio_cycles TO calvin_dev;
GRANT SELECT, INSERT, UPDATE, DELETE ON jupiter_operations TO calvin_dev;
GRANT SELECT, INSERT, UPDATE, DELETE ON emergency_events TO calvin_dev;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO calvin_dev;

-- Grant access to materialized views
GRANT SELECT ON trading_performance_hourly TO calvin_dev;
GRANT SELECT ON portfolio_risk_hourly TO calvin_dev;
GRANT SELECT ON emergency_events_daily TO calvin_dev;

-- Grant execute permissions on helper functions
GRANT EXECUTE ON FUNCTION get_portfolio_performance_summary(INTEGER) TO calvin_dev;
GRANT EXECUTE ON FUNCTION get_trading_performance_by_token(INTEGER) TO calvin_dev;
GRANT EXECUTE ON FUNCTION get_emergency_events_summary(INTEGER) TO calvin_dev;

-- ===========================================================================
-- 8. LOG MIGRATION COMPLETION
-- ===========================================================================

-- Log successful migration
INSERT INTO system_health (check_time, component, status, details) VALUES (
    NOW(),
    'vault_database_migration', 
    'healthy', 
    jsonb_build_object(
        'message', 'Vault trading database migration completed successfully',
        'tables_enhanced', 1,
        'tables_created', 3,
        'materialized_views_created', 3,
        'functions_created', 3,
        'migration_timestamp', NOW(),
        'features_added', ARRAY[
            'enhanced_trades_table',
            'portfolio_cycle_tracking',
            'jupiter_operation_tracking',
            'emergency_event_tracking',
            'performance_monitoring_views',
            'helper_functions'
        ]
    )
);

-- Migration completed (no transaction wrapper used)

-- ===========================================================================
-- MIGRATION VALIDATION
-- ===========================================================================

-- Validate that all new columns exist in trades table
DO $$
DECLARE
    missing_columns TEXT[];
    expected_columns TEXT[] := ARRAY['signal_confidence', 'model_version', 'signal_strength', 'predicted_change_pct', 'cycle_timestamp', 'jupiter_operation_id'];
    col TEXT;
BEGIN
    FOREACH col IN ARRAY expected_columns
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'trades' AND column_name = col
        ) THEN
            missing_columns := array_append(missing_columns, col);
        END IF;
    END LOOP;
    
    IF array_length(missing_columns, 1) > 0 THEN
        RAISE EXCEPTION 'Migration validation failed: Missing columns in trades table: %', array_to_string(missing_columns, ', ');
    END IF;
    
    RAISE NOTICE 'Trades table validation passed: All new columns exist';
END $$;

-- Validate that all new tables exist
DO $$
DECLARE
    missing_tables TEXT[];
    expected_tables TEXT[] := ARRAY['portfolio_cycles', 'jupiter_operations', 'emergency_events'];
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY expected_tables
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_name = tbl
        ) THEN
            missing_tables := array_append(missing_tables, tbl);
        END IF;
    END LOOP;
    
    IF array_length(missing_tables, 1) > 0 THEN
        RAISE EXCEPTION 'Migration validation failed: Missing tables: %', array_to_string(missing_tables, ', ');
    END IF;
    
    RAISE NOTICE 'Table validation passed: All new tables exist';
END $$;

-- Final success message
SELECT 'Vault trading database migration completed successfully!' AS migration_status; 