"""
Position Sync Utility - Syncs vault token holdings to position manager

Any non-USDC token in the vault IS a position that needs to be tracked.
"""

import asyncio
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass

from ..vault.vault_client import VaultClient
from ..database.production_db import get_db_manager, PositionData
from ..utils.logger import log_manager
from .position_manager import PositionManager

logger = log_manager.get_logger("position_sync")


@dataclass
class Position:
    """Simple position representation for sync purposes"""
    id: Optional[str] = None
    symbol: str = ""
    size: float = 0.0
    average_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    entry_time: datetime = None
    
    def __post_init__(self):
        if self.entry_time is None:
            self.entry_time = datetime.utcnow()
    
    def update_price(self, new_price: float):
        """Update current price and recalculate P&L"""
        self.current_price = new_price
        self.unrealized_pnl = (new_price - self.average_price) * self.size
    
    def get_pnl_percentage(self) -> float:
        """Get P&L percentage"""
        if self.average_price == 0:
            return 0.0
        return ((self.current_price - self.average_price) / self.average_price) * 100


@dataclass
class VaultHolding:
    """Represents a token holding in the vault"""
    token_address: str
    symbol: str
    quantity: float
    current_price: float
    value_usdc: float


async def get_vault_holdings(vault_client: VaultClient) -> List[VaultHolding]:
    """Get all non-USDC token holdings from the vault"""
    holdings = []
    
    try:
        # Get vault state
        vault_state = await vault_client.get_vault_state()
        
        # Get the actual token balances from vault
        # The vault client's _calculate_vault_nav method shows us how to get token accounts
        vault_authority_pda = vault_client._get_vault_authority_pda()
        
        # Get all token accounts for the vault
        from solana.rpc.types import TokenAccountOpts
        from solders.pubkey import Pubkey
        
        token_accounts_response = await vault_client.client.get_token_accounts_by_owner(
            vault_authority_pda,
            TokenAccountOpts(program_id=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"))
        )
        
        if not token_accounts_response or not token_accounts_response.value:
            logger.warning("No token accounts found for vault")
            return holdings
        
        # Get database manager for token info
        db_manager = await get_db_manager()
        
        # Process each token account
        for account_info in token_accounts_response.value:
            try:
                # Get token balance
                balance_response = await vault_client.client.get_token_account_balance(
                    account_info.pubkey
                )
                
                if not balance_response or not balance_response.value:
                    continue
                
                # Get the mint address from account data
                account_data = account_info.account.data
                if len(account_data) < 32:
                    continue
                
                # Extract mint from token account data (first 32 bytes)
                mint_bytes = account_data[:32]
                mint_pubkey = Pubkey(mint_bytes)
                mint_str = str(mint_pubkey)
                
                # Skip USDC
                if mint_str == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":
                    continue
                
                # Get token amount
                token_amount = float(balance_response.value.ui_amount or 0)
                
                if token_amount == 0:
                    continue
                
                # Get token info from database
                token_info = db_manager.get_token_by_address(mint_str)
                if not token_info:
                    logger.warning(f"Token not found in database: {mint_str}")
                    continue
                
                # Get current price
                current_price = await db_manager.get_latest_price(token_info.token_id)
                if not current_price:
                    logger.warning(f"No price data for {token_info.symbol}")
                    current_price = 0.0
                
                # Calculate value
                value_usdc = token_amount * current_price
                
                holding = VaultHolding(
                    token_address=mint_str,
                    symbol=token_info.symbol,
                    quantity=token_amount,
                    current_price=current_price,
                    value_usdc=value_usdc
                )
                
                holdings.append(holding)
                logger.info(f"Found vault holding: {token_info.symbol} - {token_amount:.6f} tokens @ ${current_price:.6f} = ${value_usdc:.2f}")
                
            except Exception as e:
                logger.error(f"Error processing token account: {e}")
                continue
        
        logger.info(f"Total vault holdings found: {len(holdings)} positions")
        return holdings
        
    except Exception as e:
        logger.error(f"Failed to get vault holdings: {e}")
        return holdings


async def sync_vault_to_positions(
    vault_client: VaultClient, 
    position_manager: PositionManager,
    force_sync: bool = False
) -> Dict[str, Position]:
    """
    Sync vault holdings to position manager.
    
    Args:
        vault_client: Initialized vault client
        position_manager: Position manager instance
        force_sync: If True, overwrite existing positions
        
    Returns:
        Dictionary of synced positions
    """
    logger.info("🔄 Starting vault → position manager sync...")
    
    try:
        # Get current vault holdings
        vault_holdings = await get_vault_holdings(vault_client)
        
        if not vault_holdings:
            logger.warning("No vault holdings found to sync")
            return {}
        
        # Get existing positions from position manager
        existing_positions = position_manager.get_active_positions()
        
        synced_positions = {}
        db_manager = await get_db_manager()
        
        for holding in vault_holdings:
            # Get token info
            token_info = db_manager.get_token_by_address(holding.token_address)
            if not token_info:
                logger.warning(f"Token not found in database: {holding.token_address}")
                continue
            
            # Check if position already exists for this token
            existing_pos_id = None
            existing_pos_data = None
            
            # Look through existing positions by token_id
            token_positions = position_manager.get_positions_by_token(token_info.token_id)
            if token_positions and not force_sync:
                logger.info(f"Position already exists for {holding.symbol}, skipping sync")
                # Create a Position object from the existing PositionData
                pos_data = token_positions[0]  # Take the first open position
                position = Position(
                    id=str(pos_data.position_id),
                    symbol=holding.symbol,
                    size=pos_data.entry_quantity,
                    average_price=pos_data.entry_price,
                    current_price=holding.current_price,
                    unrealized_pnl=(holding.current_price - pos_data.entry_price) * pos_data.entry_quantity,
                    entry_time=pos_data.entry_time
                )
                synced_positions[holding.symbol] = position
                continue
            
            # Create or update position
            logger.info(f"Creating position for {holding.symbol}: {holding.quantity:.6f} tokens")
            
            # Query for average buy price
            query = """
            SELECT 
                AVG(price) as avg_price,
                MIN(execution_time) as first_trade_time
            FROM trades t
            JOIN tokens tok ON t.token_id = tok.token_id
            WHERE tok.symbol = $1
            AND t.trade_type = 'buy'
            """
            
            async with db_manager.pg_pool.acquire() as conn:
                result = await conn.fetchrow(query, holding.symbol)
            
            avg_price = float(result['avg_price']) if result and result['avg_price'] else holding.current_price
            entry_time = result['first_trade_time'] if result and result['first_trade_time'] else datetime.utcnow()
            
            # Create position in position manager using its API
            from .position_manager import PositionType
            
            try:
                # Open a new position through position manager
                position_id = await position_manager.open_position(
                    token_id=token_info.token_id,
                    position_type=PositionType.LONG,
                    entry_price=avg_price,
                    quantity=holding.quantity,
                    stop_loss_pct=15.0,  # 15% stop loss
                    model_confidence=85.0,
                    model_version='vault_sync'
                )
                
                # Create Position object for return
                position = Position(
                    id=str(position_id),
                    symbol=holding.symbol,
                    size=holding.quantity,
                    average_price=avg_price,
                    current_price=holding.current_price,
                    unrealized_pnl=(holding.current_price - avg_price) * holding.quantity,
                    entry_time=entry_time
                )
                
                synced_positions[holding.symbol] = position
                logger.info(f"Created position {position_id} for {holding.symbol}")
                
            except Exception as e:
                logger.warning(f"Failed to create position for {holding.symbol}: {e}")
                # Still track it in our return dict even if DB creation failed
                position = Position(
                    symbol=holding.symbol,
                    size=holding.quantity,
                    average_price=avg_price,
                    current_price=holding.current_price,
                    unrealized_pnl=(holding.current_price - avg_price) * holding.quantity,
                    entry_time=entry_time
                )
                synced_positions[holding.symbol] = position
        
        # Log summary
        total_value = sum(p.size * p.current_price for p in synced_positions.values())
        logger.info(f"✅ Sync complete: {len(synced_positions)} positions, total value: ${total_value:,.2f}")
        
        return synced_positions
        
    except Exception as e:
        logger.error(f"Failed to sync vault holdings: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {}


async def auto_sync_on_startup(
    vault_client: VaultClient,
    position_manager: PositionManager
):
    """
    Automatically sync vault holdings to position manager on system startup.
    This ensures all vault positions are tracked.
    """
    logger.info("🚀 Running automatic vault position sync on startup...")
    
    try:
        # Check if position manager is empty
        active_positions = position_manager.get_active_positions()
        
        if not active_positions:
            logger.info("Position manager is empty, syncing all vault holdings...")
            synced = await sync_vault_to_positions(vault_client, position_manager, force_sync=True)
            logger.info(f"✅ Startup sync complete: {len(synced)} positions synchronized")
        else:
            logger.info(f"Position manager has {len(active_positions)} positions, checking for missing holdings...")
            # Sync only missing positions
            synced = await sync_vault_to_positions(vault_client, position_manager, force_sync=False)
            logger.info(f"✅ Incremental sync complete: {len(synced)} new positions added")
            
    except Exception as e:
        logger.error(f"Startup position sync failed: {e}")
        # Don't crash the system, just log the error
        import traceback
        logger.error(traceback.format_exc()) 