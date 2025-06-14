-- ===========================================================================
-- Calvin AI Trading System Database Initialization
-- TimescaleDB + PostgreSQL schema optimized for time-series trading data
-- ===========================================================================

-- Create TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ===========================================================================
-- TOKENS TABLE (Enhanced with metadata)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS tokens (
    token_id SERIAL PRIMARY KEY,
    address VARCHAR(44) UNIQUE NOT NULL,           -- Solana token address (base58)
    symbol VARCHAR(20) NOT NULL,                   -- Token symbol (SOL, USDC, etc.)
    name VARCHAR(100),                             -- Full token name
    decimals INTEGER NOT NULL DEFAULT 9,          -- Token decimals
    is_active BOOLEAN DEFAULT true,               -- Whether we're actively trading this token
    
    -- Enhanced metadata from BirdEye API
    coingecko_id VARCHAR(100),                    -- CoinGecko ID for price tracking
    website VARCHAR(200),                         -- Official website
    twitter VARCHAR(200),                         -- Twitter handle
    discord VARCHAR(200),                         -- Discord server
    telegram VARCHAR(200),                        -- Telegram channel
    description TEXT,                             -- Token description
    logo_uri VARCHAR(500),                        -- Token logo URL
    
    -- Social data integration
    lunarcrush_id INTEGER,                        -- LunarCrush internal asset ID
    lunarcrush_symbol VARCHAR(20),                -- LunarCrush symbol (may differ from our symbol)
    lunarcrush_topic VARCHAR(100),                -- LunarCrush social topic
    
    -- Tracking
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_api_update TIMESTAMPTZ,                  -- Last time metadata was updated from API
    last_social_update TIMESTAMPTZ,               -- Last time LunarCrush data was updated
    
    -- Validation flags
    metadata_verified BOOLEAN DEFAULT false,      -- Whether metadata was fetched from API
    trading_enabled BOOLEAN DEFAULT false,        -- Whether this token is approved for trading
    social_data_available BOOLEAN DEFAULT false   -- Whether LunarCrush ID is available
);

-- Create indexes for tokens
CREATE INDEX IF NOT EXISTS idx_tokens_address ON tokens(address);
CREATE INDEX IF NOT EXISTS idx_tokens_symbol ON tokens(symbol);
CREATE INDEX IF NOT EXISTS idx_tokens_active ON tokens(is_active);
CREATE INDEX IF NOT EXISTS idx_tokens_trading_enabled ON tokens(trading_enabled);
CREATE INDEX IF NOT EXISTS idx_tokens_lunarcrush_id ON tokens(lunarcrush_id);
CREATE INDEX IF NOT EXISTS idx_tokens_social_data_available ON tokens(social_data_available);

-- ===========================================================================
-- TOKEN MANAGEMENT FUNCTIONS (Auto-backfill & Consistency)
-- ===========================================================================

-- Function to safely get or create a token (prevents duplicates)
CREATE OR REPLACE FUNCTION get_or_create_token(
    p_address VARCHAR(44),
    p_symbol VARCHAR(20),
    p_name VARCHAR(100) DEFAULT NULL,
    p_decimals INTEGER DEFAULT 9
) RETURNS INTEGER AS $$
DECLARE
    token_record tokens%ROWTYPE;
    result_token_id INTEGER;
BEGIN
    -- First, try to find existing token by address (most reliable)
    SELECT * INTO token_record FROM tokens WHERE address = p_address;
    
    IF FOUND THEN
        -- Update symbol/name if provided and different
        IF p_symbol IS NOT NULL AND token_record.symbol != p_symbol THEN
            UPDATE tokens SET 
                symbol = p_symbol,
                updated_at = NOW()
            WHERE token_id = token_record.token_id;
        END IF;
        
        RETURN token_record.token_id;
    END IF;
    
    -- If not found by address, check by symbol (prevent symbol conflicts)
    SELECT * INTO token_record FROM tokens WHERE symbol = p_symbol;
    
    IF FOUND THEN
        -- If symbol exists but address is different, this might be an error
        RAISE WARNING 'Symbol % already exists with different address. Existing: %, New: %', 
            p_symbol, token_record.address, p_address;
    END IF;
    
    -- Create new token
    INSERT INTO tokens (address, symbol, name, decimals)
    VALUES (p_address, p_symbol, p_name, p_decimals)
    RETURNING token_id INTO result_token_id;
    
    -- Log the creation
    INSERT INTO system_health (check_time, component, status, details) VALUES (
        NOW(),
        'token_management',
        'healthy',
        jsonb_build_object(
            'action', 'token_created',
            'token_id', result_token_id,
            'address', p_address,
            'symbol', p_symbol
        )
    );
    
    RETURN result_token_id;
END;
$$ LANGUAGE plpgsql;

-- Function to initialize tracked tokens from environment variable
CREATE OR REPLACE FUNCTION initialize_tracked_tokens()
RETURNS JSONB AS $$
DECLARE
    tracked_tokens_env TEXT;
    token_addresses TEXT[];
    addr TEXT;
    created_count INTEGER := 0;
