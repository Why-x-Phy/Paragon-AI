"""
Trade Executor Event Loop Fix

Fixes the event loop conflict in trade recording operations.
"""

import asyncio
from typing import Optional
from datetime import datetime
from src.utils.logger import log_manager

logger = log_manager.get_logger("trade_executor_fix")


async def record_trade_execution_safe(
    db_manager,
    signal,
    allocation, 
    tx_sig: Optional[str],
    success: bool,
    error: str = None,
    max_slippage_bps: int = 100,
    execution_time_ms: Optional[int] = None,
    trade_type: str = 'buy'  # NEW: Support both buy and sell
) -> Optional[int]:
    """
    Thread-safe version of _record_trade_execution that handles event loop conflicts.
    
    This function ensures database operations run in the correct event loop context.
    """
    try:
        # Get token info in a thread-safe way
        token_info = None
        
        # Get token info - it's an async method
        token_info = await db_manager.get_token_by_symbol(signal.symbol)
        
        if not token_info:
            logger.error(f"❌ Token not found for symbol: {signal.symbol}")
            return None
        
        # Extract token_id - handle both dict and object responses
        if isinstance(token_info, dict):
            token_id = token_info.get('token_id')
        else:
            token_id = getattr(token_info, 'token_id', None)
        
        if not token_id:
            logger.error(f"❌ No token_id found for {signal.symbol}")
            return None
        
        # Create trade data
        from ..database.production_db import TradeData
        
        # Calculate quantity and value based on trade type
        if trade_type == 'buy':
            quantity = allocation.position_value_usdc / signal.current_price if signal.current_price > 0 else 0.0
            value_usdc = allocation.position_value_usdc if allocation else 0.0
        else:
            # For sells, we need to calculate from position size
            # This is a simplified approach - in practice, we'd get the exact quantity sold
            quantity = 0.0  # Will be updated after verification
            value_usdc = 0.0  # Will be calculated from sell proceeds
        
        trade_data = TradeData(
            token_id=token_id,
            trade_type=trade_type,  # Now supports both 'buy' and 'sell'
            price=signal.current_price,
            quantity=quantity,
            value_usdc=value_usdc,
            fee_usdc=0.0,  # Will be updated after verification
            tx_hash=tx_sig or '',
            execution_time=datetime.utcnow(),
            slippage_bps=max_slippage_bps,
            dex_name='jupiter',
            processing_time_ms=execution_time_ms,
            
            # Vault-specific fields
            signal_confidence=signal.confidence * 100 if signal.confidence <= 1.0 else signal.confidence,
            model_version=signal.model_version,
            signal_strength=(signal.strength.value if hasattr(signal.strength, 'value') else str(signal.strength)).upper(),
            predicted_change_pct=signal.predicted_change_pct,
            cycle_timestamp=datetime.utcnow(),
            jupiter_operation_id=None  # Will be set separately if available
        )
        
        # Record trade in database
        trade_id = None
        if success:
            # Use thread-safe database operation
            try:
                # Try direct call first
                trade_id = await db_manager.record_trade(trade_data)
            except (RuntimeError, Exception) as e:
                if "attached to a different loop" in str(e) or "another operation is in progress" in str(e):
                    # Event loop conflict - create new connection in current loop
                    logger.debug("Event loop conflict detected, creating new DB connection")
                    from ..database.production_db import ProductionDBManager
                    
                    # Create a new DB manager for this event loop
                    temp_db_manager = ProductionDBManager()
                    await temp_db_manager.initialize()
                    
                    try:
                        # Record using the new connection
                        trade_id = await temp_db_manager.record_trade(trade_data)
                    finally:
                        # Clean up temporary connection
                        await temp_db_manager.close()
                else:
                    raise
            
            if trade_id:
                logger.debug(f"✅ Recorded trade {trade_id} in database")
        
        return trade_id
        
    except Exception as e:
        logger.error(f"❌ Failed to record trade execution: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None


def create_thread_safe_executor(original_executor):
    """
    Wraps a VaultTradeExecutor to make it thread-safe by handling event loop conflicts.
    """
    class ThreadSafeVaultTradeExecutor:
        def __init__(self, executor):
            self._executor = executor
            self._thread_local_db_managers = {}
            
        def __getattr__(self, name):
            # Delegate all other attributes to the original executor
            return getattr(self._executor, name)
        
        async def _get_thread_safe_db_manager(self):
            """Get or create a database manager for the current event loop"""
            import threading
            thread_id = threading.current_thread().ident
            
            if thread_id not in self._thread_local_db_managers:
                from ..database.production_db import ProductionDBManager
                db_manager = ProductionDBManager()
                await db_manager.initialize()
                self._thread_local_db_managers[thread_id] = db_manager
                logger.debug(f"Created new DB manager for thread {thread_id}")
            
            return self._thread_local_db_managers[thread_id]
        
        async def _record_trade_execution(self, signal, allocation, tx_sig, success, error=None, trade_type='buy'):
            """Thread-safe version of _record_trade_execution"""
            try:
                # Get thread-safe DB manager
                db_manager = await self._get_thread_safe_db_manager()
                
                # Use the safe recording function
                trade_id = await record_trade_execution_safe(
                    db_manager=db_manager,
                    signal=signal,
                    allocation=allocation,
                    tx_sig=tx_sig,
                    success=success,
                    error=error,
                    max_slippage_bps=self._executor.max_slippage_bps,
                    execution_time_ms=int(self._executor.execution_times[-1]) if self._executor.execution_times else None,
                    trade_type=trade_type  # NEW: Pass trade type
                )
                
                # Update trade history
                if hasattr(self._executor, 'trade_history'):
                    self._executor.trade_history.append({
                        'symbol': signal.symbol,
                        'signal_type': trade_type,  # Now tracks both 'buy' and 'sell'
                        'confidence': signal.confidence,
                        'amount_usdc': allocation.position_value_usdc if allocation else 0,
                        'tx_signature': tx_sig,
                        'success': success,
                        'error': error,
                        'execution_time': datetime.utcnow(),
                        'predicted_change_pct': signal.predicted_change_pct,
                        'model_version': signal.model_version,
                        'trade_id': trade_id,
                        'trade_type': trade_type,  # Explicit trade type tracking
                        'is_sell': trade_type == 'sell'  # Flag for easy filtering
                    })
                
                return trade_id
                
            except Exception as e:
                logger.error(f"❌ Thread-safe trade recording failed: {e}")
                return None
        
        async def cleanup(self):
            """Clean up thread-local database connections"""
            for thread_id, db_manager in self._thread_local_db_managers.items():
                try:
                    await db_manager.close()
                    logger.debug(f"Closed DB manager for thread {thread_id}")
                except Exception as e:
                    logger.error(f"Error closing DB manager for thread {thread_id}: {e}")
            self._thread_local_db_managers.clear()
    
    return ThreadSafeVaultTradeExecutor(original_executor) 