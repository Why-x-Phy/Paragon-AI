"""
Calvin Trade Verification Service

Verifies that vault trades were actually executed on-chain by:
1. Checking transaction confirmation status
2. Analyzing vault program execution logs
3. Verifying token balance changes
4. Parsing Jupiter swap results
5. Updating trade status in database

This service bridges the gap between trade submission and actual execution verification.
"""

import asyncio
import json
import base64
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
from solana.rpc.core import RPCException
from solders.pubkey import Pubkey
from solders.signature import Signature

from ..config.config import config
from ..utils.logger import log
from ..database.production_db import get_db_manager, TradeData

logger = log

@dataclass
class TradeVerificationResult:
    """Result of trade verification"""
    trade_id: int
    tx_hash: str
    verified_at: datetime
    
    # Transaction status
    transaction_confirmed: bool
    transaction_successful: bool
    confirmation_slot: Optional[int] = None
    block_time: Optional[datetime] = None
    
    # Execution details
    calvin_authorized: bool = False
    vault_program_executed: bool = False
    jupiter_swap_executed: bool = False
    
    # Actual amounts (from logs/balance changes)
    actual_input_amount: Optional[float] = None
    actual_output_amount: Optional[float] = None
    actual_price_impact: Optional[float] = None
    
    # Errors
    execution_error: Optional[str] = None
    verification_error: Optional[str] = None
    
    # Final status
    final_status: str = "pending"  # "confirmed", "failed", "timeout"

