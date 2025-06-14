-- ===========================================================================
-- Fix Existing Schema Migration
-- Renames existing columns to match the corrected schema
-- ===========================================================================

-- Fix portfolio_cycles table column names
DO $$
BEGIN
    -- Check if old columns exist and rename them
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'status') THEN
        ALTER TABLE portfolio_cycles RENAME COLUMN status TO cycle_status;
        RAISE NOTICE 'Renamed portfolio_cycles.status to cycle_status';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'cycle_duration_seconds') THEN
        ALTER TABLE portfolio_cycles DROP COLUMN cycle_duration_seconds;
        RAISE NOTICE 'Dropped portfolio_cycles.cycle_duration_seconds (replaced by total_cycle_duration_ms)';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'portfolio_value') THEN
        ALTER TABLE portfolio_cycles RENAME COLUMN portfolio_value TO total_portfolio_value_usdc;
        RAISE NOTICE 'Renamed portfolio_cycles.portfolio_value to total_portfolio_value_usdc';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'max_single_position_pct') THEN
        ALTER TABLE portfolio_cycles RENAME COLUMN max_single_position_pct TO max_position_size_pct;
        RAISE NOTICE 'Renamed portfolio_cycles.max_single_position_pct to max_position_size_pct';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'cash_allocation_pct') THEN
        ALTER TABLE portfolio_cycles DROP COLUMN cash_allocation_pct;
        RAISE NOTICE 'Dropped portfolio_cycles.cash_allocation_pct (replaced by available_cash_usdc)';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'total_exposure_pct') THEN
        ALTER TABLE portfolio_cycles DROP COLUMN total_exposure_pct;
        RAISE NOTICE 'Dropped portfolio_cycles.total_exposure_pct (not needed)';
    END IF;
    
    -- Add missing columns
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'tokens_analyzed') THEN
        ALTER TABLE portfolio_cycles ADD COLUMN tokens_analyzed INTEGER NOT NULL DEFAULT 0;
        RAISE NOTICE 'Added portfolio_cycles.tokens_analyzed';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'correlation_risk') THEN
        ALTER TABLE portfolio_cycles ADD COLUMN correlation_risk DECIMAL(5,2);
        RAISE NOTICE 'Added portfolio_cycles.correlation_risk';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'available_cash_usdc') THEN
        ALTER TABLE portfolio_cycles ADD COLUMN available_cash_usdc DECIMAL(20,8);
        RAISE NOTICE 'Added portfolio_cycles.available_cash_usdc';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'data_fetch_duration_ms') THEN
        ALTER TABLE portfolio_cycles ADD COLUMN data_fetch_duration_ms INTEGER;
        RAISE NOTICE 'Added portfolio_cycles.data_fetch_duration_ms';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'inference_duration_ms') THEN
        ALTER TABLE portfolio_cycles ADD COLUMN inference_duration_ms INTEGER;
        RAISE NOTICE 'Added portfolio_cycles.inference_duration_ms';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'signal_processing_duration_ms') THEN
        ALTER TABLE portfolio_cycles ADD COLUMN signal_processing_duration_ms INTEGER;
        RAISE NOTICE 'Added portfolio_cycles.signal_processing_duration_ms';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'trade_execution_duration_ms') THEN
        ALTER TABLE portfolio_cycles ADD COLUMN trade_execution_duration_ms INTEGER;
        RAISE NOTICE 'Added portfolio_cycles.trade_execution_duration_ms';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'portfolio_cycles' AND column_name = 'total_cycle_duration_ms') THEN
        ALTER TABLE portfolio_cycles ADD COLUMN total_cycle_duration_ms INTEGER;
        RAISE NOTICE 'Added portfolio_cycles.total_cycle_duration_ms';
    END IF;
END $$;

