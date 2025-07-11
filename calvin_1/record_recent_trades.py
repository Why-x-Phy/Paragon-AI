#!/usr/bin/env python3
"""
Record recent successful trades in the database
Based on Solscan transaction data
"""

import asyncio
import sys
import os
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database.production_db import get_db_manager, TradeData
from src.utils.logger import log_manager

logger = log_manager.get_logger("record_recent_trades")

# Trade data from Solscan screenshots
RECENT_TRADES = [
    {
        "tx_hash": "5Huyeaut1ts23LspSx5meLk2KragiaHsN5PUMDPt3cqEwp2pefypndwACpuCJmrFG2DeQJHVKYZ1Y2M3UXCAQK7T",
        "block": 352624230,
        "timestamp": datetime(2025, 7, 11, 16, 13, 24),  # July 11, 2025 16:13:24 +UTC
        "token_symbol": "$WIF",
        "trade_type": "sell",  # This was a liquidation (sell)
        "usdc_amount": 7378.620662,  # From transaction: 7,378.620662 USDC received
        "token_amount": 7340.161125,  # From transaction: 7,340.161125 WIF sold
        "price": 7378.620662 / 7340.161125  # Calculate price per token (~1.00525 USDC per WIF)
    }
]

async def record_recent_trades():
    """Record the recent trades in the database"""
    try:
        logger.info("Starting to record recent trades...")
        
        # Get database manager
        db_manager = await get_db_manager()
        
        trades_added = 0
        
        for i, trade_info in enumerate(RECENT_TRADES):
            logger.info(f"Recording trade {i+1}/{len(RECENT_TRADES)}: {trade_info['tx_hash'][:12]}...")
            
            try:
                # Get token info from cache or database
                token_info = None
                for token in db_manager._token_cache.values():
                    if token.symbol.upper() == trade_info['token_symbol'].upper():
                        token_info = token
                        break
                
                if not token_info:
                    # Try to get from database or create new token
                    logger.info(f"📌 Token {trade_info['token_symbol']} not in cache, checking database...")
                    
                    # Define token addresses for known tokens
                    token_addresses = {
                        "$WIF": ("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "dogwifhat", 6),
                        "WIF": ("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "dogwifhat", 6),  # Support both
                        "PENGU": ("2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv", "Pudgy Penguins", 6),
                        "POPCAT": ("7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", "Popcat", 9)
                    }
                    
                    if trade_info['token_symbol'].upper() in token_addresses:
                        address, name, decimals = token_addresses[trade_info['token_symbol'].upper()]
                        
                        # Try to add the token to database
                        try:
                            new_token = await db_manager.add_token(
                                address=address,
                                symbol=trade_info['token_symbol'],  # Use exact symbol (e.g., $WIF)
                                name=name,
                                decimals=decimals
                            )
                            logger.info(f"✅ Added {trade_info['token_symbol']} to database")
                            
                            # Get the newly added token from cache
                            token_info = db_manager.get_token_by_address(address)
                            if not token_info:
                                # Try reloading cache
                                await db_manager._load_token_cache()
                                token_info = db_manager.get_token_by_address(address)
                                
                        except Exception as e:
                            logger.error(f"❌ Failed to add token {trade_info['token_symbol']}: {e}")
                            continue
                    else:
                        logger.error(f"❌ Unknown token {trade_info['token_symbol']}, skipping...")
                        continue
                        
                if not token_info:
                    logger.error(f"❌ Still couldn't find token {trade_info['token_symbol']}")
                    continue
                
                # Create trade data
                trade_data = TradeData(
                    token_id=token_info.token_id,
                    trade_type=trade_info.get('trade_type', 'buy'),  # Use trade type from data
                    price=trade_info['price'],
                    quantity=trade_info['token_amount'],
                    value_usdc=trade_info['usdc_amount'],
                    fee_usdc=0.0,  # Will be updated later if needed
                    tx_hash=trade_info['tx_hash'],
                    execution_time=trade_info['timestamp'],
                    slippage_bps=100,  # Default
                    dex_name='jupiter',
                    processing_time_ms=None,
                    
                    # Vault-specific fields
                    signal_confidence=100.0 if trade_info.get('trade_type') == 'sell' else 85.0,  # 100% for manual liquidations
                    model_version="manual_liquidation" if trade_info.get('trade_type') == 'sell' else "v1.0",
                    signal_strength=None if trade_info.get('trade_type') == 'sell' else "STRONG",  # NULL for manual liquidations
                    predicted_change_pct=None,
                    cycle_timestamp=trade_info['timestamp'],
                    jupiter_operation_id=None
                )
                
                # Record in database
                trade_id = await db_manager.record_trade(trade_data)
                logger.info(f"✅ Recorded trade {trade_id}: {trade_info['token_symbol']} - ${trade_info['usdc_amount']:,.2f}")
                logger.info(f"   TX: {trade_info['tx_hash']}")
                trades_added += 1
                
            except Exception as e:
                logger.error(f"❌ Failed to record trade {trade_info['tx_hash']}: {e}")
        
        logger.info(f"✅ Successfully recorded {trades_added}/{len(RECENT_TRADES)} trades")
        return trades_added == len(RECENT_TRADES)
        
    except Exception as e:
        logger.error(f"❌ Failed to record recent trades: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(record_recent_trades())
    if success:
        print("✅ All recent trades recorded successfully")
    else:
        print("❌ Some trades failed to be recorded")
        sys.exit(1) 