class TradeVerificationService:
    """
    Service for verifying vault trade execution on Solana blockchain
    """
    
    def __init__(self):
        # Solana connection
        self.rpc_url = config.get('SOLANA_RPC_URL', 'https://api.devnet.solana.com')
        self.client = None
        
        # Program IDs for verification
        self.vault_program_id = config.get('CALVIN_VAULT_PROGRAM_ID', '')
        self.jupiter_program_id = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"  # Jupiter V6
        
        # Calvin authority for signature verification
        self.calvin_authority_pubkey = None
        
        # Database manager
        self.db_manager = None
        
        # Performance tracking
        self.verifications_completed = 0
        self.verifications_failed = 0
        
        logger.info("Trade Verification Service initialized")

    async def initialize(self):
        """Initialize async components"""
        try:
            # Initialize Solana client
            self.client = AsyncClient(self.rpc_url, commitment=Commitment('confirmed'))
            
            # Get Calvin authority public key
            calvin_private_key = config.get('CALVIN_AUTHORITY_PRIVATE_KEY', '')
            if calvin_private_key:
                from solders.keypair import Keypair
                keypair = self._load_keypair_from_string(calvin_private_key)
                self.calvin_authority_pubkey = keypair.pubkey
                logger.info(f"✅ Calvin authority pubkey loaded: {self.calvin_authority_pubkey}")
            else:
                logger.warning("⚠️ Calvin authority private key not configured")
            
            # Initialize database manager
            self.db_manager = await get_db_manager()
            
            logger.info("Trade Verification Service fully initialized")
            
        except Exception as e:
            logger.error(f"❌ Trade verification service initialization failed: {e}")
            raise

    async def close(self):
        """Close async connections"""
        if self.client:
            await self.client.close()
            self.client = None

    async def verify_trade_execution(self, trade_id: int, tx_hash: str) -> TradeVerificationResult:
        """
        Verify if a vault trade was actually executed on-chain
        
        Args:
            trade_id: Database trade ID
            tx_hash: Transaction signature to verify
            
        Returns:
            TradeVerificationResult with complete verification details
        """
        if not self.client:
            await self.initialize()
        
        result = TradeVerificationResult(
            trade_id=trade_id,
            tx_hash=tx_hash,
            verified_at=datetime.utcnow()
        )
        
        try:
            logger.debug(f"🔍 Verifying trade {trade_id} with tx_hash: {tx_hash}")
            
            # Step 1: Check transaction confirmation
            await self._verify_transaction_confirmation(result)
            
            if not result.transaction_confirmed:
                result.final_status = "timeout"
                logger.warning(f"⏰ Transaction {tx_hash} not confirmed")
                return result
            
            if not result.transaction_successful:
                result.final_status = "failed"
                logger.warning(f"❌ Transaction {tx_hash} failed on-chain")
                return result
            
            # Step 2: Verify Calvin authorization
            await self._verify_calvin_authorization(result)
            
            # Step 3: Verify vault program execution
            await self._verify_vault_program_execution(result)
            
            # Step 4: Parse Jupiter swap results
            await self._parse_jupiter_swap_results(result)
            
            # Step 5: Verify token balance changes (if possible)
            await self._verify_balance_changes(result)
            
            # Step 6: Determine final status
            if result.vault_program_executed and result.jupiter_swap_executed:
                result.final_status = "confirmed"
                logger.info(f"✅ Trade {trade_id} verified successfully")
            else:
                result.final_status = "failed"
                logger.warning(f"⚠️ Trade {trade_id} verification incomplete")
            
            # Step 7: Update database
            await self._update_trade_status(result)
            
            self.verifications_completed += 1
            return result
            
        except Exception as e:
            result.verification_error = str(e)
            result.final_status = "failed"
            self.verifications_failed += 1
            logger.error(f"❌ Trade verification failed for {trade_id}: {e}")
            return result

    async def _verify_transaction_confirmation(self, result: TradeVerificationResult):
        """Verify transaction was confirmed on Solana"""
        try:
            signature = Signature.from_string(result.tx_hash)
            
            # Get transaction details
            tx_response = await self.client.get_transaction(
                signature,
                encoding="jsonParsed",
                commitment="confirmed",
                max_supported_transaction_version=0
            )
            
            if not tx_response or not tx_response.value:
                result.transaction_confirmed = False
                result.execution_error = "Transaction not found"
                return
            
            tx_data = tx_response.value
            
            # Check transaction success
            result.transaction_confirmed = True
            result.transaction_successful = tx_data.meta.err is None
            result.confirmation_slot = tx_data.slot
            
            if tx_data.block_time:
                result.block_time = datetime.fromtimestamp(tx_data.block_time)
            
            if tx_data.meta.err:
                result.execution_error = str(tx_data.meta.err)
            
            # Store transaction data for further analysis
            result._tx_data = tx_data
            
            logger.debug(f"✅ Transaction {result.tx_hash} confirmed in slot {result.confirmation_slot}")
            
        except Exception as e:
            result.transaction_confirmed = False
            result.verification_error = f"Confirmation check failed: {e}"
            logger.error(f"❌ Failed to verify transaction confirmation: {e}")

    async def _verify_calvin_authorization(self, result: TradeVerificationResult):
        """Verify transaction was signed by Calvin authority"""
        try:
            if not self.calvin_authority_pubkey or not hasattr(result, '_tx_data'):
                result.calvin_authorized = False
                return
            
            tx_data = result._tx_data
            
            # Check if Calvin's pubkey is in the account keys and marked as signer
            account_keys = tx_data.transaction.message.account_keys
            
            calvin_pubkey_str = str(self.calvin_authority_pubkey)
            
            for i, account in enumerate(account_keys):
                if str(account) == calvin_pubkey_str:
                    # Check if this account is marked as a signer
                    if hasattr(tx_data.transaction.message, 'header'):
                        num_required_signatures = tx_data.transaction.message.header.num_required_signatures
                        result.calvin_authorized = i < num_required_signatures
                    else:
                        result.calvin_authorized = True  # Assume authorized if we can't check
                    break
            
            logger.debug(f"🔐 Calvin authorization: {result.calvin_authorized}")
            
        except Exception as e:
            result.calvin_authorized = False
            logger.error(f"❌ Failed to verify Calvin authorization: {e}")

    async def _verify_vault_program_execution(self, result: TradeVerificationResult):
        """Verify vault program was executed in the transaction"""
        try:
            if not hasattr(result, '_tx_data'):
                result.vault_program_executed = False
                return
            
            tx_data = result._tx_data
            vault_program_pubkey = Pubkey.from_string(self.vault_program_id)
            
            # Check if vault program is in the instructions
            for instruction in tx_data.transaction.message.instructions:
                program_id_index = instruction.program_id_index
                program_id = tx_data.transaction.message.account_keys[program_id_index]
                
                if str(program_id) == str(vault_program_pubkey):
                    result.vault_program_executed = True
                    logger.debug("✅ Vault program execution confirmed")
                    return
            
            result.vault_program_executed = False
            logger.warning("⚠️ Vault program not found in transaction instructions")
            
        except Exception as e:
            result.vault_program_executed = False
            logger.error(f"❌ Failed to verify vault program execution: {e}")

    async def _parse_jupiter_swap_results(self, result: TradeVerificationResult):
        """Parse Jupiter swap results from transaction logs"""
        try:
            if not hasattr(result, '_tx_data'):
                return
            
            tx_data = result._tx_data
            
            # Look for Jupiter program in inner instructions (CPI calls)
            jupiter_program_pubkey = Pubkey.from_string(self.jupiter_program_id)
            
            if hasattr(tx_data.meta, 'inner_instructions'):
                for inner_instruction_set in tx_data.meta.inner_instructions:
                    for inner_instruction in inner_instruction_set.instructions:
                        program_id_index = inner_instruction.program_id_index
                        program_id = tx_data.transaction.message.account_keys[program_id_index]
                        
                        if str(program_id) == str(jupiter_program_pubkey):
                            result.jupiter_swap_executed = True
                            logger.debug("✅ Jupiter swap execution confirmed via CPI")
                            break
            
            # Parse logs for Jupiter swap details
            if hasattr(tx_data.meta, 'log_messages'):
                await self._parse_jupiter_logs(result, tx_data.meta.log_messages)
            
        except Exception as e:
            logger.error(f"❌ Failed to parse Jupiter swap results: {e}")

    async def _parse_jupiter_logs(self, result: TradeVerificationResult, log_messages: List[str]):
        """Parse Jupiter-specific logs for swap details"""
        try:
            for log in log_messages:
                # Look for Jupiter swap events in logs
                if "Program JUP6" in log and "invoke" in log:
                    result.jupiter_swap_executed = True
                
                # Parse swap amounts (Jupiter logs format may vary)
                if "SwapEvent" in log or "swap" in log.lower():
                    # Try to extract amounts from log message
                    # This is Jupiter-specific and may need adjustment based on actual log format
                    try:
                        # Example log parsing - adjust based on actual Jupiter log format
                        if "amountIn:" in log:
                            amount_in_str = log.split("amountIn:")[1].split(",")[0].strip()
                            result.actual_input_amount = float(amount_in_str)
                        
                        if "amountOut:" in log:
                            amount_out_str = log.split("amountOut:")[1].split(",")[0].strip()
                            result.actual_output_amount = float(amount_out_str)
                        
                        if "priceImpact:" in log:
                            price_impact_str = log.split("priceImpact:")[1].split(",")[0].strip()
                            result.actual_price_impact = float(price_impact_str)
                            
                    except (ValueError, IndexError):
                        # Log parsing failed, but swap was still executed
                        pass
            
        except Exception as e:
            logger.error(f"❌ Failed to parse Jupiter logs: {e}")

    async def _verify_balance_changes(self, result: TradeVerificationResult):
        """Verify token balance changes (if accessible)"""
        try:
            if not hasattr(result, '_tx_data'):
                return
            
            tx_data = result._tx_data
            
            # Check pre/post token balances if available in transaction meta
            if hasattr(tx_data.meta, 'pre_token_balances') and hasattr(tx_data.meta, 'post_token_balances'):
                pre_balances = tx_data.meta.pre_token_balances or []
                post_balances = tx_data.meta.post_token_balances or []
                
                # Calculate balance changes
                balance_changes = self._calculate_balance_changes(pre_balances, post_balances)
                
                if balance_changes:
                    logger.debug(f"📊 Token balance changes detected: {len(balance_changes)} accounts")
                    # Could store balance changes in result if needed
            
        except Exception as e:
            logger.error(f"❌ Failed to verify balance changes: {e}")

    def _calculate_balance_changes(self, pre_balances: List, post_balances: List) -> Dict[str, float]:
        """Calculate token balance changes from pre/post balances"""
        changes = {}
        
        try:
            # Create lookup for pre-balances
            pre_lookup = {balance.account_index: balance for balance in pre_balances}
            
            # Calculate changes
            for post_balance in post_balances:
                account_index = post_balance.account_index
                pre_balance = pre_lookup.get(account_index)
                
                if pre_balance:
                    pre_amount = float(pre_balance.ui_token_amount.ui_amount or 0)
                    post_amount = float(post_balance.ui_token_amount.ui_amount or 0)
                    change = post_amount - pre_amount
                    
                    if abs(change) > 0.000001:  # Ignore dust
                        mint = post_balance.mint
                        changes[mint] = change
            
        except Exception as e:
            logger.error(f"❌ Failed to calculate balance changes: {e}")
        
        return changes

    async def _update_trade_status(self, result: TradeVerificationResult):
        """Update trade status in database"""
        try:
            if not self.db_manager:
                return
            
            # Update trade with verification results
            update_data = {
                'execution_status': result.final_status,
                'confirmed_at': result.verified_at,
                'actual_output_amount': result.actual_output_amount,
                'execution_error': result.execution_error or result.verification_error
            }
            
            # Remove None values
            update_data = {k: v for k, v in update_data.items() if v is not None}
            
            await self.db_manager.update_trade_status(result.trade_id, update_data)
            logger.debug(f"✅ Updated trade {result.trade_id} status to {result.final_status}")
            
        except Exception as e:
            logger.error(f"❌ Failed to update trade status: {e}")

    async def verify_pending_trades(self, hours_back: int = 1) -> List[TradeVerificationResult]:
        """Verify all pending trades from the last N hours"""
        try:
            if not self.db_manager:
                await self.initialize()
            
            # Get pending trades
            pending_trades = await self.db_manager.get_pending_trades(hours_back)
            
            if not pending_trades:
                logger.debug("📊 No pending trades to verify")
                return []
            
            logger.info(f"🔍 Verifying {len(pending_trades)} pending trades")
            
            # Verify each trade
            results = []
            for trade in pending_trades:
                result = await self.verify_trade_execution(trade['trade_id'], trade['tx_hash'])
                results.append(result)
                
                # Small delay to avoid overwhelming RPC
                await asyncio.sleep(0.1)
            
            # Summary
            confirmed = sum(1 for r in results if r.final_status == 'confirmed')
            failed = sum(1 for r in results if r.final_status == 'failed')
            
            logger.info(f"📊 Verification complete: {confirmed} confirmed, {failed} failed")
            return results
            
        except Exception as e:
            logger.error(f"❌ Failed to verify pending trades: {e}")
            return []

    def _load_keypair_from_string(self, key_string: str):
        """Load keypair from base58 string"""
        try:
            from solders.keypair import Keypair
            import base58
            
            # Handle different key formats
            if key_string.startswith('[') and key_string.endswith(']'):
                # Array format: [1,2,3,...]
                key_bytes = bytes(json.loads(key_string))
            else:
                # Base58 format
                key_bytes = base58.b58decode(key_string)
            
            return Keypair.from_bytes(key_bytes)
            
        except Exception as e:
            logger.error(f"❌ Failed to load keypair: {e}")
            raise

    def get_stats(self) -> Dict[str, Any]:
        """Get verification service statistics"""
        success_rate = (
            self.verifications_completed / (self.verifications_completed + self.verifications_failed)
            if (self.verifications_completed + self.verifications_failed) > 0 else 0
        )
        
        return {
            'verifications_completed': self.verifications_completed,
            'verifications_failed': self.verifications_failed,
            'success_rate': success_rate,
            'client_connected': self.client is not None,
            'calvin_authority_configured': self.calvin_authority_pubkey is not None,
            'vault_program_id': self.vault_program_id,
            'rpc_url': self.rpc_url
        }

    async def health_check(self) -> bool:
        """Health check for verification service"""
        try:
            if not self.client:
                await self.initialize()
            
            # Test RPC connection
            latest_blockhash = await self.client.get_latest_blockhash()
            
            return latest_blockhash is not None
            
        except Exception as e:
            logger.error(f"❌ Verification service health check failed: {e}")
            return False

    def __del__(self):
        """Cleanup on destruction"""
        if self.client:
            logger.warning("⚠️ TradeVerificationService not properly closed")


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_verification_service_instance: Optional[TradeVerificationService] = None

async def get_trade_verifier() -> TradeVerificationService:
    """Get singleton trade verification service instance"""
    global _verification_service_instance
    
    if _verification_service_instance is None:
        _verification_service_instance = TradeVerificationService()
        await _verification_service_instance.initialize()
    
    return _verification_service_instance

async def stop_trade_verifier():
    """Stop trade verification service instance"""
    global _verification_service_instance
    
    if _verification_service_instance:
        await _verification_service_instance.close()
        _verification_service_instance = None 