"""
Calvin Vault Trade Executor

Translates portfolio signals from the inference engine into Jupiter swap transactions
and executes them through the Calvin vault smart contracts.

Phase 3.2 Integration:
- Processes PortfolioSignal objects from portfolio coordinator
- Creates Jupiter V6 swap data for USDC → target token trades
- Executes trades through vault program smart contracts
- Records trade execution data in TimescaleDB
- Handles error conditions gracefully with fallback logging

Phase 3.3 Enhancement:
- Automatic trade verification after execution
- On-chain confirmation of vault and Jupiter execution
- Database status updates with verification results
"""

import asyncio
import time
import base64
from typing import Dict, List, Optional, Any
from datetime import datetime
import aiohttp

from ..inference.portfolio_coordinator import PortfolioSignal, AssetAllocation, TradingSignal
from ..config.config import config
from ..utils.logger import log
from ..database.production_db import get_db_manager

logger = log

class VaultTradeExecutor:
    """
    Executes portfolio trading signals through Calvin vault smart contracts
    """
    
    def __init__(self):
        # Core components - now properly imported
        self.vault_client = None
        self.jupiter_client = None
        self.trade_verifier = None
        self.db_manager = None
        
        # Trading configuration - UPDATED based on real Jupiter data
        # Real test: $10k FARTCOIN trade = 0.0008% price impact with 0.5% slippage
        self.max_slippage_bps = int(config.get('MAX_SLIPPAGE_BPS', 100))  # 1.0% - still conservative vs 0.5% actual
        # REMOVED: No arbitrary trade size limits - portfolio coordinator handles sizing
        
        # Performance tracking
        self.execution_times = []
        self.trade_history = []
        
        logger.info("Vault Trade Executor initialized")
        logger.info(f"Max slippage: {self.max_slippage_bps/100:.1f}% (realistic for hourly substantial trades)")
        logger.info("Trade sizing: Managed by portfolio coordinator (no artificial limits)")

    async def initialize(self):
        """Initialize async components"""
        try:
            # Initialize database manager
            self.db_manager = await get_db_manager()
            
            # Initialize trade verifier
            try:
                from .trade_verifier import get_trade_verifier
                self.trade_verifier = await get_trade_verifier()
                logger.info("✅ Trade verifier initialized and ready")
            except Exception as e:
                logger.warning(f"⚠️ Trade verifier initialization failed: {e}")
                self.trade_verifier = None
            
            # Initialize vault and Jupiter clients
            try:
                from .vault_client import VaultClient
                from .jupiter_client import JupiterV6Client
                from solana.rpc.async_api import AsyncClient
                from solders.keypair import Keypair
                import os
                import json
                
                # Create vault client with proper parameters
                rpc_url = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
                vault_program_id = os.getenv('VAULT_PROGRAM_ID', 'tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z')
                
                # Load authority keypair
                authority_key_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'onchain', 'calvin-ai-authority.json')
                with open(authority_key_path, 'r') as f:
                    authority_key_data = json.load(f)
                authority_keypair = Keypair.from_bytes(authority_key_data)
                
                # Create connection and vault client
                connection = AsyncClient(rpc_url)
                self.vault_client = VaultClient(
                    vault_program=vault_program_id,
                    connection=connection,
                    authority_keypair=authority_keypair
                )
                
                # CRITICAL FIX: Ensure vault client has access to database manager
                # The vault client needs this for token lookups and balance queries
                self.vault_client.db_manager = self.db_manager
                
                await self.vault_client.initialize()
                logger.info("✅ Vault client initialized and ready")
                
                self.jupiter_client = JupiterV6Client()
                await self.jupiter_client.initialize()
                logger.info("✅ Jupiter client initialized and ready")
                
            except ImportError as e:
                logger.warning(f"⚠️ Client import failed - running in simulation mode: {e}")
                self.vault_client = None
                self.jupiter_client = None
            except Exception as e:
                logger.error(f"❌ Client initialization failed - running in simulation mode: {e}")
                self.vault_client = None
                self.jupiter_client = None
            
            logger.info("Vault Trade Executor fully initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize Vault Trade Executor: {e}")
            # Don't raise - allow graceful degradation
            self.vault_client = None
            self.jupiter_client = None

    async def execute_portfolio_trades(self, portfolio_signal: PortfolioSignal) -> List[str]:
        """
        Execute all buy AND sell signals from portfolio coordinator
        
        Args:
            portfolio_signal: Portfolio signal with buy/sell recommendations
            
        Returns:
            List of transaction signatures (or simulation IDs)
        """
        results = []
        
        try:
            total_signals = len(portfolio_signal.buy_signals) + len(portfolio_signal.sell_signals)
            logger.info(f"🎯 Processing portfolio signal: {len(portfolio_signal.buy_signals)} buy signals, {len(portfolio_signal.sell_signals)} sell signals")
            
            # Validate vault state before trading (if vault client available)
            if self.vault_client:
                vault_state = await self.vault_client.get_vault_state()
                if vault_state.get('paused', True):
                    logger.warning("⚠️ Vault is paused, skipping trades")
                    return results
            else:
                logger.info("📝 Running in simulation mode (no vault client)")
            
            # CRITICAL FIX: Execute SELL signals FIRST (higher priority for risk management)
            if portfolio_signal.sell_signals:
                logger.info(f"🔥 Executing {len(portfolio_signal.sell_signals)} SELL signals first (risk management priority)")
                
                for i, sell_signal in enumerate(portfolio_signal.sell_signals):
                    try:
                        logger.info(f"🔥 Processing SELL {i+1}/{len(portfolio_signal.sell_signals)}: {sell_signal.symbol}")
                        
                        # For sells, we just need the token balance - no dollar calculations needed
                        token_mint = await self._get_token_mint(sell_signal.symbol)
                        if not token_mint:
                            logger.warning(f"⚠️ Token mint not found for {sell_signal.symbol}")
                            continue
                        
                        # Get the vault's token balance
                        token_balance = await self.vault_client.get_token_balance(token_mint) if self.vault_client else 0
                        
                        if token_balance <= 0:
                            logger.info(f"⚠️ No {sell_signal.symbol} tokens in vault to sell (balance: {token_balance})")
                            continue
                        
                        logger.info(f"📊 Found {token_balance} {sell_signal.symbol} tokens in vault - will sell ALL")
                        
                        # Execute the sell - just pass the signal, we handle everything in execute_single_trade
                        tx_sig = await self.execute_single_trade(sell_signal, None, trade_type='sell')
                        
                        if tx_sig:
                            # Record as pending first, then verify
                            trade_id = await self._record_trade_execution(sell_signal, None, tx_sig, "pending", trade_type='sell')
                            logger.info(f"📤 SELL submitted: {sell_signal.symbol} - {tx_sig[:12]}...")
                            
                            # Verify transaction immediately (for real transactions)
                            if trade_id and self.trade_verifier and not tx_sig.startswith('SIM_'):
                                verification_result = await self._verify_trade_immediately(trade_id, tx_sig)
                                if verification_result.final_status == "confirmed":
                                    results.append(tx_sig)
                                    logger.info(f"✅ SELL confirmed: {sell_signal.symbol} - {tx_sig[:12]}...")
                                else:
                                    logger.error(f"❌ SELL verification failed: {sell_signal.symbol} - {verification_result.execution_error}")
                            elif tx_sig.startswith('SIM_'):
                                # For simulations, just add to results
                                results.append(tx_sig)
                                logger.info(f"📝 SELL simulation completed: {sell_signal.symbol}")
                        else:
                            # Record failed trade with detailed error info
                            error_msg = f"SELL execution returned None for {sell_signal.symbol}"
                            await self._record_trade_execution(sell_signal, None, None, "failed", error_msg, trade_type='sell')
                            logger.warning(f"❌ SELL failed: {sell_signal.symbol} - execution returned None")
                            
                    except Exception as e:
                        error_msg = f"SELL execution exception: {str(e)}"
                        logger.error(f"❌ Failed to execute SELL for {sell_signal.symbol}: {e}")
                        
                        # Log additional debugging info
                        logger.debug(f"  - Sell signal details: confidence={sell_signal.confidence:.2%}, predicted_change={sell_signal.predicted_change_pct:.2%}")
                        logger.debug(f"  - Vault client available: {self.vault_client is not None}")
                        logger.debug(f"  - Jupiter client available: {self.jupiter_client is not None}")
                        
                        # Record the failed trade with detailed error
                        try:
                            await self._record_trade_execution(sell_signal, None, None, "failed", error_msg, trade_type='sell')
                        except Exception as record_error:
                            logger.error(f"❌ Failed to record failed SELL trade: {record_error}")
            
            # Execute BUY signals after sells (to use freed up capital)
            if portfolio_signal.buy_signals:
                logger.info(f"🚀 Executing {len(portfolio_signal.buy_signals)} BUY signals")
                
                for i, buy_signal in enumerate(portfolio_signal.buy_signals):
                    try:
                        # Get allocation for this signal
                        allocation = portfolio_signal.asset_allocations.get(buy_signal.symbol)
                        if not allocation:
                            logger.warning(f"⚠️ No allocation found for {buy_signal.symbol}")
                            continue
                        
                        # Trade size managed by portfolio coordinator - no artificial validation needed
                        trade_size = allocation.position_value_usdc
                        
                        # Execute individual trade
                        logger.info(f"🚀 Executing BUY {i+1}/{len(portfolio_signal.buy_signals)}: {buy_signal.symbol}")
                        tx_sig = await self.execute_single_trade(buy_signal, allocation, trade_type='buy')
                        
                        if tx_sig:
                            # Record as pending first, then verify
                            trade_id = await self._record_trade_execution(buy_signal, allocation, tx_sig, "pending", trade_type='buy')
                            logger.info(f"📤 BUY submitted: {buy_signal.symbol} - {tx_sig[:12]}...")
                            
                            # Verify transaction immediately (for real transactions)
                            if trade_id and self.trade_verifier and not tx_sig.startswith('SIM_'):
                                verification_result = await self._verify_trade_immediately(trade_id, tx_sig)
                                if verification_result.final_status == "confirmed":
                                    results.append(tx_sig)
                                    logger.info(f"✅ BUY confirmed: {buy_signal.symbol} - {tx_sig[:12]}...")
                                else:
                                    logger.error(f"❌ BUY verification failed: {buy_signal.symbol} - {verification_result.execution_error}")
                            elif tx_sig.startswith('SIM_'):
                                # For simulations, just add to results
                                results.append(tx_sig)
                                logger.info(f"📝 BUY simulation completed: {buy_signal.symbol}")
                        else:
                            # Record failed trade
                            await self._record_trade_execution(buy_signal, allocation, None, "failed", trade_type='buy')
                            logger.warning(f"❌ BUY failed: {buy_signal.symbol}")
                            
                    except Exception as e:
                        logger.error(f"❌ Failed to execute BUY for {buy_signal.symbol}: {e}")
                        await self._record_trade_execution(buy_signal, allocation, None, "failed", str(e), trade_type='buy')
            
            # Final summary
            success_rate = len(results) / total_signals if total_signals > 0 else 0
            buy_count = len(portfolio_signal.buy_signals)
            sell_count = len(portfolio_signal.sell_signals)
            
            logger.info(f"🏁 Portfolio execution completed:")
            logger.info(f"   📊 {len(results)}/{total_signals} trades successful ({success_rate:.1%})")
            logger.info(f"   🚀 {buy_count} BUY signals processed")
            logger.info(f"   🔥 {sell_count} SELL signals processed")
            logger.info(f"   💡 Sells executed first for optimal risk management")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Portfolio trade execution failed: {e}")
            return results

    async def _verify_trade_immediately(self, trade_id: int, tx_hash: str):
        """Immediately verify trade execution (blocks until confirmed)"""
        try:
            logger.debug(f"🔍 Verifying trade {trade_id} immediately...")
            
            # Wait a moment for transaction to propagate
            await asyncio.sleep(3)
            
            # Attempt verification with retries
            max_retries = 3
            for attempt in range(max_retries):
                result = await self.trade_verifier.verify_trade_execution(trade_id, tx_hash)
                
                if result.final_status == 'confirmed':
                    logger.info(f"✅ Trade {trade_id} verified successfully on-chain")
                    return result
                elif result.final_status == 'failed':
                    logger.error(f"❌ Trade {trade_id} failed on-chain: {result.execution_error}")
                    return result
                else:
                    # Still pending, wait and retry
                    if attempt < max_retries - 1:
                        logger.debug(f"⏳ Trade {trade_id} still pending, retrying in 5s...")
                        await asyncio.sleep(5)
            
            # If we get here, verification timed out
            logger.warning(f"⏰ Trade {trade_id} verification timed out")
            result.final_status = 'timeout'
            return result
                    
        except Exception as e:
            logger.error(f"❌ Immediate trade verification failed for {trade_id}: {e}")
            # Return a failed result
            from ..vault.trade_verifier import TradeVerificationResult
            result = TradeVerificationResult(
                trade_id=trade_id,
                tx_hash=tx_hash,
                verified_at=datetime.utcnow()
            )
            result.final_status = 'failed'
            result.verification_error = str(e)
            return result

    async def _verify_trade_async(self, trade_id: int, tx_hash: str):
        """Asynchronously verify trade execution (don't block main flow) - DEPRECATED"""
        try:
            # Wait a bit for transaction to be confirmed
            await asyncio.sleep(10)
            
            logger.debug(f"🔍 Starting verification for trade {trade_id}")
            result = await self.trade_verifier.verify_trade_execution(trade_id, tx_hash)
            
            if result.final_status == 'confirmed':
                logger.info(f"✅ Trade {trade_id} verified successfully on-chain")
            else:
                logger.warning(f"⚠️ Trade {trade_id} verification failed: {result.final_status}")
                if result.execution_error:
                    logger.warning(f"   Error: {result.execution_error}")
                    
        except Exception as e:
            logger.error(f"❌ Async trade verification failed for {trade_id}: {e}")

    async def execute_single_trade(self, signal: TradingSignal, allocation: Optional[AssetAllocation], trade_type: str = 'buy') -> Optional[str]:
        """
        Execute a single trade through the vault (or simulate) - SUPPORTS BOTH BUY AND SELL
        
        Args:
            signal: Trading signal with prediction and confidence
            allocation: Asset allocation with position sizing (required for buy, optional for sell)
            trade_type: 'buy' or 'sell' (default: 'buy')
            
        Returns:
            Transaction signature if successful, simulation ID if simulated, None if failed
        """
        start_time = time.time()
        
        try:
            # 1. Get token mint address
            token_mint = await self._get_token_mint(signal.symbol)
            if not token_mint:
                logger.error(f"❌ Token mint not found for {signal.symbol}")
                return None
            
            # 2. CRITICAL FIX: Handle both BUY and SELL trades
            if trade_type == 'sell':
                # SELL: Token → USDC (reverse of buy)
                logger.info(f"🔥 Preparing SELL trade: {signal.symbol} → USDC")
                
                # For sells, get the token balance directly
                position_size = await self.vault_client.get_token_balance(token_mint) if self.vault_client else 0
                if position_size <= 0:
                    logger.warning(f"⚠️ No {signal.symbol} tokens in vault to sell")
                    return None
                
                logger.info(f"📊 Selling ALL {position_size} {signal.symbol} tokens")
                
                # Create Jupiter swap data for SELL (Token → USDC)
                if self.jupiter_client:
                    jupiter_data = await self.create_jupiter_trade(
                        input_mint=token_mint,  # Token we're selling
                        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                        amount_tokens=position_size,  # Amount of tokens to sell
                        slippage_bps=self.max_slippage_bps,
                        trade_type='sell'
                    )
                else:
                    # Simulate Jupiter data creation for sell
                    jupiter_data = self._simulate_jupiter_trade(signal.symbol, position_size, trade_type='sell')
                
                if not jupiter_data:
                    logger.error(f"❌ Failed to create Jupiter SELL data for {signal.symbol}")
                    return None
                
                # Execute SELL through vault smart contract
                if self.vault_client:
                    tx_sig = await self.vault_client.execute_trade(
                        jupiter_data=jupiter_data,
                        source_mint=token_mint,  # Token we're selling
                        destination_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC
                    )
                else:
                    # Simulate vault execution for sell
                    tx_sig = await self._simulate_vault_execution(signal.symbol, None, trade_type='sell')
                
            else:
                # BUY: USDC → Token (existing logic)
                if not allocation:
                    logger.error(f"❌ No allocation provided for BUY trade of {signal.symbol}")
                    return None
                    
                logger.info(f"🚀 Preparing BUY trade: USDC → {signal.symbol}")
                
                # Create Jupiter swap data for BUY (USDC → Token)
                if self.jupiter_client:
                    jupiter_data = await self.create_jupiter_trade(
                        input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                        output_mint=token_mint,  # Token we're buying
                        amount_usdc=allocation.position_value_usdc,
                        slippage_bps=self.max_slippage_bps,
                        trade_type='buy'
                    )
                else:
                    # Simulate Jupiter data creation for buy
                    jupiter_data = self._simulate_jupiter_trade(signal.symbol, allocation.position_value_usdc, trade_type='buy')
                
                if not jupiter_data:
                    logger.error(f"❌ Failed to create Jupiter BUY data for {signal.symbol}")
                    return None
                
                # Execute BUY through vault smart contract
                if self.vault_client:
                    tx_sig = await self.vault_client.execute_trade(
                        jupiter_data=jupiter_data,
                        source_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                        destination_mint=token_mint,  # Token we're buying
                        amount_usdc=allocation.position_value_usdc
                    )
                else:
                    # Simulate vault execution for buy
                    tx_sig = await self._simulate_vault_execution(signal.symbol, allocation, trade_type='buy')
            
            execution_time = (time.time() - start_time) * 1000
            self.execution_times.append(execution_time)
            
            if tx_sig:
                trade_amount = allocation.position_value_usdc if (trade_type == 'buy' and allocation) else position_size
                logger.info(f"✅ Executed {trade_type.upper()} trade for {signal.symbol}: {trade_amount} in {execution_time:.1f}ms")
                logger.info(f"   Transaction: {tx_sig}")
            
            return tx_sig
            
        except Exception as e:
            logger.error(f"❌ Single {trade_type.upper()} trade execution failed for {signal.symbol}: {e}")
            return None

    async def _get_position_size_to_sell(self, symbol: str) -> float:
        """
        Get the position size to sell for a given symbol by querying vault balance directly
        
        Args:
            symbol: Token symbol to check
            
        Returns:
            Amount of tokens to sell (in token units) - ALL tokens if any exist
        """
        try:
            # Get token mint address from cache
            token_mint = await self._get_token_mint(symbol)
            if not token_mint:
                logger.error(f"❌ Token mint not found for {symbol}")
                return 0.0
            
            # For sell signals, we just need the vault balance - no price needed
            if not self.vault_client:
                logger.warning(f"⚠️ No vault client available for {symbol}")
                return 0.0
            
            # CRITICAL FIX: Use vault client's get_token_balance method directly
            # This method handles all the complexity of querying the vault's token account
            try:
                logger.debug(f"🔍 Querying vault balance for {symbol} (mint: {token_mint[:8]}...)")
                
                # Get the actual token balance from the vault
                token_balance = await self.vault_client.get_token_balance(token_mint)
                
                if token_balance is None:
                    logger.debug(f"Vault balance query returned None for {symbol}")
                    return 0.0
                
                if token_balance <= 0:
                    logger.debug(f"No {symbol} tokens in vault to sell (balance: {token_balance})")
                    return 0.0
                
                # For sell signals, we sell ALL tokens we have
                logger.info(f"📊 Found {token_balance} {symbol} tokens in vault - will sell ALL")
                return token_balance
                
            except Exception as vault_error:
                logger.error(f"❌ Failed to get vault balance for {symbol}: {vault_error}")
                
                # FALLBACK: Try to get balance from vault's get_all_vault_balances method
                try:
                    logger.debug(f"🔄 Trying fallback method for {symbol}")
                    all_balances = await self.vault_client.get_all_vault_balances()
                    
                    if token_mint in all_balances:
                        balance = all_balances[token_mint]
                        logger.info(f"📊 Fallback: Found {balance} {symbol} tokens in vault")
                        return balance
                    else:
                        logger.debug(f"No {symbol} balance found in vault balances")
                        return 0.0
                        
                except Exception as fallback_error:
                    logger.error(f"❌ Fallback balance query failed for {symbol}: {fallback_error}")
                    return 0.0
            
        except Exception as e:
            logger.error(f"❌ Failed to get position size to sell for {symbol}: {e}")
            return 0.0

    async def create_jupiter_trade(self, input_mint: str, output_mint: str, 
                                 amount_usdc: float = None, amount_tokens: float = None, 
                                 slippage_bps: int = 50, trade_type: str = 'buy') -> Optional[Dict]:
        """
        Create Jupiter swap transaction data for vault execution - SUPPORTS BOTH BUY AND SELL
        
        Args:
            input_mint: Input token mint
            output_mint: Output token mint
            amount_usdc: Amount in USDC to trade (for buys)
            amount_tokens: Amount in tokens to trade (for sells)
            slippage_bps: Maximum slippage in basis points
            trade_type: 'buy' or 'sell'
            
        Returns:
            Jupiter swap data for vault execution
        """
        try:
            # Calculate amount in proper units based on trade type
            if trade_type == 'buy':
                # BUY: Convert USDC to micro-USDC (6 decimals)
                if amount_usdc is None:
                    raise ValueError("amount_usdc is required for buy trades")
                amount_in_smallest_unit = int(amount_usdc * 1e6)
                logger.debug(f"🚀 BUY trade: {amount_usdc} USDC = {amount_in_smallest_unit} micro-USDC")
            else:
                # SELL: Convert tokens to smallest unit (need to get token decimals)
                if amount_tokens is None:
                    raise ValueError("amount_tokens is required for sell trades")
                
                # CRITICAL FIX: Get token decimals from database manager for sell trades
                token_decimals = 6  # Default to 6 decimals
                try:
                    # For sells, input_mint is the token being sold
                    if self.db_manager and hasattr(self.db_manager, '_token_cache'):
                        for token in self.db_manager._token_cache.values():
                            if token.address == input_mint:
                                token_decimals = token.decimals
                                logger.debug(f"✅ Found token decimals for {input_mint[:8]}...: {token_decimals}")
                                break
                    
                    # If not found in cache, try direct database lookup
                    if token_decimals == 6 and self.db_manager:
                        token_info = self.db_manager.get_token_by_address(input_mint)
                        if token_info:
                            token_decimals = token_info.decimals
                            logger.debug(f"✅ Found token decimals via DB lookup: {token_decimals}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Failed to get token decimals for {input_mint}: {e}")
                    # Use default 6 decimals
                
                amount_in_smallest_unit = int(amount_tokens * (10 ** token_decimals))
                logger.debug(f"🔥 SELL trade: {amount_tokens} tokens = {amount_in_smallest_unit} smallest units ({token_decimals} decimals)")
            
            # Get Jupiter quote (this will record the operation in database)
            # Get vault authority PDA as payer for the quote
            vault_authority_pda = str(self.vault_client._get_vault_authority_pda()) if self.vault_client else None
            
            quote = await self.jupiter_client.get_quote(
                input_mint=input_mint,
                output_mint=output_mint,
                amount=amount_in_smallest_unit,
                slippage_bps=slippage_bps,
                payer_pubkey=vault_authority_pda
            )
            
            # Store Jupiter operation ID for trade linking
            if hasattr(self.jupiter_client, '_last_operation_id'):
                self._pending_jupiter_id = self.jupiter_client._last_operation_id
            
            if not quote or 'error' in quote:
                logger.error(f"❌ Jupiter quote failed: {quote}")
                return None
            
            # Validate quote
            expected_amount = amount_usdc if trade_type == 'buy' else amount_tokens
            if not self._validate_jupiter_quote(quote, expected_amount, trade_type):
                logger.error(f"❌ Jupiter quote validation failed")
                return None
            
            # Get swap instruction data using Node.js bridge
            # ✅ CRITICAL FIX: Use vault authority PDA for Jupiter instruction generation
            # The vault program will handle the signing via CPI with PDA seeds
            vault_authority_pda = str(self.vault_client._get_vault_authority_pda()) if self.vault_client else "6tMyF1Q5GScmXCJGSgpsKQtMPSPgkREwWuWWNspcmV8U"
            swap_data = await self.jupiter_client.get_swap_transaction(
                quote, 
                vault_authority_pda,  # Vault authority PDA (will sign via CPI)
                slippage_bps
            )
            
            if not swap_data or not swap_data.get('sdk_generated'):
                logger.error(f"❌ Failed to generate Jupiter instruction via Node.js bridge")
                return None
            
            trade_direction = f"{amount_usdc} USDC → {output_mint}" if trade_type == 'buy' else f"{amount_tokens} tokens → USDC"
            logger.debug(f"✅ Created Jupiter {trade_type.upper()} trade via Node.js bridge: {trade_direction}")
            logger.debug(f"  - Generated {len(swap_data.get('accounts', []))} accounts")
            logger.debug(f"  - Instruction data: {len(swap_data.get('instruction_data', ''))} chars")
            
            return swap_data
            
        except Exception as e:
            logger.error(f"❌ Jupiter trade creation failed: {e}")
            return None

    def _simulate_jupiter_trade(self, symbol: str, amount: float, trade_type: str = 'buy') -> str:
        """Simulate Jupiter trade creation for testing"""
        if trade_type == 'buy':
            logger.info(f"📝 Simulating Jupiter BUY trade: ${amount} USDC → {symbol}")
            return f"JUPITER_SIM_BUY_{symbol}_{int(amount)}_{int(time.time())}"
        else:
            logger.info(f"📝 Simulating Jupiter SELL trade: {amount} {symbol} → USDC")
            return f"JUPITER_SIM_SELL_{symbol}_{int(amount)}_{int(time.time())}"

    async def _simulate_vault_execution(self, symbol: str, allocation: AssetAllocation, trade_type: str = 'buy') -> str:
        """Simulate vault execution for testing"""
        logger.info(f"📝 Simulating vault execution: {symbol} {trade_type.upper()} trade")
        await asyncio.sleep(0.1)  # Simulate network delay
        
        if trade_type == 'buy':
            return f"SIM_BUY_{symbol}_{int(allocation.position_value_usdc)}_{int(time.time())}"
        else:
            return f"SIM_SELL_{symbol}_{int(time.time())}"

    def _validate_trade_size(self, trade_size_usdc: float) -> bool:
        """Validate trade size is within acceptable limits"""
        # No artificial limits - portfolio coordinator handles sizing intelligently
        return trade_size_usdc > 0

    def _validate_jupiter_quote(self, quote: Dict, expected_amount: float, trade_type: str = 'buy') -> bool:
        """Validate Jupiter quote is reasonable for both buy and sell trades"""
        try:
            # Check required fields
            if not all(key in quote for key in ['inAmount', 'outAmount']):
                return False
            
            # Check price impact is reasonable (<2% for our conservative approach)
            price_impact = float(quote.get('priceImpactPct', 0))
            if abs(price_impact) > 2.0:  # 2% max price impact
                logger.warning(f"⚠️ High price impact: {price_impact}%")
                return False
            
            # Check input amount matches expected (validation differs by trade type)
            input_amount = int(quote['inAmount'])
            
            if trade_type == 'buy':
                # For buys: expected_amount is in USDC, convert to micro-USDC
                expected_micro_usdc = int(expected_amount * 1e6)
                if abs(input_amount - expected_micro_usdc) > expected_micro_usdc * 0.01:  # 1% tolerance
                    logger.warning(f"⚠️ BUY input amount mismatch: {input_amount} vs {expected_micro_usdc}")
                    return False
            else:
                # For sells: expected_amount is in tokens, need to get token decimals
                # This is more complex validation - for now, just check it's reasonable
                if input_amount <= 0:
                    logger.warning(f"⚠️ SELL input amount invalid: {input_amount}")
                    return False
                
                logger.debug(f"✅ SELL quote validated: input={input_amount}, expected≈{expected_amount}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Quote validation failed: {e}")
            return False

    async def _get_token_mint(self, symbol: str) -> Optional[str]:
        """Get token mint address from database"""
        try:
            if not self.db_manager:
                await self.initialize()
            
            # CRITICAL FIX: Handle event loop conflicts in token cache access
            try:
                # Get token info from cache only (avoid database queries)
                for token in self.db_manager._token_cache.values():
                    if token.symbol.upper() == symbol.upper():
                        return token.address
            except Exception as cache_error:
                logger.debug(f"Cache access failed for {symbol}: {cache_error}")
                
                # Fallback: Try direct database lookup with proper error handling
                try:
                    token_info = self.db_manager.get_token_by_symbol(symbol)
                    if token_info:
                        return token_info.address
                except Exception as db_error:
                    logger.warning(f"Database lookup failed for {symbol}: {db_error}")
            
            logger.error(f"❌ Token not found in cache or database for symbol: {symbol}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Failed to get token mint for {symbol}: {e}")
            return None

    async def _record_trade_execution(self, signal: TradingSignal, allocation: Optional[AssetAllocation],
                                    tx_sig: Optional[str], status: str, error: str = None, trade_type: str = 'buy') -> Optional[int]:
        """Record trade execution in database using enhanced trades table"""
        try:
            if not self.db_manager:
                return None
            
            # Get token_id from cache only (avoid database queries that cause event loop conflicts)
            token_info = None
            for token in self.db_manager._token_cache.values():
                if token.symbol.upper() == signal.symbol.upper():
                    token_info = token
                    break
            
            if not token_info:
                logger.error(f"❌ Token not found in cache for symbol: {signal.symbol}")
                return None
            
            token_id = token_info.token_id
            
            # Create enhanced trade data with vault-specific fields
            from ..database.production_db import TradeData
            
            # Calculate quantity and value based on trade type
            if trade_type == 'buy':
                if not allocation:
                    logger.error(f"❌ No allocation provided for BUY trade recording")
                    return None
                quantity = allocation.position_value_usdc / signal.current_price if signal.current_price > 0 else 0.0
                value_usdc = allocation.position_value_usdc
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
                slippage_bps=self.max_slippage_bps,
                dex_name='jupiter',
                processing_time_ms=int(self.execution_times[-1]) if self.execution_times else None,
                
                # NEW: Vault-specific fields
                signal_confidence=signal.confidence * 100 if signal.confidence <= 1.0 else signal.confidence,  # Convert 0-1 to 0-100 scale
                model_version=signal.model_version,
                signal_strength=(signal.strength.value if hasattr(signal.strength, 'value') else str(signal.strength)).upper(),
                predicted_change_pct=signal.predicted_change_pct,
                cycle_timestamp=datetime.utcnow(),
                jupiter_operation_id=getattr(self, '_pending_jupiter_id', None)
            )
            
            # Record in enhanced trades table with event loop safe approach
            trade_id = None
            if status in ["pending", "confirmed", True]:  # Record for pending, confirmed, or legacy True
                try:
                    # Try with existing db_manager first
                    trade_id = await self.db_manager.record_trade(trade_data)
                    logger.debug(f"✅ Recorded trade {trade_id} in database")
                    
                    # Store trade_id for Jupiter operation linking
                    trade_data.trade_id = trade_id
                    
                    # Link Jupiter operation if pending
                    if hasattr(self, '_pending_jupiter_id') and self._pending_jupiter_id:
                        await self.db_manager.update_trade_jupiter_operation(trade_id, self._pending_jupiter_id)
                        logger.debug(f"✅ Linked trade {trade_id} to Jupiter operation {self._pending_jupiter_id}")
                        delattr(self, '_pending_jupiter_id')  # Clear pending ID
                        
                except Exception as db_error:
                    if "attached to a different loop" in str(db_error) or "another operation is in progress" in str(db_error):
                        # Event loop conflict - create new connection for current loop
                        logger.debug("Event loop conflict detected, creating new DB connection for trade recording")
                        try:
                            from ..database.production_db import ProductionDBManager
                            
                            # Create a new DB manager for this event loop
                            temp_db_manager = ProductionDBManager()
                            await temp_db_manager.initialize()
                            
                            try:
                                # Record using the new connection
                                trade_id = await temp_db_manager.record_trade(trade_data)
                                logger.debug(f"✅ Recorded trade {trade_id} in database (new connection)")
                                
                                # Store trade_id for Jupiter operation linking
                                trade_data.trade_id = trade_id
                                
                            finally:
                                # Clean up temporary connection
                                await temp_db_manager.close()
                                
                        except Exception as temp_error:
                            logger.error(f"❌ Failed to record trade with new connection: {temp_error}")
                            # Continue without recording - don't fail the whole trade
                    else:
                        # Different error - re-raise
                        raise
            
            # Store in trade history for statistics
            self.trade_history.append({
                'symbol': signal.symbol,
                'signal_type': trade_type,  # Now tracks both 'buy' and 'sell'
                'confidence': signal.confidence,
                'amount_usdc': allocation.position_value_usdc if (allocation and trade_type == 'buy') else 0,  # 0 for sells since we don't know USD value yet
                'tx_signature': tx_sig,
                'success': status in ["confirmed", True],  # Convert status to boolean for compatibility
                'status': status,
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
            logger.error(f"❌ Failed to record trade execution: {e}")
            return None

    def get_execution_stats(self) -> Dict[str, Any]:
        """Get trade execution performance statistics"""
        return {
            'total_trades': len(self.trade_history),
            'successful_trades': sum(1 for t in self.trade_history if t['success']),
            'avg_execution_time_ms': sum(self.execution_times) / len(self.execution_times) if self.execution_times else 0,
            'recent_trades': self.trade_history[-10:] if self.trade_history else [],
            'max_slippage_bps': self.max_slippage_bps,
            'vault_client_available': self.vault_client is not None,
            'jupiter_client_available': self.jupiter_client is not None,
            'trade_verifier_available': self.trade_verifier is not None
        }

    async def get_performance_report(self) -> Dict[str, Any]:
        """Get comprehensive performance report"""
        try:
            stats = self.get_execution_stats()
            
            # Add database-based metrics if available
            if self.db_manager:
                from datetime import timedelta
                end_time = datetime.utcnow()
                start_time = end_time - timedelta(hours=24)
                
                db_summary = await self.db_manager.get_trading_performance_summary(start_time, end_time)
                stats.update({
                    'db_metrics': db_summary,
                    'verification_stats': await self.trade_verifier.get_stats() if self.trade_verifier else None
                })
            
            return stats
            
        except Exception as e:
            logger.error(f"❌ Failed to generate performance report: {e}")
            return self.get_execution_stats()

    async def verify_recent_trades(self, hours_back: int = 1) -> Dict[str, Any]:
        """Manually trigger verification of recent trades"""
        try:
            if not self.trade_verifier:
                return {'error': 'Trade verifier not available'}
            
            results = await self.trade_verifier.verify_pending_trades(hours_back)
            
            return {
                'trades_verified': len(results),
                'confirmed': sum(1 for r in results if r.final_status == 'confirmed'),
                'failed': sum(1 for r in results if r.final_status == 'failed'),
                'timeout': sum(1 for r in results if r.final_status == 'timeout'),
                'results': [
                    {
                        'trade_id': r.trade_id,
                        'tx_hash': r.tx_hash[:12] + '...',
                        'status': r.final_status,
                        'error': r.execution_error or r.verification_error
                    }
                    for r in results
                ]
            }
            
        except Exception as e:
            logger.error(f"❌ Manual trade verification failed: {e}")
            return {'error': str(e)} 