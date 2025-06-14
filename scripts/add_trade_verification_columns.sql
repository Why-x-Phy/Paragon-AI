-- ===========================================================================
-- Trade Verification Enhancement Migration
-- Adds columns to support on-chain trade verification
-- FIXED TO MATCH MAIN SCHEMA EXACTLY
-- ===========================================================================

-- Add execution status tracking columns to trades table (EXACT MATCH TO MAIN SCHEMA)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS execution_status VARCHAR(20) DEFAULT 'pending';
ALTER TABLE trades ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS actual_output_amount DECIMAL(20,8);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS execution_error TEXT;

-- Add constraints for execution status (EXACT MATCH TO MAIN SCHEMA)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'check_execution_status' 
        AND table_name = 'trades'
    ) THEN
        ALTER TABLE trades ADD CONSTRAINT check_execution_status 
            CHECK (execution_status IN ('pending', 'confirmed', 'failed', 'timeout'));
    END IF;
END $$;

-- Add indexes for verification queries (EXACT MATCH TO MAIN SCHEMA)
CREATE INDEX IF NOT EXISTS idx_trades_execution_status ON trades(execution_status, execution_time DESC);
CREATE INDEX IF NOT EXISTS idx_trades_pending_verification ON trades(execution_time DESC) 
    WHERE execution_status = 'pending' OR execution_status IS NULL;

-- Update existing trades to have 'pending' status if they have tx_hash
UPDATE trades 
SET execution_status = 'pending' 
WHERE tx_hash IS NOT NULL 
  AND tx_hash != '' 
  AND execution_status IS NULL;

-- Log the migration
INSERT INTO system_health (check_time, component, status, details) VALUES (
    NOW(),
    'trade_verification_migration',
    'healthy',
    jsonb_build_object(
        'message', 'Trade verification columns added successfully',
        'columns_added', ARRAY['execution_status', 'confirmed_at', 'actual_output_amount', 'execution_error'],
        'indexes_created', ARRAY['idx_trades_execution_status', 'idx_trades_pending_verification'],
        'migration_date', NOW()
    )
); 