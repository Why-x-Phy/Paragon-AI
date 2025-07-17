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
        self.rpc_url = config.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
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
            verified_at=datetime.utcnow(),
            transaction_confirmed=False,
            transaction_successful=False
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
            
            # Check transaction success - handle different possible structures
            result.transaction_confirmed = True
            
            # The correct structure is tx_data.transaction.meta (based on solders library)
            meta = None
            if hasattr(tx_data, 'transaction') and hasattr(tx_data.transaction, 'meta'):
                meta = tx_data.transaction.meta
            elif hasattr(tx_data, 'meta'):
                meta = tx_data.meta
            elif isinstance(tx_data, dict):
                meta = tx_data.get('meta')
            
            if meta:
                result.transaction_successful = meta.err is None if hasattr(meta, 'err') else (meta.get('err') is None if isinstance(meta, dict) else True)
                
                if hasattr(meta, 'err') and meta.err:
                    result.execution_error = str(meta.err)
                elif isinstance(meta, dict) and meta.get('err'):
                    result.execution_error = str(meta.get('err'))
            else:
                # If we can't find meta, assume successful if transaction exists
                result.transaction_successful = True
                logger.warning(f"⚠️ Could not find meta data for transaction {result.tx_hash}, assuming successful")
            
            # Get slot information directly from tx_data
            result.confirmation_slot = tx_data.slot
            
            # Get block time
            if hasattr(tx_data, 'block_time') and tx_data.block_time:
                result.block_time = datetime.fromtimestamp(tx_data.block_time)
            
            # Store transaction data for further analysis
            result._tx_data = tx_data
            
            logger.debug(f"✅ Transaction {result.tx_hash} confirmed in slot {result.confirmation_slot}")
            
        except Exception as e:
            result.transaction_confirmed = False
            result.verification_error = f"Confirmation check failed: {e}"
            logger.error(f"❌ Failed to verify transaction confirmation: {e}")
            import traceback
            logger.debug(traceback.format_exc())

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
        """Parse Jupiter swap results from transaction"""
        try:
            if not hasattr(result, '_tx_data'):
                return
            
            tx_data = result._tx_data
            
            # The correct structure is tx_data.transaction.meta (based on solders library)
            meta = None
            if hasattr(tx_data, 'transaction') and hasattr(tx_data.transaction, 'meta'):
                meta = tx_data.transaction.meta
            elif hasattr(tx_data, 'meta'):
                meta = tx_data.meta
            elif isinstance(tx_data, dict):
                meta = tx_data.get('meta')
            
            if not meta:
                logger.warning(f"⚠️ No meta data found for Jupiter swap parsing")
                return
            
            # Look for Jupiter program in inner instructions (CPI calls)
            jupiter_program_pubkey = Pubkey.from_string(self.jupiter_program_id)
            
            # Handle inner instructions
            if hasattr(meta, 'inner_instructions') and meta.inner_instructions:
                for inner_instruction_set in meta.inner_instructions:
                    instructions = inner_instruction_set.instructions if hasattr(inner_instruction_set, 'instructions') else inner_instruction_set.get('instructions', [])
                    for inner_instruction in instructions:
                        program_id_index = inner_instruction.program_id_index if hasattr(inner_instruction, 'program_id_index') else inner_instruction.get('program_id_index')
                        
                        # Get account keys from the correct location
                        if hasattr(tx_data, 'transaction') and hasattr(tx_data.transaction, 'transaction') and hasattr(tx_data.transaction.transaction, 'message'):
                            account_keys = tx_data.transaction.transaction.message.account_keys
                        elif hasattr(tx_data, 'transaction') and hasattr(tx_data.transaction, 'message'):
                            account_keys = tx_data.transaction.message.account_keys
                        else:
                            account_keys = None
                        
                        if account_keys and program_id_index is not None:
                            program_id = account_keys[program_id_index]
                            
                            if str(program_id) == str(jupiter_program_pubkey):
                                result.jupiter_swap_executed = True
                                logger.debug("✅ Jupiter swap execution confirmed via CPI")
                                break
            
            # Parse logs for Jupiter swap details
            if hasattr(meta, 'log_messages') and meta.log_messages:
                await self._parse_jupiter_logs(result, meta.log_messages)
            
        except Exception as e:
            logger.error(f"❌ Failed to parse Jupiter swap results: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    async def _parse_jupiter_logs(self, result: TradeVerificationResult, log_messages: List[str]):
        """Parse Jupiter-specific logs for swap details"""
        try:
            for log in log_messages:
                # Look for Jupiter program mentions
                if "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4" in log or "Jupiter" in log:
                    result.jupiter_swap_executed = True
                    logger.debug(f"✅ Jupiter swap detected in log: {log[:100]}...")
                
                # Look for specific Jupiter swap patterns
                if "🚀 Setting up Jupiter CPI" in log:
                    result.jupiter_swap_executed = True
                    logger.debug("✅ Jupiter CPI setup detected")
                
                # Look for Jupiter program invocation
                if "Program JUP6" in log and "invoke" in log:
                    result.jupiter_swap_executed = True
                    logger.debug("✅ Jupiter program invocation detected")
                
                # Try to parse amounts from logs
                try:
                    # Look for amount patterns in logs
                    if "amount" in log.lower() and any(char.isdigit() for char in log):
                        # Try to extract numbers from the log
                        import re
                        numbers = re.findall(r'\d+', log)
                        if numbers:
                            # Store the first large number we find as potential amount
                            for num_str in numbers:
                                num = int(num_str)
                                if num > 1000:  # Ignore small numbers
                                    if result.actual_output_amount is None:
                                        result.actual_output_amount = num
                                        logger.debug(f"Extracted potential amount from log: {num}")
                                    break
                    
                    # Look for swap completion messages
                    if "swap" in log.lower() and ("complete" in log.lower() or "success" in log.lower()):
                        result.jupiter_swap_executed = True
                        logger.debug("✅ Jupiter swap completion detected")
                        
                except Exception as e:
                    # Log parsing failed for this line, continue with others
                    logger.debug(f"Failed to parse Jupiter log line: {log[:100]}... Error: {e}")
                    continue
            
            if result.jupiter_swap_executed:
                logger.info(f"✅ Jupiter swap execution confirmed via log analysis")
            else:
                logger.debug("❌ No Jupiter swap execution detected in logs")
                
        except Exception as e:
            logger.error(f"❌ Failed to parse Jupiter logs: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    async def _verify_balance_changes(self, result: TradeVerificationResult):
        """Verify token balance changes and extract actual amounts"""
        try:
            if not hasattr(result, '_tx_data'):
                return
            
            tx_data = result._tx_data
            
            # The correct structure is tx_data.transaction.meta (based on solders library)
            meta = None
            if hasattr(tx_data, 'transaction') and hasattr(tx_data.transaction, 'meta'):
                meta = tx_data.transaction.meta
            elif hasattr(tx_data, 'meta'):
                meta = tx_data.meta
            elif isinstance(tx_data, dict):
                meta = tx_data.get('meta')
            
            if not meta:
                logger.warning(f"⚠️ No meta data found for balance change verification")
                return
            
            # Check pre/post token balances if available in transaction meta
            if hasattr(meta, 'pre_token_balances') and hasattr(meta, 'post_token_balances'):
                pre_balances = meta.pre_token_balances or []
                post_balances = meta.post_token_balances or []
                
                if pre_balances and post_balances:
                    # Calculate balance changes
                    balance_changes = self._calculate_balance_changes(pre_balances, post_balances)
                    
                    if balance_changes:
                        logger.debug(f"📊 Token balance changes detected: {len(balance_changes)} accounts")
                        
                        # Store balance changes for debugging
                        result.balance_changes = list(balance_changes.items())
                        
                        # ENHANCED: Extract actual amounts from balance changes if not already available
                        if not result.actual_input_amount or not result.actual_output_amount:
                            # Try to identify input/output amounts from balance changes
                            # Look for USDC changes (input/output for most trades)
                            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                            
                            # Get account keys to identify vault accounts
                            account_keys = None
                            if hasattr(tx_data, 'transaction') and hasattr(tx_data.transaction, 'transaction') and hasattr(tx_data.transaction.transaction, 'message'):
                                account_keys = tx_data.transaction.transaction.message.account_keys
                            elif hasattr(tx_data, 'transaction') and hasattr(tx_data.transaction, 'message'):
                                account_keys = tx_data.transaction.message.account_keys
                            
                            if account_keys:
                                # Parse balance changes to identify vault transactions
                                usdc_spent = None
                                usdc_received = None
                                tokens_spent = None
                                tokens_received = None
                                
                                for change_key, change_amount in balance_changes.items():
                                    try:
                                        # Extract account index and mint from the key
                                        parts = change_key.split('_')
                                        if len(parts) >= 3:
                                            account_index = int(parts[1])
                                            mint = '_'.join(parts[2:])  # Rejoin mint address
                                            
                                            # Get the actual account pubkey
                                            if account_index < len(account_keys):
                                                account_pubkey = account_keys[account_index]
                                                
                                                if mint == usdc_mint:
                                                    # USDC changes
                                                    if change_amount > 0:
                                                        usdc_received = change_amount
                                                        logger.debug(f"Found USDC gain: {change_amount} (account {account_index})")
                                                    else:
                                                        usdc_spent = abs(change_amount)
                                                        logger.debug(f"Found USDC spend: {abs(change_amount)} (account {account_index})")
                                                else:
                                                    # Other token changes
                                                    if change_amount < 0:
                                                        tokens_spent = abs(change_amount)
                                                        logger.debug(f"Found token sale: {abs(change_amount)} (account {account_index})")
                                                    else:
                                                        tokens_received = change_amount
                                                        logger.debug(f"Found token purchase: {change_amount} (account {account_index})")
                                                
                                    except Exception as e:
                                        logger.debug(f"Failed to process balance change {change_key}: {e}")
                                        continue
                                
                                # Determine trade type and set input/output correctly
                                if usdc_spent and tokens_received:
                                    # BUY TRADE: Spent USDC to get tokens
                                    result.actual_input_amount = usdc_spent  # USDC spent
                                    result.actual_output_amount = tokens_received  # Tokens received
                                    logger.debug(f"Detected BUY trade: {usdc_spent} USDC → {tokens_received} tokens")
                                elif tokens_spent and usdc_received:
                                    # SELL TRADE: Sold tokens to get USDC
                                    result.actual_input_amount = tokens_spent  # Tokens sold
                                    result.actual_output_amount = usdc_received  # USDC received
                                    logger.debug(f"Detected SELL trade: {tokens_spent} tokens → {usdc_received} USDC")
                                else:
                                    # Fallback to original logic if pattern doesn't match
                                    logger.debug(f"Could not determine trade type clearly, using fallback logic")
                                    if usdc_received and not result.actual_output_amount:
                                        result.actual_output_amount = usdc_received
                                    if usdc_spent and not result.actual_input_amount:
                                        result.actual_input_amount = usdc_spent
                        
                        logger.debug(f"✅ Balance changes processed: input={result.actual_input_amount}, output={result.actual_output_amount}")
                    else:
                        logger.debug("📊 No token balance changes detected")
                else:
                    logger.debug("📊 No pre/post token balance data available")
            else:
                logger.debug("📊 No pre/post token balance attributes found")
            
        except Exception as e:
            logger.error(f"❌ Failed to verify balance changes: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    def _calculate_balance_changes(self, pre_balances: List, post_balances: List) -> Dict[str, float]:
        """Calculate balance changes between pre and post token balances"""
        try:
            # Create maps by account_index for easier lookup
            pre_map = {}
            post_map = {}
            
            for balance in pre_balances:
                account_index = balance.account_index
                ui_amount = balance.ui_token_amount.ui_amount if hasattr(balance.ui_token_amount, 'ui_amount') and balance.ui_token_amount.ui_amount else 0.0
                pre_map[account_index] = {
                    'mint': str(balance.mint),
                    'amount': ui_amount
                }
            
            for balance in post_balances:
                account_index = balance.account_index
                ui_amount = balance.ui_token_amount.ui_amount if hasattr(balance.ui_token_amount, 'ui_amount') and balance.ui_token_amount.ui_amount else 0.0
                post_map[account_index] = {
                    'mint': str(balance.mint),
                    'amount': ui_amount
                }
            
            # Calculate changes
            changes = {}
            all_account_indices = set(pre_map.keys()) | set(post_map.keys())
            
            for account_index in all_account_indices:
                pre_amount = pre_map.get(account_index, {}).get('amount', 0.0)
                post_amount = post_map.get(account_index, {}).get('amount', 0.0)
                change = post_amount - pre_amount
                
                if abs(change) > 0.001:  # Only include significant changes
                    # Get mint from either pre or post
                    mint = pre_map.get(account_index, {}).get('mint') or post_map.get(account_index, {}).get('mint')
                    if mint:
                        changes[f"account_{account_index}_{mint}"] = change
            
            return changes
            
        except Exception as e:
            logger.error(f"❌ Failed to calculate balance changes: {e}")
            return {}

    async def _update_trade_status(self, result: TradeVerificationResult):
        """Update trade status in database with actual transaction data"""
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
            
            # CRITICAL FIX: Update actual trade amounts from blockchain data
            if result.final_status == "confirmed" and result.actual_output_amount is not None:
                # Get the original trade to determine if it's buy or sell
                try:
                    trade_query = """
                        SELECT trade_type, token_id, price 
                        FROM trades 
                        WHERE trade_id = $1
                    """
                    async with self.db_manager.pg_pool.acquire() as conn:
                        trade_row = await conn.fetchrow(trade_query, result.trade_id)
                    
                    if trade_row:
                        trade_type = trade_row['trade_type']
                        token_id = trade_row['token_id']
                        original_price = trade_row['price']
                        
                        # Get token info for decimals conversion
                        token_info = None
                        for token in self.db_manager._token_cache.values():
                            if token.token_id == token_id:
                                token_info = token
                                break
                        
                        if token_info:
                            token_decimals = token_info.decimals
                            
                            if trade_type == 'buy':
                                # For BUY: actual_output_amount is the tokens received
                                # Convert from smallest units to token units
                                actual_quantity = result.actual_output_amount / (10 ** token_decimals)
                                # Calculate actual value in USDC (input amount would be better, but use price estimate)
                                actual_value_usdc = actual_quantity * original_price
                                
                                update_data['quantity'] = actual_quantity
                                update_data['value_usdc'] = actual_value_usdc
                                
                                logger.debug(f"Updated BUY trade {result.trade_id}: {actual_quantity} tokens, ${actual_value_usdc:.2f}")
                                
                            elif trade_type == 'sell':
                                # For SELL: actual_output_amount is the USDC received
                                # Convert from USDC smallest units (6 decimals) to USDC
                                actual_value_usdc = result.actual_output_amount / (10 ** 6)  # USDC has 6 decimals
                                # Calculate quantity sold (use input amount if available, otherwise estimate)
                                if result.actual_input_amount:
                                    actual_quantity = result.actual_input_amount / (10 ** token_decimals)
                                else:
                                    # Estimate from USDC received and price
                                    actual_quantity = actual_value_usdc / original_price if original_price > 0 else 0
                                
                                update_data['quantity'] = actual_quantity
                                update_data['value_usdc'] = actual_value_usdc
                                
                                logger.debug(f"Updated SELL trade {result.trade_id}: {actual_quantity} tokens, ${actual_value_usdc:.2f}")
                        
                except Exception as e:
                    logger.warning(f"Failed to update actual trade amounts for {result.trade_id}: {e}")
                    # Continue with status update even if amount update fails
            
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