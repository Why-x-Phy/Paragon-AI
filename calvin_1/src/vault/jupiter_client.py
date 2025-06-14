"""
Jupiter V6 Client

Handles integration with Jupiter V6 API for quote generation and swap transaction creation.
Provides the interface that VaultTradeExecutor expects for creating swap data.

Phase 3.3 Implementation:
- Get quotes from Jupiter V6 API
- Create swap transaction data for vault execution  
- Handle API errors and rate limiting gracefully
- Validate quotes and provide debugging information
"""

import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Optional, Any
from datetime import datetime

from ..config.config import config
from ..utils.logger import log

logger = log

class JupiterV6Client:
    """
    Jupiter V6 API client for quote generation and swap transaction creation
    """
    
    def __init__(self):
        self.base_url = "https://quote-api.jup.ag/v6"
        self.session = None
        self.db_manager = None
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 0.1  # 100ms between requests
        
        # Performance tracking
        self.request_count = 0
        self.error_count = 0
        self.total_response_time = 0
        
        # Configuration
        self.timeout = config.get('JUPITER_TIMEOUT_SECONDS', 30)
        self.max_retries = config.get('JUPITER_MAX_RETRIES', 3)
        
        logger.info("Jupiter V6 Client initialized")

    async def initialize(self):
        """Initialize async session and database connection"""
        if not self.session:
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=10)
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={'User-Agent': 'Calvin-AI-Trading-Bot/1.0'}
            )
            logger.info("Jupiter V6 Client session initialized")
        
        # Initialize database manager for operation tracking
        if not self.db_manager:
            try:
                from ..database.production_db import get_db_manager
                self.db_manager = await get_db_manager()
                logger.debug("Jupiter client database integration initialized")
            except Exception as e:
                logger.warning(f"Jupiter client database integration failed: {e}")
                self.db_manager = None

    async def close(self):
        """Close async session"""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("Jupiter V6 Client session closed")

    async def get_quote(self, input_mint: str, output_mint: str, amount: int, 
                       slippage_bps: int = 100) -> Optional[Dict]:
        """
        Get Jupiter quote for token swap
        
        Args:
            input_mint: Input token mint address (e.g., USDC)
            output_mint: Output token mint address (e.g., target token)
            amount: Amount in smallest token units (e.g., micro-USDC)
            slippage_bps: Slippage tolerance in basis points (100 = 1%)
            
        Returns:
            Quote dictionary or None if failed
        """
        await self._rate_limit()
        
        if not self.session:
            await self.initialize()
        
        url = f"{self.base_url}/quote"
        params = {
            'inputMint': input_mint,
            'outputMint': output_mint,
            'amount': str(amount),
            'slippageBps': str(slippage_bps),
            'onlyDirectRoutes': 'false',
            'asLegacyTransaction': 'false',
            'platformFeeBps': '0',  # No platform fees
            'maxAccounts': '20'  # Reasonable limit for transaction size
        }
        
        start_time = time.time()
        
        for attempt in range(self.max_retries):
            try:
                self.request_count += 1
                
                async with self.session.get(url, params=params) as response:
                    response_time = (time.time() - start_time) * 1000
                    self.total_response_time += response_time
                    
                    if response.status == 200:
                        quote = await response.json()
                        
                        logger.debug(f"✅ Jupiter quote successful: {input_mint[:8]}...→{output_mint[:8]}... "
                                   f"(${amount/1e6:.0f} USDC) in {response_time:.1f}ms")
                        
                        # Validate quote structure
                        if self._validate_quote_structure(quote):
                            # Record successful quote operation
                            await self._record_jupiter_operation(
                                operation_type='quote',
                                input_mint=input_mint,
                                output_mint=output_mint,
                                input_amount=amount,
                                output_amount=int(quote.get('outAmount', 0)),
                                slippage_bps=slippage_bps,
                                price_impact_pct=float(quote.get('priceImpactPct', 0)),
                                route_plan=quote.get('routePlan'),
                                success=True,
                                execution_time_ms=int(response_time)
                            )
                            return quote
                        else:
                            logger.error("❌ Invalid quote structure received from Jupiter")
                            # Record failed quote operation
                            await self._record_jupiter_operation(
                                operation_type='quote',
                                input_mint=input_mint,
                                output_mint=output_mint,
                                input_amount=amount,
                                slippage_bps=slippage_bps,
                                success=False,
                                error_message="Invalid quote structure",
                                execution_time_ms=int(response_time)
                            )
                            return None
                    
                    elif response.status == 429:  # Rate limited
                        wait_time = 2 ** attempt  # Exponential backoff
                        logger.warning(f"⏸️ Jupiter rate limited, waiting {wait_time}s (attempt {attempt + 1})")
                        await asyncio.sleep(wait_time)
                        continue
                    
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Jupiter API error {response.status}: {error_text}")
                        self.error_count += 1
                        
                        if response.status >= 500:  # Server error, retry
                            await asyncio.sleep(1)
                            continue
                        else:  # Client error, don't retry
                            return None
                            
            except asyncio.TimeoutError:
                logger.error(f"⏰ Jupiter API timeout (attempt {attempt + 1})")
                self.error_count += 1
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                    
            except Exception as e:
                logger.error(f"❌ Jupiter API request failed: {e} (attempt {attempt + 1})")
                self.error_count += 1
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1)
                    continue
        
        logger.error(f"❌ Jupiter quote failed after {self.max_retries} attempts")
        return None

    async def get_swap_transaction(self, quote: Dict, user_public_key: str = None) -> Optional[Dict]:
        """
        Get swap transaction data and accounts from Jupiter quote
        
        Args:
            quote: Quote object from get_quote()
            user_public_key: User's public key (optional, can use vault authority)
            
        Returns:
            Dict containing:
            - 'transaction_data': base64 encoded transaction
            - 'accounts': List of account addresses Jupiter needs
            - 'instructions': Parsed instruction data
        """
        await self._rate_limit()
        
        if not self.session:
            await self.initialize()
        
        url = f"{self.base_url}/swap"
        
        # Use vault authority if no user key provided
        if not user_public_key:
            user_public_key = config.get('CALVIN_VAULT_AUTHORITY_PUBKEY', '')
            if not user_public_key:
                logger.error("❌ No user public key provided and no vault authority configured")
                return None
        
        payload = {
            'quoteResponse': quote,
            'userPublicKey': user_public_key,
            'wrapAndUnwrapSol': True,
            'useSharedAccounts': True,
            'feeAccount': None,  # No additional fees
            'computeUnitPriceMicroLamports': 'auto'  # Let Jupiter optimize
        }
        
        start_time = time.time()
        
        for attempt in range(self.max_retries):
            try:
                self.request_count += 1
                
                async with self.session.post(url, json=payload) as response:
                    response_time = (time.time() - start_time) * 1000
                    self.total_response_time += response_time
                    
                    if response.status == 200:
                        swap_data = await response.json()
                        transaction_data = swap_data.get('swapTransaction')
                        
                        if transaction_data:
                            # Extract accounts from the transaction
                            accounts = await self._extract_accounts_from_transaction(transaction_data)
                            
                            logger.debug(f"✅ Jupiter swap transaction created in {response_time:.1f}ms")
                            logger.debug(f"📋 Extracted {len(accounts)} accounts for vault integration")
                            
                            return {
                                'transaction_data': transaction_data,  # Keep as base64 string
                                'accounts': accounts,
                                'quote': quote
                            }
                        else:
                            logger.error("❌ No swap transaction data in Jupiter response")
                            return None
                    
                    elif response.status == 429:  # Rate limited
                        wait_time = 2 ** attempt
                        logger.warning(f"⏸️ Jupiter swap rate limited, waiting {wait_time}s (attempt {attempt + 1})")
                        await asyncio.sleep(wait_time)
                        continue
                    
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Jupiter swap API error {response.status}: {error_text}")
                        self.error_count += 1
                        
                        if response.status >= 500:  # Server error, retry
                            await asyncio.sleep(1)
                            continue
                        else:  # Client error, don't retry
                            return None
                            
            except Exception as e:
                logger.error(f"❌ Jupiter swap request failed: {e} (attempt {attempt + 1})")
                self.error_count += 1
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1)
                    continue
        
        logger.error(f"❌ Jupiter swap transaction failed after {self.max_retries} attempts")
        return None

    async def _extract_accounts_from_transaction(self, transaction_data: str) -> List[str]:
        """
        Extract account addresses from Jupiter transaction data
        
        This is CRITICAL for vault integration - we need to know all accounts
        that Jupiter will access so we can include them in our vault instruction.
        
        Args:
            transaction_data: Base64 encoded transaction from Jupiter
            
        Returns:
            List of account addresses as strings
        """
        try:
            import base64
            from solders.transaction import VersionedTransaction
            
            # Decode the base64 transaction
            tx_bytes = base64.b64decode(transaction_data)
            
            # Deserialize the transaction
            tx = VersionedTransaction.from_bytes(tx_bytes)
            
            # Extract account keys from the message
            accounts = []
            if hasattr(tx.message, 'account_keys'):
                # For MessageV0, account_keys contains the accounts
                accounts = [str(key) for key in tx.message.account_keys]
                logger.debug(f"📋 Extracted {len(accounts)} accounts from Jupiter transaction")
                
                # Log first few accounts for debugging (without exposing full addresses)
                if accounts:
                    sample_accounts = [acc[:8] + "..." for acc in accounts[:3]]
                    logger.debug(f"🔍 Sample accounts: {sample_accounts}")
                
                return accounts
            else:
                logger.warning("⚠️ Could not extract accounts from transaction message")
                return []
                
        except Exception as e:
            logger.error(f"❌ Failed to extract accounts from transaction: {e}")
            return []

    async def _record_jupiter_operation(self, operation_type: str, input_mint: str, output_mint: str,
                                       input_amount: int, output_amount: int = None, slippage_bps: int = None,
                                       price_impact_pct: float = None, route_plan: Dict = None,
                                       success: bool = False, error_message: str = None,
                                       execution_time_ms: int = None, tx_signature: str = None,
                                       trade_id: int = None) -> Optional[int]:
        """Record Jupiter operation in database"""
        try:
            if not self.db_manager:
                return None
            
            from ..database.production_db import JupiterOperationData
            
            operation = JupiterOperationData(
                operation_timestamp=datetime.utcnow(),
                operation_type=operation_type,
                input_mint=input_mint,
                output_mint=output_mint,
                input_amount=input_amount,
                output_amount=output_amount,
                slippage_bps=slippage_bps or 0,
                actual_output_amount=None,
                price_impact_pct=price_impact_pct,
                fee_amount=None,
                fee_mint=None,
                route_plan=route_plan,
                market_infos=None,
                tx_hash=tx_signature,
                success=success,
                error_message=error_message,
                quote_response_time_ms=execution_time_ms,
                swap_execution_time_ms=None
            )
            
            operation_id = await self.db_manager.record_jupiter_operation(operation)
            logger.debug(f"✅ Recorded Jupiter {operation_type} operation {operation_id}")
            
            # Store last operation ID for trade linking
            self._last_operation_id = operation_id
            
            return operation_id
            
        except Exception as e:
            logger.error(f"❌ Failed to record Jupiter operation: {e}")
            return None

    def _validate_quote_structure(self, quote: Dict) -> bool:
        """Validate that quote has required fields"""
        required_fields = ['inAmount', 'outAmount', 'priceImpactPct', 'routePlan']
        
        for field in required_fields:
            if field not in quote:
                logger.error(f"❌ Missing required field in Jupiter quote: {field}")
                return False
        
        # Validate route plan structure
        route_plan = quote.get('routePlan', [])
        if not isinstance(route_plan, list) or len(route_plan) == 0:
            logger.error("❌ Invalid or empty route plan in Jupiter quote")
            return False
        
        return True

    async def _rate_limit(self):
        """Simple rate limiting to avoid overwhelming Jupiter API"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            await asyncio.sleep(sleep_time)
        
        self.last_request_time = time.time()

    def get_stats(self) -> Dict[str, Any]:
        """Get client performance statistics"""
        avg_response_time = (
            self.total_response_time / self.request_count 
            if self.request_count > 0 else 0
        )
        
        success_rate = (
            (self.request_count - self.error_count) / self.request_count 
            if self.request_count > 0 else 0
        )
        
        return {
            'total_requests': self.request_count,
            'total_errors': self.error_count,
            'success_rate': success_rate,
            'avg_response_time_ms': avg_response_time,
            'session_active': self.session is not None
        }

    async def health_check(self) -> bool:
        """Simple health check - try to get a quote for a known pair"""
        try:
            # Test with a small USDC → SOL quote
            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            sol_mint = "So11111111111111111111111111111111111111112"
            test_amount = 1000000  # $1 USDC
            
            quote = await self.get_quote(usdc_mint, sol_mint, test_amount, 100)
            
            if quote:
                logger.debug("✅ Jupiter health check passed")
                return True
            else:
                logger.warning("⚠️ Jupiter health check failed - no quote received")
                return False
                
        except Exception as e:
            logger.error(f"❌ Jupiter health check error: {e}")
            return False

    def __del__(self):
        """Cleanup on destruction"""
        if self.session and not self.session.closed:
            logger.warning("⚠️ JupiterV6Client session not properly closed") 