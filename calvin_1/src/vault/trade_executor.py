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
        Execute all buy signals from portfolio coordinator
        
        Args:
            portfolio_signal: Portfolio signal with buy/sell recommendations
            
        Returns:
            List of transaction signatures (or simulation IDs)
        """
        results = []
        
        try:
            logger.info(f"🎯 Processing portfolio signal: {len(portfolio_signal.buy_signals)} buy signals")
            
            # Validate vault state before trading (if vault client available)
            if self.vault_client:
                vault_state = await self.vault_client.get_vault_state()
                if vault_state.get('paused', True):
                    logger.warning("⚠️ Vault is paused, skipping trades")
                    return results
            else:
                logger.info("📝 Running in simulation mode (no vault client)")
            
            # Execute buy signals only (selling handled separately)
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
                    logger.info(f"🚀 Executing trade {i+1}/{len(portfolio_signal.buy_signals)}: {buy_signal.symbol}")
                    tx_sig = await self.execute_single_trade(buy_signal, allocation)
                    
                    if tx_sig:
                        results.append(tx_sig)
                        
                        # Record successful trade and get trade_id
                        trade_id = await self._record_trade_execution(buy_signal, allocation, tx_sig, True)
                        logger.info(f"✅ Trade executed: {buy_signal.symbol} - {tx_sig[:12]}...")
                        
                        # Schedule verification (async, don't wait)
                        if trade_id and self.trade_verifier and not tx_sig.startswith('SIM_'):
                            asyncio.create_task(self._verify_trade_async(trade_id, tx_sig))
                    else:
                        # Record failed trade
                        await self._record_trade_execution(buy_signal, allocation, None, False)
                        logger.warning(f"❌ Trade failed: {buy_signal.symbol}")
                        
                except Exception as e:
                    logger.error(f"❌ Failed to execute trade for {buy_signal.symbol}: {e}")
                    await self._record_trade_execution(buy_signal, allocation, None, False, str(e))
            
            success_rate = len(results) / len(portfolio_signal.buy_signals) if portfolio_signal.buy_signals else 0
            logger.info(f"🏁 Portfolio execution completed: {len(results)}/{len(portfolio_signal.buy_signals)} trades successful ({success_rate:.1%})")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Portfolio trade execution failed: {e}")
            return results

    async def _verify_trade_async(self, trade_id: int, tx_hash: str):
        """Asynchronously verify trade execution (don't block main flow)"""
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

    async def execute_single_trade(self, signal: TradingSignal, allocation: AssetAllocation) -> Optional[str]:
        """
        Execute a single trade through the vault (or simulate)
        
        Args:
            signal: Trading signal with prediction and confidence
            allocation: Asset allocation with position sizing
            
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
            
            # 2. Create Jupiter swap data (or simulate)
            if self.jupiter_client:
                jupiter_data = await self.create_jupiter_trade(
                    input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                    output_mint=token_mint,
                    amount_usdc=allocation.position_value_usdc,
                    slippage_bps=self.max_slippage_bps
                )
            else:
                # Simulate Jupiter data creation
                jupiter_data = self._simulate_jupiter_trade(signal.symbol, allocation.position_value_usdc)
            
            if not jupiter_data:
                logger.error(f"❌ Failed to create Jupiter trade data for {signal.symbol}")
                return None
            
            # 3. Execute through vault smart contract (or simulate)
            if self.vault_client:
                tx_sig = await self.vault_client.execute_trade(
                    jupiter_data=jupiter_data,
                    source_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                    destination_mint=token_mint,  # target token
                    amount_usdc=allocation.position_value_usdc
                )
            else:
                # Simulate vault execution
                tx_sig = await self._simulate_vault_execution(signal.symbol, allocation)
            
            execution_time = (time.time() - start_time) * 1000
            self.execution_times.append(execution_time)
            
            if tx_sig:
                logger.info(f"✅ Executed trade for {signal.symbol}: ${allocation.position_value_usdc} USDC in {execution_time:.1f}ms")
                logger.info(f"   Transaction: {tx_sig}")
            
            return tx_sig
            
        except Exception as e:
            logger.error(f"❌ Single trade execution failed for {signal.symbol}: {e}")
            return None

    async def create_jupiter_trade(self, input_mint: str, output_mint: str, 
                                 amount_usdc: float, slippage_bps: int = 50) -> Optional[Dict]:
        """
        Create Jupiter swap transaction data for vault execution
        
        Args:
            input_mint: Input token mint (USDC)
            output_mint: Output token mint (target token)
            amount_usdc: Amount in USDC to trade
            slippage_bps: Maximum slippage in basis points
            
        Returns:
            Jupiter swap data for vault execution
        """
        try:
            # Convert USDC to micro-USDC (6 decimals)
            amount_micro_usdc = int(amount_usdc * 1e6)
            
            # Get Jupiter quote (this will record the operation in database)
            # Get vault authority PDA as payer for the quote
            vault_authority_pda = str(self.vault_client._get_vault_authority_pda()) if self.vault_client else None
            
            quote = await self.jupiter_client.get_quote(
                input_mint=input_mint,
                output_mint=output_mint,
                amount=amount_micro_usdc,
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
            if not self._validate_jupiter_quote(quote, amount_usdc):
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
            
            logger.debug(f"✅ Created Jupiter trade via Node.js bridge: {amount_usdc} USDC → {output_mint}")
            logger.debug(f"  - Generated {len(swap_data.get('accounts', []))} accounts")
            logger.debug(f"  - Instruction data: {len(swap_data.get('instruction_data', ''))} chars")
            
            return swap_data
            
        except Exception as e:
            logger.error(f"❌ Jupiter trade creation failed: {e}")
            return None

    def _simulate_jupiter_trade(self, symbol: str, amount_usdc: float) -> str:
        """Simulate Jupiter trade creation for testing"""
        logger.info(f"📝 Simulating Jupiter trade: ${amount_usdc} USDC → {symbol}")
        return f"JUPITER_SIM_{symbol}_{int(amount_usdc)}_{int(time.time())}"

    async def _simulate_vault_execution(self, symbol: str, allocation: AssetAllocation) -> str:
        """Simulate vault execution for testing"""
        logger.info(f"📝 Simulating vault execution: {symbol} trade")
        await asyncio.sleep(0.1)  # Simulate network delay
        return f"SIM_{symbol}_{int(allocation.position_value_usdc)}_{int(time.time())}"

    def _validate_trade_size(self, trade_size_usdc: float) -> bool:
        """Validate trade size is within acceptable limits"""
        # No artificial limits - portfolio coordinator handles sizing intelligently
        return trade_size_usdc > 0

    def _validate_jupiter_quote(self, quote: Dict, expected_amount_usdc: float) -> bool:
        """Validate Jupiter quote is reasonable"""
        try:
            # Check required fields
            if not all(key in quote for key in ['inAmount', 'outAmount']):
                return False
            
            # Check price impact is reasonable (<2% for our conservative approach)
            price_impact = float(quote.get('priceImpactPct', 0))
            if abs(price_impact) > 2.0:  # 2% max price impact
                logger.warning(f"⚠️ High price impact: {price_impact}%")
                return False
            
            # Check input amount matches expected
            input_amount = int(quote['inAmount'])
            expected_micro_usdc = int(expected_amount_usdc * 1e6)
            
            if abs(input_amount - expected_micro_usdc) > expected_micro_usdc * 0.01:  # 1% tolerance
                logger.warning(f"⚠️ Input amount mismatch: {input_amount} vs {expected_micro_usdc}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Quote validation failed: {e}")
            return False

    async def _get_token_mint(self, symbol: str) -> Optional[str]:
        """Get token mint address from database"""
        try:
            if not self.db_manager:
                await self.initialize()
            
            token_info = await self.db_manager.get_token_by_symbol(symbol)
            return token_info['address'] if token_info else None
            
        except Exception as e:
            logger.error(f"❌ Failed to get token mint for {symbol}: {e}")
            return None

    async def _record_trade_execution(self, signal: TradingSignal, allocation: AssetAllocation,
                                    tx_sig: Optional[str], success: bool, error: str = None) -> Optional[int]:
        """Record trade execution in database using enhanced trades table"""
        try:
            if not self.db_manager:
                return None
            
            # Get token_id
            token_info = await self.db_manager.get_token_by_symbol(signal.symbol)
            if not token_info:
                logger.error(f"❌ Token not found for symbol: {signal.symbol}")
                return None
            
            # Create enhanced trade data with vault-specific fields
            from ..database.production_db import TradeData
            
            trade_data = TradeData(
                token_id=token_info['token_id'],
                trade_type='buy',
                price=signal.current_price,
                quantity=allocation.position_value_usdc / signal.current_price if signal.current_price > 0 else 0.0,
                value_usdc=allocation.position_value_usdc if allocation else 0.0,
                fee_usdc=0.0,  # Will be updated after verification
                tx_hash=tx_sig or '',
                execution_time=datetime.utcnow(),
                slippage_bps=self.max_slippage_bps,
                dex_name='jupiter',
                processing_time_ms=int(self.execution_times[-1]) if self.execution_times else None,
                
                # NEW: Vault-specific fields
                signal_confidence=signal.confidence * 100 if signal.confidence <= 1.0 else signal.confidence,  # Convert 0-1 to 0-100 scale
                model_version=signal.model_version,
                signal_strength=signal.strength.value if hasattr(signal.strength, 'value') else str(signal.strength),
                predicted_change_pct=signal.predicted_change_pct,
                cycle_timestamp=datetime.utcnow(),
                jupiter_operation_id=getattr(self, '_pending_jupiter_id', None)
            )
            
            # Record in enhanced trades table
            trade_id = None
            if success and self.db_manager:
                trade_id = await self.db_manager.record_trade(trade_data)
                logger.debug(f"✅ Recorded trade {trade_id} in database")
                
                # Store trade_id for Jupiter operation linking
                trade_data.trade_id = trade_id
                
                # Link Jupiter operation if pending
                if hasattr(self, '_pending_jupiter_id') and self._pending_jupiter_id:
                    await self.db_manager.update_trade_jupiter_operation(trade_id, self._pending_jupiter_id)
                    logger.debug(f"✅ Linked trade {trade_id} to Jupiter operation {self._pending_jupiter_id}")
                    delattr(self, '_pending_jupiter_id')  # Clear pending ID
            
            # Store in trade history for statistics
            self.trade_history.append({
                'symbol': signal.symbol,
                'signal_type': 'buy',
                'confidence': signal.confidence,
                'amount_usdc': allocation.position_value_usdc if allocation else 0,
                'tx_signature': tx_sig,
                'success': success,
                'error': error,
                'execution_time': datetime.utcnow(),
                'predicted_change_pct': signal.predicted_change_pct,
                'model_version': signal.model_version,
                'trade_id': trade_id,
                'amount_usdc': allocation.position_value_usdc if allocation else 0
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