BEGIN
    -- Get tracked tokens from environment variable
    SELECT current_setting('app.tracked_tokens', true) INTO tracked_tokens_env;
    
    IF tracked_tokens_env IS NULL OR tracked_tokens_env = '' THEN
        RAISE WARNING 'TRACKED_TOKENS environment variable not set. Please configure app.tracked_tokens.';
        RETURN jsonb_build_object('error', 'TRACKED_TOKENS not configured', 'created', 0);
    END IF;
    
    -- Split comma-separated addresses
    SELECT string_to_array(replace(tracked_tokens_env, ' ', ''), ',') INTO token_addresses;
    
    -- Create placeholder tokens for each address (metadata will be filled by application)
    FOREACH addr IN ARRAY token_addresses
    LOOP
        BEGIN
            INSERT INTO tokens (address, symbol, name, decimals, is_active)
            VALUES (addr, 'TBD', 'To Be Determined', 9, true)
            ON CONFLICT (address) DO UPDATE SET
                is_active = true,
                updated_at = NOW();
            created_count := created_count + 1;
        EXCEPTION WHEN others THEN
            -- Log error but continue with other tokens
            RAISE WARNING 'Failed to create token with address %: %', addr, SQLERRM;
        END;
    END LOOP;
    
    RETURN jsonb_build_object(
        'success', true, 
        'created', created_count,
        'message', 'Placeholder tokens created - use application layer to fetch metadata'
    );
END;
$$ LANGUAGE plpgsql;

-- ===========================================================================
-- CROSS-VALIDATION TRIGGERS (Prevent Inconsistencies)
-- ===========================================================================

-- Function to validate token references
CREATE OR REPLACE FUNCTION validate_token_reference()
RETURNS TRIGGER AS $$
BEGIN
    -- Ensure the token exists and is active
    IF NOT EXISTS (SELECT 1 FROM tokens WHERE token_id = NEW.token_id AND is_active = true) THEN
        RAISE EXCEPTION 'Token ID % does not exist or is inactive', NEW.token_id;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ===========================================================================
-- OHLCV TIME-SERIES TABLE (Hypertable)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS ohlcv (
    time TIMESTAMPTZ NOT NULL,                    -- Candle timestamp
    token_id INTEGER NOT NULL,                    -- Foreign key to tokens
    resolution VARCHAR(10) NOT NULL,              -- 1m, 5m, 15m, 1h, 4h, 1d
    open DOUBLE PRECISION NOT NULL,               -- Opening price
    high DOUBLE PRECISION NOT NULL,               -- Highest price
    low DOUBLE PRECISION NOT NULL,                -- Lowest price
    close DOUBLE PRECISION NOT NULL,              -- Closing price
    volume DOUBLE PRECISION NOT NULL DEFAULT 0,   -- Volume in base token
    volume_usd DOUBLE PRECISION,                  -- Volume in USD
    trades_count INTEGER,                         -- Number of trades in period
    data_source VARCHAR(20) DEFAULT 'birdeye',    -- Data source (birdeye, websocket)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT fk_ohlcv_token FOREIGN KEY (token_id) REFERENCES tokens(token_id),
    CONSTRAINT check_ohlcv_prices CHECK (open > 0 AND high > 0 AND low > 0 AND close > 0),
    CONSTRAINT check_ohlcv_high_low CHECK (high >= low),
    CONSTRAINT check_ohlcv_volume CHECK (volume >= 0),
    CONSTRAINT unique_ohlcv_time_token_resolution UNIQUE (time, token_id, resolution)
);