-- Fix jupiter_operations table column names
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jupiter_operations' AND column_name = 'operation_time') THEN
        ALTER TABLE jupiter_operations RENAME COLUMN operation_time TO operation_timestamp;
        RAISE NOTICE 'Renamed jupiter_operations.operation_time to operation_timestamp';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jupiter_operations' AND column_name = 'tx_signature') THEN
        ALTER TABLE jupiter_operations RENAME COLUMN tx_signature TO tx_hash;
        RAISE NOTICE 'Renamed jupiter_operations.tx_signature to tx_hash';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jupiter_operations' AND column_name = 'execution_time_ms') THEN
        ALTER TABLE jupiter_operations RENAME COLUMN execution_time_ms TO quote_response_time_ms;
        RAISE NOTICE 'Renamed jupiter_operations.execution_time_ms to quote_response_time_ms';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jupiter_operations' AND column_name = 'block_number') THEN
        ALTER TABLE jupiter_operations DROP COLUMN block_number;
        RAISE NOTICE 'Dropped jupiter_operations.block_number (not needed)';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jupiter_operations' AND column_name = 'trade_id') THEN
        ALTER TABLE jupiter_operations DROP COLUMN trade_id;
        RAISE NOTICE 'Dropped jupiter_operations.trade_id (trades link to jupiter via jupiter_operation_id)';
    END IF;
    
    -- Add missing columns
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jupiter_operations' AND column_name = 'actual_output_amount') THEN
        ALTER TABLE jupiter_operations ADD COLUMN actual_output_amount BIGINT;
        RAISE NOTICE 'Added jupiter_operations.actual_output_amount';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jupiter_operations' AND column_name = 'fee_amount') THEN
        ALTER TABLE jupiter_operations ADD COLUMN fee_amount BIGINT;
        RAISE NOTICE 'Added jupiter_operations.fee_amount';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jupiter_operations' AND column_name = 'fee_mint') THEN
        ALTER TABLE jupiter_operations ADD COLUMN fee_mint VARCHAR(44);
        RAISE NOTICE 'Added jupiter_operations.fee_mint';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jupiter_operations' AND column_name = 'market_infos') THEN
        ALTER TABLE jupiter_operations ADD COLUMN market_infos JSONB;
        RAISE NOTICE 'Added jupiter_operations.market_infos';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'jupiter_operations' AND column_name = 'swap_execution_time_ms') THEN
        ALTER TABLE jupiter_operations ADD COLUMN swap_execution_time_ms INTEGER;
        RAISE NOTICE 'Added jupiter_operations.swap_execution_time_ms';
    END IF;
END $$;