-- Convert to hypertable (main time-series optimization)
SELECT create_hypertable('ohlcv', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_ohlcv_token_time_desc ON ohlcv (token_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_time_resolution ON ohlcv (time DESC, resolution);
CREATE INDEX IF NOT EXISTS idx_ohlcv_token_resolution ON ohlcv (token_id, resolution, time DESC);

-- Enable compression for older data
ALTER TABLE ohlcv SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'token_id,resolution'
);

-- Auto-compress data older than 7 days
SELECT add_compression_policy('ohlcv', INTERVAL '7 days', if_not_exists => TRUE);

-- Retention policy (keep 2 years of data)
SELECT add_retention_policy('ohlcv', INTERVAL '2 years', if_not_exists => TRUE);

-- ===========================================================================
-- POSITIONS TABLE
-- ===========================================================================

CREATE TABLE IF NOT EXISTS positions (
    position_id SERIAL PRIMARY KEY,
    token_id INTEGER NOT NULL,                    -- Foreign key to tokens
    position_type VARCHAR(10) NOT NULL,           -- 'long' or 'short'
    status VARCHAR(20) NOT NULL DEFAULT 'open',   -- 'open', 'closed', 'partial'
    
    -- Entry details
    entry_price DOUBLE PRECISION NOT NULL,        -- Entry price
    entry_quantity DOUBLE PRECISION NOT NULL,     -- Position size in tokens
    entry_value_usdc DOUBLE PRECISION NOT NULL,   -- Position value in USDC
    entry_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    entry_tx_hash VARCHAR(88),                    -- Solana transaction hash
    
    -- Exit details (nullable for open positions)
    exit_price DOUBLE PRECISION,                  -- Exit price
    exit_quantity DOUBLE PRECISION,               -- Quantity sold
    exit_value_usdc DOUBLE PRECISION,             -- Exit value in USDC
    exit_time TIMESTAMPTZ,
    exit_tx_hash VARCHAR(88),
    
    -- Risk management
    stop_loss_price DOUBLE PRECISION,             -- Stop loss trigger price
    take_profit_price DOUBLE PRECISION,           -- Take profit trigger price
    
    -- P&L tracking
    realized_pnl_usdc DOUBLE PRECISION DEFAULT 0, -- Realized profit/loss
    unrealized_pnl_usdc DOUBLE PRECISION DEFAULT 0, -- Current unrealized P&L
    fees_paid_usdc DOUBLE PRECISION DEFAULT 0,    -- Total fees paid
    
    -- Model information
    model_prediction_confidence DOUBLE PRECISION, -- Model confidence score
    model_version VARCHAR(50),                     -- Model version used
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT fk_positions_token FOREIGN KEY (token_id) REFERENCES tokens(token_id),
    CONSTRAINT check_position_type CHECK (position_type IN ('long', 'short')),
    CONSTRAINT check_position_status CHECK (status IN ('open', 'closed', 'partial')),
    CONSTRAINT check_position_prices CHECK (entry_price > 0),
    CONSTRAINT check_position_quantities CHECK (entry_quantity > 0)
);

-- Create indexes for positions
CREATE INDEX IF NOT EXISTS idx_positions_token_status ON positions(token_id, status);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_entry_time ON positions(entry_time DESC);
CREATE INDEX IF NOT EXISTS idx_positions_open ON positions(token_id) WHERE status = 'open';

-- ===========================================================================
-- TRADES TABLE (Individual trade executions)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS trades (
    trade_id SERIAL PRIMARY KEY,
    position_id INTEGER,                          -- Optional: link to position
    token_id INTEGER NOT NULL,                    -- Foreign key to tokens
    trade_type VARCHAR(10) NOT NULL,              -- 'buy' or 'sell'
    
    -- Execution details
    price DOUBLE PRECISION NOT NULL,              -- Execution price
    quantity DOUBLE PRECISION NOT NULL,           -- Quantity traded
    value_usdc DOUBLE PRECISION NOT NULL,         -- Trade value in USDC
    fee_usdc DOUBLE PRECISION NOT NULL DEFAULT 0, -- Trading fee paid
    slippage_bps INTEGER,                         -- Slippage in basis points
    
    -- DEX information
    dex_name VARCHAR(20),                         -- 'jupiter', 'orca', etc.
    tx_hash VARCHAR(88) NOT NULL,                 -- Solana transaction hash
    block_number BIGINT,                          -- Block number
    
    -- Timing
    execution_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processing_time_ms INTEGER,                   -- Time to execute trade
    
    -- Vault-specific fields (Phase 3.2 enhancement)
    signal_confidence DECIMAL(5,2),               -- Model confidence score (0-100)
    model_version VARCHAR(50),                    -- Model version used for signal
    signal_strength VARCHAR(20),                  -- 'STRONG', 'MODERATE', 'WEAK'
    predicted_change_pct DECIMAL(8,4),            -- Predicted price change %
    cycle_timestamp TIMESTAMPTZ,                  -- Portfolio cycle timestamp
    jupiter_operation_id INTEGER,                 -- Link to jupiter_operations table
    
    -- Trade verification fields (Phase 3.3 enhancement)
    execution_status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'confirmed', 'failed', 'timeout'
    confirmed_at TIMESTAMPTZ,                     -- When trade was verified on-chain
    actual_output_amount DECIMAL(20,8),           -- Actual amount received from swap
    execution_error TEXT,                         -- Error details if verification failed
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT fk_trades_position FOREIGN KEY (position_id) REFERENCES positions(position_id),
    CONSTRAINT fk_trades_token FOREIGN KEY (token_id) REFERENCES tokens(token_id),
    CONSTRAINT check_trade_type CHECK (trade_type IN ('buy', 'sell')),
    CONSTRAINT check_trade_amounts CHECK (price > 0 AND quantity > 0 AND value_usdc > 0),
    CONSTRAINT check_signal_confidence CHECK (signal_confidence IS NULL OR (signal_confidence >= 0 AND signal_confidence <= 100)),
    CONSTRAINT check_signal_strength CHECK (signal_strength IS NULL OR signal_strength IN ('STRONG', 'MODERATE', 'WEAK')),
    CONSTRAINT check_execution_status CHECK (execution_status IN ('pending', 'confirmed', 'failed', 'timeout'))
);

-- Create indexes for trades
CREATE INDEX IF NOT EXISTS idx_trades_token_time ON trades(token_id, execution_time DESC);
CREATE INDEX IF NOT EXISTS idx_trades_position ON trades(position_id);
CREATE INDEX IF NOT EXISTS idx_trades_tx_hash ON trades(tx_hash);
CREATE INDEX IF NOT EXISTS idx_trades_execution_time ON trades(execution_time DESC);
-- Vault-specific indexes
CREATE INDEX IF NOT EXISTS idx_trades_cycle_timestamp ON trades(cycle_timestamp DESC) WHERE cycle_timestamp IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trades_model_version ON trades(model_version) WHERE model_version IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trades_signal_confidence ON trades(signal_confidence DESC) WHERE signal_confidence IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trades_jupiter_operation ON trades(jupiter_operation_id) WHERE jupiter_operation_id IS NOT NULL;
-- Trade verification indexes
CREATE INDEX IF NOT EXISTS idx_trades_execution_status ON trades(execution_status, execution_time DESC);
CREATE INDEX IF NOT EXISTS idx_trades_pending_verification ON trades(execution_time DESC) WHERE execution_status = 'pending' OR execution_status IS NULL;

-- ===========================================================================
-- MODEL PREDICTIONS TABLE
-- ===========================================================================

CREATE TABLE IF NOT EXISTS model_predictions (
    prediction_id SERIAL PRIMARY KEY,
    token_id INTEGER NOT NULL,                    -- Foreign key to tokens
    model_name VARCHAR(50) NOT NULL,              -- 'FastDQN_SOL', etc.
    model_version VARCHAR(50) NOT NULL,           -- Model version
    
    -- Prediction details
    prediction_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prediction_action VARCHAR(10) NOT NULL,       -- 'buy', 'sell', 'hold'
    confidence_score DOUBLE PRECISION NOT NULL,   -- Model confidence (0-1)
    predicted_price_change DOUBLE PRECISION,      -- Expected price change %
    prediction_horizon_minutes INTEGER,           -- Prediction timeframe
    
    -- Model input features (JSON for flexibility)
    input_features JSONB,                         -- Feature vector used
    
    -- Validation (filled later)
    actual_outcome VARCHAR(10),                   -- Actual result after time
    outcome_accuracy DOUBLE PRECISION,            -- How accurate was prediction
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT fk_predictions_token FOREIGN KEY (token_id) REFERENCES tokens(token_id),
    CONSTRAINT check_prediction_action CHECK (prediction_action IN ('buy', 'sell', 'hold')),
    CONSTRAINT check_confidence_score CHECK (confidence_score >= 0 AND confidence_score <= 1)
);

-- Create indexes for model predictions
CREATE INDEX IF NOT EXISTS idx_predictions_token_time ON model_predictions(token_id, prediction_time DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_model ON model_predictions(model_name, model_version);
CREATE INDEX IF NOT EXISTS idx_predictions_confidence ON model_predictions(confidence_score);

-- ===========================================================================
-- SOCIAL DATA TABLE (Daily social metrics from LunarCrush)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS social_data (
    time TIMESTAMPTZ NOT NULL,                    -- Data timestamp (hourly)
    token_id INTEGER NOT NULL,                    -- Foreign key to tokens
    
    -- Core social metrics from LunarCrush (hourly data)
    sentiment DECIMAL(5,2),                       -- Sentiment score (0-100)
    galaxy_score DECIMAL(5,2),                    -- LunarCrush galaxy score
    alt_rank INTEGER,                             -- Alternative rank
    social_dominance DECIMAL(8,4),                -- Social dominance percentage
    interactions BIGINT,                          -- Hourly interactions count
    
    -- Social engagement metrics (hourly data)
    contributors_active INTEGER,                  -- Active contributors this hour
    contributors_created INTEGER,                 -- New contributors this hour
    posts_active INTEGER,                         -- Active posts this hour
    posts_created INTEGER,                        -- New posts created this hour
    spam INTEGER,                                 -- Spam posts this hour
    
    -- Market metrics included in social data
    market_dominance DECIMAL(8,4),                -- Market dominance percentage
    market_cap DECIMAL(20,2),                     -- Market capitalization
    circulating_supply DECIMAL(20,2),             -- Circulating supply
    close_price DECIMAL(20,8),                    -- Closing price for this hour
    open_price DECIMAL(20,8),                     -- Opening price for this hour
    high_price DECIMAL(20,8),                     -- Highest price this hour
    low_price DECIMAL(20,8),                      -- Lowest price this hour
    volume_24h DECIMAL(20,2),                     -- 24h trading volume (rolling)
    
    -- Data source tracking
    data_source VARCHAR(20) DEFAULT 'lunarcrush', -- Data source
    lunarcrush_id INTEGER,                        -- LunarCrush internal ID used
    api_fetch_time TIMESTAMPTZ DEFAULT NOW(),     -- When data was fetched
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT fk_social_data_token FOREIGN KEY (token_id) REFERENCES tokens(token_id),
    CONSTRAINT unique_social_data_time_token UNIQUE (time, token_id)
);

-- Convert to hypertable with daily chunks (better for daily social data)
SELECT create_hypertable('social_data', 'time', chunk_time_interval => INTERVAL '1 week', if_not_exists => TRUE);

-- Create indexes for social data
CREATE INDEX IF NOT EXISTS idx_social_data_token_time ON social_data (token_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_social_data_sentiment ON social_data (sentiment) WHERE sentiment IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_social_data_galaxy_score ON social_data (galaxy_score) WHERE galaxy_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_social_data_lunarcrush_id ON social_data (lunarcrush_id) WHERE lunarcrush_id IS NOT NULL;

-- Enable compression for older social data
ALTER TABLE social_data SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'token_id'
);

-- Compress social data older than 30 days
SELECT add_compression_policy('social_data', INTERVAL '30 days', if_not_exists => TRUE);

-- Retention policy (keep 2 years of social data)
SELECT add_retention_policy('social_data', INTERVAL '2 years', if_not_exists => TRUE);

-- ===========================================================================
-- MARKET EVENTS TABLE (For transaction/orderbook data)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS market_events (
    event_time TIMESTAMPTZ NOT NULL,              -- Partitioning column (MUST be first for TimescaleDB)
    token_id INTEGER NOT NULL,                    -- Foreign key to tokens
    event_type TEXT NOT NULL,                     -- 'transaction', 'trade', 'whale_move', etc.
    event_data JSONB NOT NULL,                    -- Event details (flexible structure)
    
    -- Size/impact indicators
    size_usd DECIMAL(20,8),                       -- Event size in USD
    impact_score DECIMAL(8,4),                    -- Market impact score (0-1)
    
    -- Source information
    source TEXT DEFAULT 'birdeye',                -- Data source identifier
    raw_data JSONB,                               -- Raw event data for debugging
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT fk_market_events_token FOREIGN KEY (token_id) REFERENCES tokens(token_id),
    CONSTRAINT check_impact_score CHECK (impact_score IS NULL OR (impact_score >= 0 AND impact_score <= 1))
);

-- Convert to hypertable for scalability with HOURLY chunks (optimal for large cap tokens)
SELECT create_hypertable('market_events', 'event_time', chunk_time_interval => INTERVAL '1 hour', if_not_exists => TRUE);

-- Create indexes for market events
CREATE INDEX IF NOT EXISTS idx_market_events_token_time ON market_events(token_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_market_events_type ON market_events(event_type, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_market_events_size ON market_events(size_usd DESC) WHERE size_usd IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_market_events_source ON market_events(source, event_time DESC);

-- Enable compression for market events (compress old data to save space)
ALTER TABLE market_events SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'token_id,event_type,source',
    timescaledb.compress_orderby = 'event_time DESC'
);

-- Compress market events after 1 day (keeps recent data uncompressed for fast access)
SELECT add_compression_policy('market_events', INTERVAL '1 day', if_not_exists => TRUE);

-- ===========================================================================
-- SYSTEM HEALTH TABLE
-- ===========================================================================

CREATE TABLE IF NOT EXISTS system_health (
    check_time TIMESTAMPTZ NOT NULL,              -- Partitioning column (MUST be first for TimescaleDB)
    component TEXT NOT NULL,                      -- 'websocket', 'database', 'model', etc.
    status TEXT NOT NULL,                         -- 'healthy', 'degraded', 'down'
    
    -- Metrics
    response_time_ms INTEGER,                     -- Response time in milliseconds
    error_count INTEGER DEFAULT 0,               -- Error count in period
    success_rate DECIMAL(5,2),                   -- Success rate percentage (0-100)
    
    -- Details
    details JSONB,                                -- Additional health info
    error_message TEXT,                           -- Last error message
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT check_health_status CHECK (status IN ('healthy', 'degraded', 'down')),
    CONSTRAINT check_success_rate CHECK (success_rate IS NULL OR (success_rate >= 0 AND success_rate <= 100))
);

-- Convert to hypertable
SELECT create_hypertable('system_health', 'check_time', chunk_time_interval => INTERVAL '1 hour', if_not_exists => TRUE);

-- Create indexes for system health
CREATE INDEX IF NOT EXISTS idx_system_health_component ON system_health(component, check_time DESC);
CREATE INDEX IF NOT EXISTS idx_system_health_status ON system_health(status, check_time DESC);

-- Auto-compress and retain system health data
ALTER TABLE system_health SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'component,status',
    timescaledb.compress_orderby = 'check_time DESC'
);
SELECT add_compression_policy('system_health', INTERVAL '1 day', if_not_exists => TRUE);
SELECT add_retention_policy('system_health', INTERVAL '30 days', if_not_exists => TRUE);

-- ===========================================================================
-- VAULT TRADING TABLES (Phase 3.2 Enhancement)
-- ===========================================================================

-- Portfolio Cycles Table - Track hourly trading cycles
CREATE TABLE IF NOT EXISTS portfolio_cycles (
    cycle_id SERIAL,
    cycle_timestamp TIMESTAMPTZ NOT NULL,         -- Cycle start time (partitioning column)
    
    -- Composite primary key including partitioning column for TimescaleDB
    PRIMARY KEY (cycle_id, cycle_timestamp),
    
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

-- Create indexes for portfolio cycles
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

-- Jupiter Operations Table - Track DEX interactions
CREATE TABLE IF NOT EXISTS jupiter_operations (
    operation_id SERIAL,
    operation_timestamp TIMESTAMPTZ NOT NULL,     -- Operation time (partitioning column)
    
    -- Composite primary key including partitioning column for TimescaleDB
    PRIMARY KEY (operation_id, operation_timestamp),
    
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

-- Create indexes for jupiter operations
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

-- Emergency Events Table - Track risk management events
CREATE TABLE IF NOT EXISTS emergency_events (
    event_id SERIAL,
    event_timestamp TIMESTAMPTZ NOT NULL,         -- Event time (partitioning column)
    
    -- Composite primary key including partitioning column for TimescaleDB
    PRIMARY KEY (event_id, event_timestamp),
    
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

-- Create indexes for emergency events
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
-- VALIDATION TRIGGERS (Create after all tables exist)
-- ===========================================================================

-- Apply validation triggers to all tables with token_id foreign keys
CREATE TRIGGER validate_ohlcv_token 
    BEFORE INSERT OR UPDATE ON ohlcv
    FOR EACH ROW EXECUTE FUNCTION validate_token_reference();

CREATE TRIGGER validate_positions_token 
    BEFORE INSERT OR UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION validate_token_reference();

CREATE TRIGGER validate_trades_token 
    BEFORE INSERT OR UPDATE ON trades
    FOR EACH ROW EXECUTE FUNCTION validate_token_reference();

CREATE TRIGGER validate_predictions_token 
    BEFORE INSERT OR UPDATE ON model_predictions
    FOR EACH ROW EXECUTE FUNCTION validate_token_reference();

CREATE TRIGGER validate_market_events_token 
    BEFORE INSERT OR UPDATE ON market_events
    FOR EACH ROW EXECUTE FUNCTION validate_token_reference();

CREATE TRIGGER validate_social_data_token 
    BEFORE INSERT OR UPDATE ON social_data
    FOR EACH ROW EXECUTE FUNCTION validate_token_reference();

-- Validation triggers for new vault trading tables
CREATE TRIGGER validate_emergency_events_token 
    BEFORE INSERT OR UPDATE ON emergency_events
    FOR EACH ROW EXECUTE FUNCTION validate_token_reference();

-- ===========================================================================
-- CONTINUOUS AGGREGATES (Materialized Views)
-- ===========================================================================

-- 1-hour OHLCV aggregated from minute data
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_1h
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 hour', time) AS bucket,
    token_id,
    resolution,
    first(open, time) as open,
    max(high) as high,
    min(low) as low,
    last(close, time) as close,
    sum(volume) as volume,
    sum(volume_usd) as volume_usd,
    sum(trades_count) as trades_count
FROM ohlcv 
WHERE resolution = '1m'
GROUP BY bucket, token_id, resolution;

-- Auto-refresh the 1-hour view (fixed time windows)
SELECT add_continuous_aggregate_policy('ohlcv_1h',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

-- Market events hourly summary (using hypertable)
CREATE MATERIALIZED VIEW IF NOT EXISTS market_events_hourly
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 hour', event_time) AS hour,
    token_id,
    event_type,
    count(*) as event_count,
    avg(size_usd) as avg_size_usd,
    max(size_usd) as max_size_usd,
    sum(size_usd) as total_volume_usd
FROM market_events
GROUP BY hour, token_id, event_type;

-- Auto-refresh market events summary
SELECT add_continuous_aggregate_policy('market_events_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

-- Vault Trading Performance Hourly View (regular materialized view since trades is not a hypertable)
CREATE MATERIALIZED VIEW IF NOT EXISTS trading_performance_hourly AS
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

-- Portfolio Risk Hourly View
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

-- Emergency Events Daily View
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
-- FUNCTIONS AND TRIGGERS
-- ===========================================================================

-- Function to update timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at (drop existing first to avoid conflicts)
DO $$
BEGIN
    DROP TRIGGER IF EXISTS update_tokens_updated_at ON tokens;
    CREATE TRIGGER update_tokens_updated_at BEFORE UPDATE ON tokens
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
EXCEPTION WHEN OTHERS THEN
    -- Ignore errors if trigger doesn't exist
    NULL;
END $$;

DO $$
BEGIN
    DROP TRIGGER IF EXISTS update_positions_updated_at ON positions;
    CREATE TRIGGER update_positions_updated_at BEFORE UPDATE ON positions
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
EXCEPTION WHEN OTHERS THEN
    -- Ignore errors if trigger doesn't exist
    NULL;
END $$;

-- Function to calculate unrealized P&L
CREATE OR REPLACE FUNCTION calculate_unrealized_pnl(
    position_row positions,
    current_price DOUBLE PRECISION
) RETURNS DOUBLE PRECISION AS $$
BEGIN
    IF position_row.status != 'open' THEN
        RETURN 0;
    END IF;
    
    IF position_row.position_type = 'long' THEN
        RETURN (current_price - position_row.entry_price) * position_row.entry_quantity;
    ELSE
        RETURN (position_row.entry_price - current_price) * position_row.entry_quantity;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- ===========================================================================
-- VAULT TRADING HELPER FUNCTIONS (Phase 3.2 Enhancement)
-- ===========================================================================

-- Function to get portfolio performance summary
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

-- Function to get trading performance by token
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

-- Function to get emergency events summary
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
-- INITIAL DATA & TOKEN INITIALIZATION
-- ===========================================================================

-- NOTE: Tokens will be automatically added from TRACKED_TOKENS environment variable
-- No hardcoded tokens - user controls what gets added via .env configuration

-- Create a view for easy token management
CREATE OR REPLACE VIEW token_status AS
SELECT 
    token_id,
    address,
    symbol,
    name,
    decimals,
    is_active,
    trading_enabled,
    metadata_verified,
    social_data_available,
    lunarcrush_id,
    lunarcrush_symbol,
    lunarcrush_topic,
    last_api_update,
    last_social_update,
    created_at,
    CASE 
        WHEN NOT metadata_verified THEN 'missing_metadata'
        WHEN NOT social_data_available THEN 'missing_social_mapping'
        WHEN NOT trading_enabled THEN 'metadata_only'
        WHEN NOT is_active THEN 'inactive'
        ELSE 'ready'
    END as status
FROM tokens
ORDER BY trading_enabled DESC, social_data_available DESC, metadata_verified DESC, symbol;

-- Function to get token ID safely (for use in scripts)
CREATE OR REPLACE FUNCTION get_token_id_by_address(p_address VARCHAR(44))
RETURNS INTEGER AS $$
DECLARE
    result_id INTEGER;
BEGIN
    SELECT token_id INTO result_id FROM tokens WHERE address = p_address;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Token with address % not found. Use get_or_create_token() first.', p_address;
    END IF;
    
    RETURN result_id;
END;
$$ LANGUAGE plpgsql;

-- Function to get token ID safely by symbol (for use in scripts)
CREATE OR REPLACE FUNCTION get_token_id_by_symbol(p_symbol VARCHAR(20))
RETURNS INTEGER AS $$
DECLARE
    result_id INTEGER;
    token_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO token_count FROM tokens WHERE symbol = p_symbol;
    
    IF token_count = 0 THEN
        RAISE EXCEPTION 'Token with symbol % not found.', p_symbol;
    END IF;
    
    IF token_count > 1 THEN
        RAISE EXCEPTION 'Multiple tokens found with symbol %. Use address instead.', p_symbol;
    END IF;
    
    SELECT token_id INTO result_id FROM tokens WHERE symbol = p_symbol LIMIT 1;
    
    RETURN result_id;
END;
$$ LANGUAGE plpgsql;

-- Initialize tracked tokens from environment (if configured)
-- This will be called automatically but can also be run manually
DO $$
DECLARE
    init_result JSONB;
BEGIN
    -- Try to initialize tracked tokens from environment
    BEGIN
        SELECT initialize_tracked_tokens() INTO init_result;
        
        -- Log the result
        INSERT INTO system_health (check_time, component, status, details) VALUES (
            NOW(),
            'tracked_tokens_init',
            'healthy',
            jsonb_build_object(
                'auto_init_result', init_result,
                'message', 'Automatic token initialization completed'
            )
        );
        
    EXCEPTION WHEN others THEN
        -- Log the error but don't fail the entire initialization
        INSERT INTO system_health (check_time, component, status, details) VALUES (
            NOW(),
            'tracked_tokens_init',
            'degraded',
            jsonb_build_object(
                'error', SQLERRM,
                'message', 'Auto-initialization failed - tokens can be initialized manually'
            )
        );
    END;
END $$;

-- ===========================================================================
-- VIEWS FOR COMMON QUERIES
-- ===========================================================================

-- Latest prices view
CREATE OR REPLACE VIEW latest_prices AS
SELECT DISTINCT ON (o.token_id) 
    t.symbol,
    t.address,
    o.close as price,
    o.volume_usd,
    o.time as last_update
FROM ohlcv o
JOIN tokens t ON o.token_id = t.token_id
WHERE o.resolution = '1m'
ORDER BY o.token_id, o.time DESC;

-- Open positions view
CREATE OR REPLACE VIEW open_positions AS
SELECT 
    p.*,
    t.symbol,
    t.address,
    lp.price as current_price,
    calculate_unrealized_pnl(p, lp.price) as current_unrealized_pnl
FROM positions p
JOIN tokens t ON p.token_id = t.token_id
LEFT JOIN latest_prices lp ON t.symbol = lp.symbol
WHERE p.status = 'open';

-- Performance summary view
CREATE OR REPLACE VIEW performance_summary AS
SELECT 
    t.symbol,
    COUNT(p.position_id) as total_positions,
    COUNT(CASE WHEN p.status = 'open' THEN 1 END) as open_positions,
    SUM(CASE WHEN p.status = 'closed' THEN p.realized_pnl_usdc ELSE 0 END) as total_realized_pnl,
    SUM(CASE WHEN p.status = 'open' THEN calculate_unrealized_pnl(p, lp.price) ELSE 0 END) as total_unrealized_pnl,
    SUM(p.fees_paid_usdc) as total_fees,
    AVG(CASE WHEN p.status = 'closed' AND p.realized_pnl_usdc > 0 THEN 1.0 ELSE 0.0 END) as win_rate
FROM positions p
JOIN tokens t ON p.token_id = t.token_id
LEFT JOIN latest_prices lp ON t.symbol = lp.symbol
GROUP BY t.symbol;

-- ===========================================================================
-- GRANTS AND PERMISSIONS
-- ===========================================================================

-- Grant permissions to development user (calvin_prod only exists in production)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO calvin_dev;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO calvin_dev;

-- Grant access to views
GRANT SELECT ON latest_prices TO calvin_dev;
GRANT SELECT ON open_positions TO calvin_dev;
GRANT SELECT ON performance_summary TO calvin_dev;
GRANT SELECT ON token_status TO calvin_dev;

-- Grant execute permissions on token management functions
GRANT EXECUTE ON FUNCTION get_or_create_token(VARCHAR, VARCHAR, VARCHAR, INTEGER) TO calvin_dev;
GRANT EXECUTE ON FUNCTION get_token_id_by_address(VARCHAR) TO calvin_dev;
GRANT EXECUTE ON FUNCTION get_token_id_by_symbol(VARCHAR) TO calvin_dev;
GRANT EXECUTE ON FUNCTION initialize_tracked_tokens() TO calvin_dev;

-- Grant execute permissions on vault trading functions
GRANT EXECUTE ON FUNCTION get_portfolio_performance_summary(INTEGER) TO calvin_dev;
GRANT EXECUTE ON FUNCTION get_trading_performance_by_token(INTEGER) TO calvin_dev;
GRANT EXECUTE ON FUNCTION get_emergency_events_summary(INTEGER) TO calvin_dev;

-- ===========================================================================
-- COMPLETION & SETUP INSTRUCTIONS
-- ===========================================================================

-- Log successful initialization with explicit timestamp
INSERT INTO system_health (check_time, component, status, details) VALUES (
    NOW(),
    'database_init', 
    'healthy', 
    jsonb_build_object(
        'message', 'Calvin AI database initialized successfully with vault trading enhancements (Phase 3.2)',
        'tables_created', 12,
        'views_created', 9,
        'functions_created', 9,
        'triggers_created', 7,
        'hypertables', ARRAY['ohlcv', 'social_data', 'market_events', 'system_health', 'portfolio_cycles', 'jupiter_operations', 'emergency_events'],
        'vault_enhancements', jsonb_build_object(
            'trades_table_enhanced', 'Added 6 vault-specific columns for signal tracking',
            'portfolio_cycles', 'Complete hourly trading cycle tracking with performance metrics',
            'jupiter_operations', 'DEX interaction tracking with route and execution details',
            'emergency_events', 'Risk management event tracking with response actions',
            'materialized_views', ARRAY['trading_performance_hourly', 'portfolio_risk_hourly', 'emergency_events_daily'],
            'helper_functions', ARRAY['get_portfolio_performance_summary', 'get_trading_performance_by_token', 'get_emergency_events_summary']
        ),
        'features', ARRAY['auto_token_management', 'api_integration', 'cross_validation', 'metadata_sync', 'dedicated_social_table', 'vault_trading_tracking', 'portfolio_cycle_management', 'jupiter_integration', 'emergency_monitoring'],
        'data_separation', jsonb_build_object(
            'social_data', 'Weekly chunks for daily social metrics from LunarCrush',
            'market_events', 'Daily chunks for high-frequency transaction/orderbook data',
            'ohlcv', 'Daily chunks for price/volume time series',
            'portfolio_cycles', 'Weekly chunks for hourly trading cycles',
            'jupiter_operations', 'Daily chunks for DEX operations',
            'emergency_events', 'Weekly chunks for risk management events'
        )
    )
);

-- Instructions for completing the setup
INSERT INTO system_health (check_time, component, status, details) VALUES (
    NOW(),
    'setup_instructions',
    'healthy',
    jsonb_build_object(
        'message', 'Database initialization complete. Follow these steps to activate token management',
        'required_env_vars', jsonb_build_object(
            'TRACKED_TOKENS', 'Comma-separated list of token addresses to track',
            'BIRDEYE_API_KEY', 'Your BirdEye API key for metadata fetching'
        ),
        'setup_commands', ARRAY[
            'Add to .env file: TRACKED_TOKENS=address1,address2,address3',
            'Add to .env file: BIRDEYE_API_KEY=your_api_key_here',
            'Set database config: ALTER DATABASE calvin_trading_dev SET app.tracked_tokens = ''address1,address2,address3'';',
            'Set database config: ALTER DATABASE calvin_trading_dev SET app.birdeye_api_key = ''your_api_key'';',
            'Run manually: SELECT initialize_tracked_tokens();',
            'Check status: SELECT * FROM token_status;'
        ],
        'auto_features', ARRAY[
            'get_or_create_token() prevents duplicate token IDs',
            'Triggers validate all token references',
            'API integration fetches metadata automatically',
            'Cross-validation prevents inconsistencies'
        ]
    )
); 