-- Fix emergency_events table column names
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'event_time') THEN
        ALTER TABLE emergency_events RENAME COLUMN event_time TO event_timestamp;
        RAISE NOTICE 'Renamed emergency_events.event_time to event_timestamp';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'trigger_value') THEN
        ALTER TABLE emergency_events DROP COLUMN trigger_value;
        RAISE NOTICE 'Dropped emergency_events.trigger_value (moved to trigger_condition)';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'threshold_value') THEN
        ALTER TABLE emergency_events DROP COLUMN threshold_value;
        RAISE NOTICE 'Dropped emergency_events.threshold_value (moved to trigger_condition)';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'trigger_type') THEN
        ALTER TABLE emergency_events DROP COLUMN trigger_type;
        RAISE NOTICE 'Dropped emergency_events.trigger_type (moved to trigger_condition)';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'position_size') THEN
        ALTER TABLE emergency_events DROP COLUMN position_size;
        RAISE NOTICE 'Dropped emergency_events.position_size (moved to current_metrics)';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'portfolio_impact') THEN
        ALTER TABLE emergency_events RENAME COLUMN portfolio_impact TO total_value_affected_usdc;
        RAISE NOTICE 'Renamed emergency_events.portfolio_impact to total_value_affected_usdc';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'position_pnl') THEN
        ALTER TABLE emergency_events DROP COLUMN position_pnl;
        RAISE NOTICE 'Dropped emergency_events.position_pnl (moved to current_metrics)';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'tx_signature') THEN
        ALTER TABLE emergency_events DROP COLUMN tx_signature;
        RAISE NOTICE 'Dropped emergency_events.tx_signature (replaced by tx_hashes array)';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'notes') THEN
        ALTER TABLE emergency_events DROP COLUMN notes;
        RAISE NOTICE 'Dropped emergency_events.notes (moved to current_metrics)';
    END IF;
    
    -- Add missing columns
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'severity') THEN
        ALTER TABLE emergency_events ADD COLUMN severity VARCHAR(20) NOT NULL DEFAULT 'MEDIUM';
        RAISE NOTICE 'Added emergency_events.severity';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'trigger_condition') THEN
        ALTER TABLE emergency_events ADD COLUMN trigger_condition JSONB NOT NULL DEFAULT '{}';
        RAISE NOTICE 'Added emergency_events.trigger_condition';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'current_metrics') THEN
        ALTER TABLE emergency_events ADD COLUMN current_metrics JSONB;
        RAISE NOTICE 'Added emergency_events.current_metrics';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'threshold_breached') THEN
        ALTER TABLE emergency_events ADD COLUMN threshold_breached JSONB;
        RAISE NOTICE 'Added emergency_events.threshold_breached';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'positions_affected') THEN
        ALTER TABLE emergency_events ADD COLUMN positions_affected INTEGER DEFAULT 0;
        RAISE NOTICE 'Added emergency_events.positions_affected';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'action_successful') THEN
        ALTER TABLE emergency_events ADD COLUMN action_successful BOOLEAN;
        RAISE NOTICE 'Added emergency_events.action_successful';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'execution_time_ms') THEN
        ALTER TABLE emergency_events ADD COLUMN execution_time_ms INTEGER;
        RAISE NOTICE 'Added emergency_events.execution_time_ms';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'tx_hashes') THEN
        ALTER TABLE emergency_events ADD COLUMN tx_hashes TEXT[];
        RAISE NOTICE 'Added emergency_events.tx_hashes';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'resolved_timestamp') THEN
        ALTER TABLE emergency_events ADD COLUMN resolved_timestamp TIMESTAMPTZ;
        RAISE NOTICE 'Added emergency_events.resolved_timestamp';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'emergency_events' AND column_name = 'resolution_method') THEN
        ALTER TABLE emergency_events ADD COLUMN resolution_method VARCHAR(50);
        RAISE NOTICE 'Added emergency_events.resolution_method';
    END IF;
END $$;

-- Now create the missing indexes with correct column names
CREATE INDEX IF NOT EXISTS idx_portfolio_cycles_status ON portfolio_cycles(cycle_status, cycle_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jupiter_operations_timestamp ON jupiter_operations(operation_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jupiter_operations_type ON jupiter_operations(operation_type, operation_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jupiter_operations_input_mint ON jupiter_operations(input_mint, operation_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jupiter_operations_output_mint ON jupiter_operations(output_mint, operation_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jupiter_operations_success ON jupiter_operations(success, operation_timestamp DESC) WHERE success IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jupiter_operations_tx_hash ON jupiter_operations(tx_hash) WHERE tx_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_emergency_events_timestamp ON emergency_events(event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_emergency_events_type ON emergency_events(event_type, event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_emergency_events_severity ON emergency_events(severity, event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_emergency_events_token ON emergency_events(token_id, event_timestamp DESC) WHERE token_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_emergency_events_unresolved ON emergency_events(event_timestamp DESC) WHERE resolved_timestamp IS NULL;

-- Update compression settings with correct column names
ALTER TABLE portfolio_cycles SET (
    timescaledb.compress_segmentby = 'cycle_status,execution_priority'
);

ALTER TABLE jupiter_operations SET (
    timescaledb.compress_orderby = 'operation_timestamp DESC'
);

ALTER TABLE emergency_events SET (
    timescaledb.compress_segmentby = 'event_type,severity',
    timescaledb.compress_orderby = 'event_timestamp DESC'
);

-- Log completion
INSERT INTO system_health (check_time, component, status, details) VALUES (
    NOW(),
    'schema_fix_migration',
    'healthy',
    jsonb_build_object(
        'message', 'Existing schema fixed to match corrected field names',
        'migration_date', NOW()
    )
);

SELECT 'Schema fix migration completed successfully!' AS migration_status; 