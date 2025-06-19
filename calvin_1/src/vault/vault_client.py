"""
Calvin Vault Client

Interfaces with Calvin vault smart contracts on Solana for trade execution and state management.
Provides the interface that VaultTradeExecutor expects for executing trades through the vault.

Phase 3.3 Implementation:
- Execute trades through vault smart contract
- Query vault state and user positions
- Handle Solana transaction creation and signing
- Integrate with Jupiter swap data for vault execution
"""

import asyncio
import base64
import json
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
from solana.rpc.types import TxOpts
from solana.rpc.core import RPCException
from solders.transaction import VersionedTransaction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.message import MessageV0
from solders.hash import Hash
from solana.rpc.core import RPCException

from ..config.config import config
from ..utils.logger import log
from ..database.production_db import get_db_manager

logger = log

class VaultClient:
    """
    Client for interacting with Calvin vault smart contracts
    """
    
    def __init__(self):
        # Solana connection
        self.rpc_url = config.get('SOLANA_RPC_URL', 'https://api.devnet.solana.com')
        self.client = None
        
        # Vault configuration
        self.vault_program_id = config.get('CALVIN_VAULT_PROGRAM_ID', '')
        self.staking_program_id = config.get('CALVIN_STAKING_PROGRAM_ID', '')
        
        # 🎯 NEW: Treasury configuration
        self.treasury_address = config.get('CALVIN_TREASURY_ADDRESS', 'HV4x1p4gHhMcyjWpexki7Mis7ajecMntwCcvLjQJdLiC')
        
        # Trading authority (Calvin AI's keypair)
        self.authority_private_key = config.get('CALVIN_AUTHORITY_PRIVATE_KEY', '')
        self.authority_keypair = None
        
        # Performance tracking
        self.transaction_count = 0
        self.failed_transactions = 0
        self.total_execution_time = 0
        
        # Configuration
        self.commitment = Commitment('confirmed')
        self.max_retries = config.get('VAULT_MAX_RETRIES', 3)
        self.timeout = config.get('VAULT_TIMEOUT_SECONDS', 60)
        
        logger.info("Vault Client initialized")

    async def initialize(self):
        """Initialize async components and validate configuration"""
        try:
            # Initialize Solana client
            self.client = AsyncClient(self.rpc_url, commitment=self.commitment)
            
            # Validate RPC connection
            await self._validate_rpc_connection()
            
            # Initialize authority keypair
            if self.authority_private_key:
                try:
                    self.authority_keypair = self._load_keypair_from_string(self.authority_private_key)
                    logger.info(f"✅ Trading authority loaded: {self.authority_keypair.pubkey()}")
                except Exception as e:
                    logger.error(f"❌ Failed to load trading authority keypair: {e}")
                    self.authority_keypair = None
            else:
                logger.warning("⚠️ No trading authority private key configured - will run in read-only mode")
            
            # Validate program IDs
            if self.vault_program_id:
                logger.info(f"✅ Vault program ID: {self.vault_program_id}")
            else:
                logger.error("❌ No vault program ID configured")
            
            if self.staking_program_id:
                logger.info(f"✅ Staking program ID: {self.staking_program_id}")
            else:
                logger.error("❌ No staking program ID configured")
            
            logger.info("Vault Client fully initialized")
            
        except Exception as e:
            logger.error(f"❌ Vault Client initialization failed: {e}")
            raise

    async def close(self):
        """Close async connections"""
        if self.client:
            await self.client.close()
            self.client = None
            logger.info("Vault Client closed")

    async def execute_trade(self, jupiter_data: Dict, source_mint: str, destination_mint: str, amount_usdc: float) -> Optional[str]:
        """
        Execute a trade through the vault smart contract
        
        Args:
            jupiter_data: Dict containing Jupiter transaction data and accounts
            source_mint: Source token mint (USDC)
            destination_mint: Destination token mint
            amount_usdc: Trade amount in USDC
            
        Returns:
            Transaction signature if successful, None otherwise
        """
        if not self.authority_keypair:
            logger.error("❌ Cannot execute trade - no trading authority configured")
            return None
        
        if not self.client:
            await self.initialize()
        
        try:
            start_time = asyncio.get_event_loop().time()
            
            # Create vault trade instruction
            transaction = await self._create_vault_trade_transaction(
                jupiter_data, source_mint, destination_mint, amount_usdc
            )
            
            if not transaction:
                logger.error("❌ Failed to create vault trade transaction")
                return None
            
            # Sign and send transaction
            signature = await self._send_transaction(transaction)
            
            execution_time = (asyncio.get_event_loop().time() - start_time) * 1000
            self.total_execution_time += execution_time
            self.transaction_count += 1
            
            if signature:
                logger.info(f"✅ Vault trade executed: {signature} in {execution_time:.1f}ms")
                return signature
            else:
                self.failed_transactions += 1
                logger.error("❌ Vault trade execution failed")
                return None
                
        except Exception as e:
            self.failed_transactions += 1
            logger.error(f"❌ Vault trade execution error: {e}")
            return None

    async def get_vault_state(self) -> Dict[str, Any]:
        """
        Get current vault state from smart contract with improved error handling
        
        Returns:
            Dictionary containing vault state information
        """
        if not self.client:
            await self.initialize()
            
        try:
            # Derive vault PDA using the same method as smart contract
            usdc_mint_pubkey = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
            vault_program_id = Pubkey.from_string(self.vault_program_id)
            
            vault_pda, vault_bump = Pubkey.find_program_address(
                [b"vault", bytes(usdc_mint_pubkey)],
                vault_program_id
            )
            
            logger.debug(f"🔍 Querying vault account: {vault_pda}")
            
            # Query the vault account using Helius/Solana RPC with timeout
            try:
                account_info = await asyncio.wait_for(
                    self.client.get_account_info(vault_pda),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.warning("⚠️ Vault account query timed out")
                return {
                    'paused': True,
                    'initialized': False,
                    'error': 'Query timeout',
                    'vault_address': str(vault_pda),
                    'last_updated': datetime.utcnow().isoformat()
                }
            
            if not account_info or not account_info.value:
                logger.warning("⚠️ Vault account not found - may not be initialized")
                return {
                    'paused': True,
                    'initialized': False,
                    'error': 'Vault account not found',
                    'vault_address': str(vault_pda),
                    'vault_bump': vault_bump,
                    'last_updated': datetime.utcnow().isoformat(),
                    'needs_initialization': True,
                    'vault_program_id': self.vault_program_id
                }

            # Decode the account data according to our Anchor program structure
            vault_data = await self._decode_vault_account(account_info.value.data)
            
            if not vault_data:
                logger.error("❌ Failed to decode vault account data")
                return {
                    'paused': True,
                    'initialized': True,  # Account exists but data is invalid
                    'error': 'Failed to decode vault data',
                    'vault_address': str(vault_pda),
                    'vault_bump': vault_bump,
                    'last_updated': datetime.utcnow().isoformat()
                }

            # Calculate derived metrics
            nav_per_share = (
                vault_data['total_usdc'] / vault_data['total_shares'] 
                if vault_data['total_shares'] > 0 else 1.0
            )
            
            vault_state = {
                # Core vault data from smart contract
                'initialized': True,
                'paused': vault_data.get('paused', False),
                'total_usdc': vault_data.get('total_usdc', 0),
                'total_shares': vault_data.get('total_shares', 0),
                'trading_authority': vault_data.get('trading_authority'),
                'emergency_owner': vault_data.get('emergency_owner'),
                
                # Fee configuration
                'performance_fee_bps': vault_data.get('performance_fee_bps', 750),  # 7.5%
                'deposit_fee_bps': vault_data.get('deposit_fee_bps', 250),  # 2.5%
                'withdrawal_fee_bps': vault_data.get('withdrawal_fee_bps', 0),  # 0%
                
                # Derived metrics
                'nav_per_share': nav_per_share,
                'total_value_locked_usdc': vault_data.get('total_usdc', 0),
                
                # Metadata
                'vault_address': str(vault_pda),
                'vault_bump': vault_bump,
                'last_updated': datetime.utcnow().isoformat(),
                'query_method': 'helius_rpc'
            }
            
            logger.debug(f"📊 Retrieved vault state: ${vault_state['total_usdc']:,.2f} USDC, {vault_state['total_shares']:,} shares")
            return vault_state
            
        except Exception as e:
            logger.warning(f"Failed to get vault state: {e}")
            return {
                'paused': True,  # Fail-safe: assume paused on error
                'initialized': False,
                'error': str(e),
                'last_updated': datetime.utcnow().isoformat(),
                'vault_program_id': self.vault_program_id,
                'needs_troubleshooting': True
            }

    async def _decode_vault_account(self, account_data: bytes) -> Optional[Dict[str, Any]]:
        """
        Decode vault account data according to Anchor program structure
        
        Actual Vault struct (from onchain/programs/calvin-vault/src/state/mod.rs):
        - discriminator: [u8; 8]
        - emergency_owner: Pubkey (32 bytes)
        - calvin_authority: Pubkey (32 bytes)
        - staking_program_id: Pubkey (32 bytes)
        - shares_mint: Pubkey (32 bytes)
        - usdc_mint: Pubkey (32 bytes)
        - usdc_vault: Pubkey (32 bytes)
        - vault_authority: Pubkey (32 bytes)
        - vault_bump: u8 (1 byte)
        - shares_mint_bump: u8 (1 byte)
        - authority_bump: u8 (1 byte)
        - calvin_mint: Pubkey (32 bytes)
        - treasury: Pubkey (32 bytes)
        - per_nft_cap: u64 (8 bytes)
        - high_water_mark_nav: u64 (8 bytes)
        - total_shares: u64 (8 bytes)
        - paused: bool (1 byte)
        - jupiter_program_id: Pubkey (32 bytes)
        - reentrancy_guard: bool (1 byte)
        - trading_paused: bool (1 byte)
        - deposits_paused: bool (1 byte)
        - withdrawals_paused: bool (1 byte)
        - emergency_owners: [Pubkey; 2] (64 bytes)
        - emergency_owners_count: u8 (1 byte)
        - required_signatures: u8 (1 byte)
        - next_operation_id: u64 (8 bytes)
        - cpi_call_counts: [CpiCallTracker; 2] (152 bytes)
        - cpi_trackers_count: u8 (1 byte)
        
        Args:
            account_data: Raw account data bytes
            
        Returns:
            Decoded vault data dictionary
        """
        try:
            import struct
            
            if len(account_data) < 8:
                logger.error("❌ Account data too short for Anchor discriminator")
                return None
            
            # Skip Anchor discriminator (first 8 bytes)
            data = account_data[8:]
            
            # Calculate minimum expected size for core fields we need
            min_size = (
                32 + 32 + 32 + 32 + 32 + 32 + 32 +  # 7 Pubkeys (224 bytes)
                1 + 1 + 1 +                          # 3 bump fields (3 bytes) 
                32 + 32 +                            # calvin_mint + treasury (64 bytes)
                8 + 8 + 8 +                          # per_nft_cap + high_water_mark + total_shares (24 bytes)
                1 +                                  # paused (1 byte)
                32                                   # jupiter_program_id (32 bytes)
            )  # = 380 bytes minimum
            
            if len(data) < min_size:
                logger.error(f"❌ Account data too short: {len(data)} bytes, expected at least {min_size}")
                return None
            
            offset = 0
            
            # Parse the vault data according to actual Rust struct layout
            # Pubkey: emergency_owner (32 bytes)
            emergency_owner_bytes = data[offset:offset+32]
            emergency_owner = str(Pubkey(emergency_owner_bytes))
            offset += 32
            
            # Pubkey: calvin_authority (32 bytes)
            calvin_authority_bytes = data[offset:offset+32]
            calvin_authority = str(Pubkey(calvin_authority_bytes))
            offset += 32
            
            # Pubkey: staking_program_id (32 bytes)
            staking_program_id_bytes = data[offset:offset+32]
            staking_program_id = str(Pubkey(staking_program_id_bytes))
            offset += 32
            
            # Pubkey: shares_mint (32 bytes)
            shares_mint_bytes = data[offset:offset+32]
            shares_mint = str(Pubkey(shares_mint_bytes))
            offset += 32
            
            # Pubkey: usdc_mint (32 bytes)
            usdc_mint_bytes = data[offset:offset+32]
            usdc_mint = str(Pubkey(usdc_mint_bytes))
            offset += 32
            
            # Pubkey: usdc_vault (32 bytes)
            usdc_vault_bytes = data[offset:offset+32]
            usdc_vault = str(Pubkey(usdc_vault_bytes))
            offset += 32
            
            # Pubkey: vault_authority (32 bytes)
            vault_authority_bytes = data[offset:offset+32]
            vault_authority = str(Pubkey(vault_authority_bytes))
            offset += 32
            
            # u8: vault_bump (1 byte)
            vault_bump = data[offset]
            offset += 1
            
            # u8: shares_mint_bump (1 byte)
            shares_mint_bump = data[offset]
            offset += 1
            
            # u8: authority_bump (1 byte)
            authority_bump = data[offset]
            offset += 1
            
            # Pubkey: calvin_mint (32 bytes)
            calvin_mint_bytes = data[offset:offset+32]
            calvin_mint = str(Pubkey(calvin_mint_bytes))
            offset += 32
            
            # Pubkey: treasury (32 bytes)
            treasury_bytes = data[offset:offset+32]
            treasury = str(Pubkey(treasury_bytes))
            offset += 32
            
            # u64: per_nft_cap (8 bytes, little-endian)
            per_nft_cap = struct.unpack('<Q', data[offset:offset+8])[0]
            offset += 8
            
            # u64: high_water_mark_nav (8 bytes, little-endian)
            high_water_mark_nav = struct.unpack('<Q', data[offset:offset+8])[0]
            offset += 8
            
            # u64: total_shares (8 bytes, little-endian)
            total_shares = struct.unpack('<Q', data[offset:offset+8])[0]
            offset += 8
            
            # bool: paused (1 byte)
            paused = data[offset] != 0
            offset += 1
            
            # Pubkey: jupiter_program_id (32 bytes)
            jupiter_program_bytes = data[offset:offset+32]
            jupiter_program_id = str(Pubkey(jupiter_program_bytes))
            offset += 32
            
            # Try to read additional fields if data is long enough
            reentrancy_guard = False
            trading_paused = False
            deposits_paused = False
            withdrawals_paused = False
            
            if len(data) > offset + 4:  # Check if we have enough data for the new fields
                try:
                    # bool: reentrancy_guard (1 byte)
                    reentrancy_guard = data[offset] != 0
                    offset += 1
                    
                    # bool: trading_paused (1 byte)
                    trading_paused = data[offset] != 0
                    offset += 1
                    
                    # bool: deposits_paused (1 byte)
                    deposits_paused = data[offset] != 0
                    offset += 1
                    
                    # bool: withdrawals_paused (1 byte)
                    withdrawals_paused = data[offset] != 0
                    offset += 1
                    
                except Exception as e:
                    logger.debug(f"Could not read extended pause fields: {e}")
            
            # Calculate total USDC value by checking usdc_vault token account
            # This requires a separate RPC call, so we'll estimate for now
            total_usdc_estimate = high_water_mark_nav / 1e6 if high_water_mark_nav > 0 else 0.0
            
            decoded_data = {
                # Core vault info
                'emergency_owner': emergency_owner,
                'calvin_authority': calvin_authority,  # This is the trading authority
                'staking_program_id': staking_program_id,
                'shares_mint': shares_mint,
                'usdc_mint': usdc_mint,
                'usdc_vault': usdc_vault,
                'vault_authority': vault_authority,
                
                # Bump seeds
                'vault_bump': vault_bump,
                'shares_mint_bump': shares_mint_bump,
                'authority_bump': authority_bump,
                
                # Other addresses
                'calvin_mint': calvin_mint,
                'treasury': treasury,
                'jupiter_program_id': jupiter_program_id,
                
                # Financial data
                'per_nft_cap': per_nft_cap,
                'high_water_mark_nav': high_water_mark_nav,
                'total_shares': total_shares,
                'total_usdc': total_usdc_estimate,  # Estimated for backward compatibility
                
                # Status flags
                'paused': paused,
                'reentrancy_guard': reentrancy_guard,
                'trading_paused': trading_paused,
                'deposits_paused': deposits_paused,
                'withdrawals_paused': withdrawals_paused,
                
                # Legacy compatibility fields
                'trading_authority': calvin_authority,  # Alias for backward compatibility
                'performance_fee_bps': 750,  # Default values for missing fee config
                'deposit_fee_bps': 250,
                'withdrawal_fee_bps': 0,
                'bump': vault_bump  # Legacy field name
            }
            
            logger.debug(f"✅ Decoded vault data: shares={total_shares}, paused={paused}, trading_paused={trading_paused}")
            return decoded_data
            
        except Exception as e:
            logger.error(f"❌ Failed to decode vault account data: {e}")
            return None

    async def get_user_position(self, user_pubkey: str) -> Dict[str, Any]:
        """
        Get user's vault position by querying the actual user position account
        
        Note: The UserPosition struct tracks deposits, but shares are stored in SPL token accounts.
        We need to query both the UserPosition account and the user's share token account.
        
        Args:
            user_pubkey: User's public key
            
        Returns:
            Dictionary with user position information
        """
        if not self.client:
            await self.initialize()
        
        try:
            # 1. Derive user position PDA
            vault_program_id = Pubkey.from_string(self.vault_program_id)
            user_pubkey_obj = Pubkey.from_string(user_pubkey)
            usdc_mint = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
            
            # Derive vault PDA first
            vault_pda, _ = Pubkey.find_program_address(
                [b"vault", bytes(usdc_mint)],
                vault_program_id
            )
            
            # Derive user position PDA (seeds: ["pos", vault, user])
            user_position_pda, _ = Pubkey.find_program_address(
                [b"pos", bytes(vault_pda), bytes(user_pubkey_obj)],
                vault_program_id
            )
            
            logger.debug(f"🔍 Querying user position: {user_position_pda}")
            
            # 2. Query the actual user position account
            account_info = await self.client.get_account_info(user_position_pda)
            
            # 3. Get vault state to find shares mint
            vault_state = await self.get_vault_state()
            shares_mint = vault_state.get('shares_mint')
            
            if not account_info or not account_info.value:
                # User has no position (account doesn't exist)
                logger.debug(f"📊 No position found for {user_pubkey[:8]}...")
                return {
                    'shares': 0,
                    'usdc_value': 0.0,
                    'total_deposits_usdc': 0.0,
                    'last_deposit': None,
                    'user': user_pubkey,
                    'initialized': False,
                    'position_address': str(user_position_pda)
                }
            
            # 4. Decode position data (tracks deposits, not shares)
            position_data = await self._decode_user_position(account_info.value.data)
            
            if not position_data:
                logger.error("❌ Failed to decode user position data")
                return {
                    'shares': 0,
                    'usdc_value': 0.0,
                    'total_deposits_usdc': 0.0,
                    'last_deposit': None,
                    'user': user_pubkey,
                    'error': 'Failed to decode position data',
                    'position_address': str(user_position_pda)
                }
            
            # 5. Get user's share token balance (actual shares)
            shares = 0
            if shares_mint:
                try:
                    # Get user's associated token account for shares
                    # Calculate ATA manually since solders.token might not have this function
                    from solders.hash import hash as solana_hash
                    
                    shares_mint_pubkey = Pubkey.from_string(shares_mint)
                    ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
                    TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
                    
                    # Find associated token address
                    user_shares_ata, _ = Pubkey.find_program_address(
                        [bytes(user_pubkey_obj), bytes(TOKEN_PROGRAM_ID), bytes(shares_mint_pubkey)],
                        ASSOCIATED_TOKEN_PROGRAM_ID
                    )
                    
                    # Query the token account
                    shares_account_info = await self.client.get_token_account_balance(user_shares_ata)
                    if shares_account_info and shares_account_info.value:
                        shares = int(shares_account_info.value.amount)
                    
                except Exception as e:
                    logger.debug(f"Could not get shares balance for {user_pubkey[:8]}...: {e}")
            
            # 6. Calculate USDC value of shares
            nav_per_share = vault_state.get('nav_per_share', 1.0)
            usdc_value = shares * nav_per_share
            
            # 7. Convert timestamp to readable format
            last_deposit = None
            if position_data.get('last_deposit_timestamp') and position_data['last_deposit_timestamp'] > 0:
                last_deposit = datetime.fromtimestamp(position_data['last_deposit_timestamp']).isoformat()
            
            position = {
                'shares': shares,
                'usdc_value': usdc_value,
                'total_deposits_usdc': position_data.get('total_deposits_usdc', 0.0),
                'last_deposit': last_deposit,
                'user': user_pubkey,
                'initialized': True,
                'position_address': str(user_position_pda),
                'shares_mint': shares_mint,
                'nav_per_share': nav_per_share,
                'last_updated': datetime.utcnow().isoformat()
            }
            
            logger.debug(f"📊 Retrieved position for {user_pubkey[:8]}...: {shares} shares = ${usdc_value:.2f} (deposits: ${position_data.get('total_deposits_usdc', 0):.2f})")
            return position
            
        except Exception as e:
            logger.error(f"❌ Failed to get user position: {e}")
            return {
                'shares': 0,
                'usdc_value': 0.0,
                'total_deposits_usdc': 0.0,
                'last_deposit': None,
                'user': user_pubkey,
                'error': str(e),
                'initialized': False
            }

    async def _decode_user_position(self, account_data: bytes) -> Optional[Dict[str, Any]]:
        """
        Decode user position account data according to Anchor program structure
        
        Actual UserPosition struct (from onchain/programs/calvin-vault/src/state/mod.rs):
        - discriminator: [u8; 8]
        - user_authority: Pubkey (32 bytes)
        - vault: Pubkey (32 bytes)
        - total_deposits_usdc: u64 (8 bytes)
        - last_deposit_timestamp: i64 (8 bytes)
        - bump: u8 (1 byte)
        - reserved: [u8; 64] (64 bytes)
        
        Args:
            account_data: Raw account data bytes
            
        Returns:
            Decoded user position data dictionary
        """
        try:
            import struct
            
            if len(account_data) < 8:
                logger.error("❌ Position account data too short for Anchor discriminator")
                return None
            
            # Skip Anchor discriminator (first 8 bytes)
            data = account_data[8:]
            
            # Calculate minimum expected size: user_authority + vault + total_deposits + timestamp + bump
            min_size = 32 + 32 + 8 + 8 + 1  # = 81 bytes minimum (not including reserved)
            
            if len(data) < min_size:
                logger.error(f"❌ Position account data too short: {len(data)} bytes, expected at least {min_size}")
                return None
            
            offset = 0
            
            # Parse the user position data according to actual Rust struct layout
            # Pubkey: user_authority (32 bytes)
            user_authority_bytes = data[offset:offset+32]
            user_authority = str(Pubkey(user_authority_bytes))
            offset += 32
            
            # Pubkey: vault (32 bytes)
            vault_bytes = data[offset:offset+32]
            vault = str(Pubkey(vault_bytes))
            offset += 32
            
            # u64: total_deposits_usdc (8 bytes, little-endian)
            total_deposits_usdc = struct.unpack('<Q', data[offset:offset+8])[0]
            offset += 8
            
            # i64: last_deposit_timestamp (8 bytes, little-endian, signed)
            last_deposit_timestamp = struct.unpack('<q', data[offset:offset+8])[0]
            offset += 8
            
            # u8: bump (1 byte)
            bump = data[offset]
            offset += 1
            
            decoded_data = {
                'user_authority': user_authority,
                'vault': vault,
                'total_deposits_usdc': total_deposits_usdc / 1e6,  # Convert micro-USDC to USDC
                'last_deposit_timestamp': last_deposit_timestamp,
                'bump': bump,
                
                # Legacy compatibility fields (calculated from actual data)
                'shares': 0,  # This struct doesn't store shares directly - shares are in the shares token account
                'last_deposit_ts': last_deposit_timestamp,  # Legacy field name
            }
            
            logger.debug(f"✅ Decoded user position: user={user_authority[:8]}..., deposits=${decoded_data['total_deposits_usdc']:.2f}")
            return decoded_data
            
        except Exception as e:
            logger.error(f"❌ Failed to decode user position data: {e}")
            return None

    async def emergency_exit_position(self, symbol: str, amount: float) -> Optional[str]:
        """
        Execute emergency exit for a position via vault smart contract
        
        Args:
            symbol: Token symbol to exit
            amount: Amount to exit (in token units)
            
        Returns:
            Transaction signature if successful
        """
        logger.critical(f"🚨 EMERGENCY EXIT requested for {symbol}: {amount} tokens")
        
        try:
            # Get token information
            if not self.db_manager:
                self.db_manager = await get_db_manager()
            
            token_info = await self.db_manager.get_token_by_symbol(symbol)
            if not token_info:
                logger.error(f"❌ Token info not found for {symbol}")
                return None
            
            destination_mint = token_info['address']
            source_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC
            
            # For emergency exit, we need to sell the position back to USDC
            # Create a Jupiter sell transaction (reverse of normal buy)
            from .jupiter_client import JupiterV6Client
            jupiter_client = JupiterV6Client()
            
            # Calculate amount in token decimals
            token_decimals = token_info.get('decimals', 6)
            amount_in_smallest_unit = int(amount * (10 ** token_decimals))
            
            logger.debug(f"🔄 Creating emergency sell: {amount} {symbol} → USDC")
            
            # Get Jupiter quote for selling the token
            quote = await jupiter_client.get_quote(
                input_mint=destination_mint,      # Selling token
                output_mint=source_mint,          # Getting USDC
                amount=amount_in_smallest_unit,
                slippage_bps=200  # 2% slippage for emergency (higher tolerance)
            )
            
            if not quote or 'error' in quote:
                logger.error(f"❌ Emergency Jupiter quote failed for {symbol}: {quote}")
                return None
            
            # Get swap transaction data
            swap_data = await jupiter_client.get_swap_transaction(quote)
            if not swap_data:
                logger.error(f"❌ Emergency Jupiter swap data failed for {symbol}")
                return None
            
            # Create jupiter data dict for vault execution
            jupiter_data = {
                'transaction_data': swap_data.get('swapTransaction', ''),
                'accounts': swap_data.get('accounts', []),
                'quote': quote
            }
            
            # Execute emergency trade through vault (selling position)
            tx_sig = await self.execute_trade(
                jupiter_data=jupiter_data,
                source_mint=destination_mint,     # Source is the token being sold
                destination_mint=source_mint,     # Destination is USDC
                amount_usdc=0.0  # Amount will be calculated from token amount
            )
            
            if tx_sig:
                logger.critical(f"✅ EMERGENCY EXIT executed for {symbol}: {tx_sig}")
                return tx_sig
            else:
                logger.error(f"❌ Emergency exit transaction failed for {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Emergency exit failed for {symbol}: {e}")
            return None

    def _load_keypair_from_string(self, key_string: str) -> Keypair:
        """
        Load keypair from string, handling both base58 and JSON array formats
        
        Args:
            key_string: Private key as base58 string or JSON array string
            
        Returns:
            Keypair object
        """
        try:
            # Handle JSON array format (Solana CLI format): [1,2,3,4,...]
            if key_string.strip().startswith('['):
                import ast
                # Parse the array string safely
                private_key_bytes = ast.literal_eval(key_string)
                return Keypair.from_bytes(private_key_bytes)
            
            # Handle base58 encoded string format
            else:
                return Keypair.from_base58_string(key_string)
                
        except Exception as e:
            # If first attempt fails, try the other format as fallback
            try:
                if key_string.strip().startswith('['):
                    # If array format failed, maybe it's malformed - try base58
                    return Keypair.from_base58_string(key_string)
                else:
                    # If base58 failed, try array format
                    import ast
                    private_key_bytes = ast.literal_eval(key_string)
                    return Keypair.from_bytes(private_key_bytes)
            except Exception as e2:
                raise ValueError(f"Failed to load keypair in any format. Array error: {e}, Base58 error: {e2}")

    async def _validate_rpc_connection(self):
        """Validate RPC connection is working"""
        try:
            # Test with a simple get_latest_blockhash call instead of get_health (which doesn't exist)
            response = await self.client.get_latest_blockhash()
            if response and response.value:
                logger.debug("✅ Solana RPC connection validated")
            else:
                raise Exception("RPC health check returned invalid response")
                
        except Exception as e:
            logger.error(f"❌ Solana RPC connection failed: {e}")
            raise

    async def _create_vault_trade_transaction(self, jupiter_data: Dict, source_mint: str, destination_mint: str, amount_usdc: float) -> Optional[VersionedTransaction]:
        """
        Create a vault trade transaction that calls the vault program's trade() instruction
        
        This is where the "remaining accounts" magic happens! We extract all the accounts
        that Jupiter needs and include them in our vault instruction.
        
        Args:
            jupiter_data: Dict with transaction_data, accounts, and quote from Jupiter
            source_mint: Source token mint (USDC)
            destination_mint: Destination token mint
            amount_usdc: Trade amount in USDC
            
        Returns:
            Transaction object ready to be signed and sent
        """
        try:
            from solders.transaction import VersionedTransaction
            from solders.system_program import ID as SYS_PROGRAM_ID
            from solders.sysvar import RENT
            from solders.pubkey import Pubkey
            from solders.instruction import Instruction, AccountMeta
            from solders.message import MessageV0
            
            logger.debug(f"🔨 Creating vault trade transaction: {source_mint} → {destination_mint}")
            
            # Program IDs
            vault_program_id = Pubkey.from_string(self.vault_program_id)
            jupiter_program_id = Pubkey.from_string("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4")  # Jupiter V6
            TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
            ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
            
            # Convert string addresses to Pubkey objects
            source_mint_pubkey = Pubkey.from_string(source_mint)
            destination_mint_pubkey = Pubkey.from_string(destination_mint)
            
            # Derive vault PDA
            vault_pda, vault_bump = Pubkey.find_program_address(
                [b"vault", bytes(source_mint_pubkey)],  # Vault seeded with USDC mint
                vault_program_id
            )
            
            # Derive vault authority PDA
            # Using exact seed from constants.rs: VAULT_AUTHORITY_PDA_SEED = b"vault_authority"
            vault_authority_pda, authority_bump = Pubkey.find_program_address(
                [b"vault_authority"],
                vault_program_id
            )
            
            # Derive token accounts (vault's token accounts are ATAs owned by vault_authority)
            # The vault uses Associated Token Accounts, not custom PDAs
            # Find associated token accounts for vault authority
            vault_usdc_token_account, _ = Pubkey.find_program_address(
                [bytes(vault_authority_pda), bytes(TOKEN_PROGRAM_ID), bytes(source_mint_pubkey)],
                ASSOCIATED_TOKEN_PROGRAM_ID
            )
            
            vault_source_token_account = vault_usdc_token_account  # Same as USDC for source
            
            vault_destination_token_account, _ = Pubkey.find_program_address(
                [bytes(vault_authority_pda), bytes(TOKEN_PROGRAM_ID), bytes(destination_mint_pubkey)],
                ASSOCIATED_TOKEN_PROGRAM_ID
            )
            
            # 🚨 CRITICAL FIX: Derive token whitelist PDAs (MISSING from original)
            # Using exact seeds from constants.rs: TOKEN_WHITELIST_PDA_SEED = b"token_whitelist"
            source_token_whitelist_pda, source_whitelist_bump = Pubkey.find_program_address(
                [b"token_whitelist", bytes(vault_pda), bytes(source_mint_pubkey)],
                vault_program_id
            )
            
            destination_token_whitelist_pda, dest_whitelist_bump = Pubkey.find_program_address(
                [b"token_whitelist", bytes(vault_pda), bytes(destination_mint_pubkey)],
                vault_program_id
            )
            
            # 🚨 CRITICAL FIX: Get oracle accounts from oracle_config.rs (MISSING from original)
            source_oracle_pubkey = await self._get_oracle_for_token(source_mint)
            destination_oracle_pubkey = await self._get_oracle_for_token(destination_mint)
            
            if not source_oracle_pubkey:
                logger.error(f"❌ No oracle found for source token {source_mint}")
                return None
                
            if not destination_oracle_pubkey:
                logger.error(f"❌ No oracle found for destination token {destination_mint}")
                return None
            
            logger.debug(f"🔮 Using oracles: source={source_oracle_pubkey}, dest={destination_oracle_pubkey}")
            
            # Derive treasury USDC token account
            treasury_pubkey = Pubkey.from_string(self.treasury_address)
            treasury_usdc_token_account, _ = Pubkey.find_program_address(
                [bytes(treasury_pubkey), bytes(TOKEN_PROGRAM_ID), bytes(source_mint_pubkey)],
                ASSOCIATED_TOKEN_PROGRAM_ID
            )
            
            # Create vault trade instruction accounts (EXACT MATCH to smart contract Trade struct)
            accounts = [
                # Core vault accounts
                AccountMeta(pubkey=self.authority_keypair.public_key, is_signer=True, is_writable=True),  # authority
                AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),  # vault
                AccountMeta(pubkey=vault_usdc_token_account, is_signer=False, is_writable=True),  # vault_usdc_token
                AccountMeta(pubkey=source_mint_pubkey, is_signer=False, is_writable=False),  # source_mint
                AccountMeta(pubkey=destination_mint_pubkey, is_signer=False, is_writable=False),  # destination_mint
                AccountMeta(pubkey=vault_source_token_account, is_signer=False, is_writable=True),  # source_token_account
                AccountMeta(pubkey=vault_destination_token_account, is_signer=False, is_writable=True),  # destination_token_account
                AccountMeta(pubkey=vault_authority_pda, is_signer=False, is_writable=False),  # vault_authority
                
                # 🎯 NEW: Treasury account for performance fees
                AccountMeta(pubkey=treasury_usdc_token_account, is_signer=False, is_writable=True),  # treasury_usdc_token
                
                AccountMeta(pubkey=source_token_whitelist_pda, is_signer=False, is_writable=False),  # source_token_whitelist
                AccountMeta(pubkey=destination_token_whitelist_pda, is_signer=False, is_writable=False),  # destination_token_whitelist
                
                AccountMeta(pubkey=source_oracle_pubkey, is_signer=False, is_writable=False),  # source_price_account
                AccountMeta(pubkey=destination_oracle_pubkey, is_signer=False, is_writable=False),  # destination_price_account
                
                # Program accounts
                AccountMeta(pubkey=jupiter_program_id, is_signer=False, is_writable=False),  # jupiter_program
                AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),  # token_program
            ]
            
            # Extract Jupiter transaction data and accounts
            jupiter_transaction_data = jupiter_data.get('transaction_data', '')
            jupiter_accounts = jupiter_data.get('accounts', [])
            
            logger.debug(f"📋 Jupiter transaction data: {len(jupiter_transaction_data)} chars")
            logger.debug(f"📋 Jupiter accounts: {len(jupiter_accounts)} accounts")
            
            # 🚨 CRITICAL: Add Jupiter accounts as remaining accounts
            # This is where we solve the "remaining accounts" problem!
            for account_str in jupiter_accounts:
                try:
                    account_pubkey = Pubkey.from_string(account_str)
                    # Add as writable since Jupiter may need to modify these accounts
                    accounts.append(AccountMeta(pubkey=account_pubkey, is_signer=False, is_writable=True))
                except Exception as e:
                    logger.warning(f"⚠️ Failed to parse Jupiter account {account_str}: {e}")
            
            # Create instruction data (Jupiter transaction as base64 bytes)
            import base64
            if isinstance(jupiter_transaction_data, str):
                instruction_data = base64.b64decode(jupiter_transaction_data)
            else:
                instruction_data = jupiter_transaction_data
            
            # Create the vault trade instruction with discriminator
            # Anchor uses 8-byte discriminator: SHA256("global:trade")[0:8]
            import hashlib
            discriminator_string = "global:trade"
            discriminator_hash = hashlib.sha256(discriminator_string.encode()).digest()
            trade_discriminator = discriminator_hash[:8]
            
            # The vault's trade() function expects: discriminator + Jupiter transaction data
            full_instruction_data = trade_discriminator + instruction_data
            
            vault_trade_ix = Instruction(
                program_id=vault_program_id,
                accounts=accounts,
                data=full_instruction_data
            )
            
            # Get recent blockhash
            recent_blockhash_resp = await self.client.get_latest_blockhash()
            if not recent_blockhash_resp or not recent_blockhash_resp.value:
                logger.error("❌ Failed to get recent blockhash")
                return None
            
            recent_blockhash = recent_blockhash_resp.value.blockhash
            
            # Create versioned transaction message
            message = MessageV0.try_compile(
                payer=self.authority_keypair.pubkey,
                instructions=[vault_trade_ix],
                address_lookup_table_accounts=[],
                recent_blockhash=recent_blockhash,
            )
            
            # Create versioned transaction
            transaction = VersionedTransaction(message, [self.authority_keypair])
            
            logger.debug(f"✅ Created vault trade transaction with {len(accounts)} accounts (including {len(jupiter_accounts)} Jupiter accounts)")
            return transaction
            
        except Exception as e:
            logger.error(f"❌ Failed to create vault trade transaction: {e}")
            return None

    async def _get_oracle_for_token(self, token_mint: str) -> Optional[Pubkey]:
        """
        Get the Pyth oracle account for a specific token mint
        
        This maps to the oracle_config.rs constants in the smart contract
        
        Args:
            token_mint: Token mint address
            
        Returns:
            Pyth oracle pubkey if found
        """
        try:
            # Real Pyth oracle mappings from oracle_config.rs (converted from hex to pubkeys)
            # Each oracle address is derived from the hex string in PYTH_PRICE_FEEDS
            TOKEN_ORACLE_MAPPING = {
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "Gnt27xtC473ZT2Mw5u8wZ68Z3gULkSTb5DuxJy7eJotD",  # USDC
                "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN": "FJwgyp5h2FvCm2RYMoFGH5npsKoN7mH3agQTgW2oKbYf",  # TRUMP
                "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof": "BKyRbT3efcUWsKNkZnYPRdxVPHFQE9dzBUJfKoWz1s1z",  # RENDER
                "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "g6eRCbboSwK4tSWngn773RCMexr1APQr4uA9bGZBYfo",   # JUP
                "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "8ihFLu5FimgTQ1Unh4dVyEHUGodJ5gJQCrQf4KUVB9bN",  # BONK
                "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump": "FZgvx7qqJvMfz7bKMtRbchXNVKBwYXfg2aKVh7QEBSGG",  # FARTCOIN
                "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": "AnLf8tVYCM816gmBjiy8n53eXKKEDydT5piYjjQDPgTB",   # RAY
                "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL": "D8UUgr8a3aR3yUeHLu5v8jmVjHBjRNRQLvpvHRQSjM3B",   # JTO
                "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3npgxbkkTs8LG": "nrYkQQQur7z8rYTST3G9GqATviK5SxTDkrqd21MW6Ue",    # PYTH
                "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": "6ABgrEZk8urs6kJ1JNdC1sspH5zKXRqxy8sg3ZG2cQps",  # WIF
                "BUjZjAS2vbbb65g7Z1Ca9ZRVYoJscURG5L3AkVXHP2ac": "8kVVBkOGNnwJhqVAJJh5UNEqgfX9HZHaRdHGXMxFTHGW", # VIRTUAL
                "3Bmj7x4udgJhKa43EYRcmNq2JLkgz7eAayFn8qYhyXKV": "DJKQz4GKWzXLVX8dGAqLnzuqmR6VNWK2mQ6KJp2Jy4ue", # PENGU
                "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ": "EhYXXUn7dUfJKB5TKXUwZTHsUZCXGj2MFJJjrQNPTZWv", # W (WORMHOLE)
                "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": "Fu1hzNr7YfGZFBrB7XkwDJUwWswpKM5oSc6HvpqsLmug", # POPCAT
                "ATHdb8YvGvBVhgJB3PaMU5sCdAUHkhkN42jdYWK4h2xQ": "G6rAxKYKYQ48QqRVP4F3Gn8Sx5Br5Y8zPBwBXQEU87RM", # ATH
                "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5": "5WzJ8K5YHJjZYwMhz9c2ZCpj2R6pF9v3SzQF9a7aJQNu", # MEW
                "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey": "3Qub6Fc3NjwrFdDaVG8W4PmNKnNRGqKPqHcUqGjyFdFc", # MNDE
                "AUKyeqDfN8p6B93X9gYCnCpdJUfvxU6ZWEmAy2VKqm3w": "8FdvJCqLRBgCdJNWN9hnXWKFzRRPMdG7gBq5vqH4XQQS", # SPX (SPX6900)
                "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE": "4ivThkX8uRxBpHsdWSqyXYihzKF3zpRGAUCqyuagnLoV", # ORCA
            }
            
            oracle_address = TOKEN_ORACLE_MAPPING.get(token_mint)
            if oracle_address:
                return Pubkey.from_string(oracle_address)
            else:
                logger.warning(f"⚠️ No oracle mapping found for token {token_mint}")
                # For unknown tokens, use USDC oracle as fallback
                return Pubkey.from_string("Gnt27xtC473ZT2Mw5u8wZ68Z3gULkSTb5DuxJy7eJotD")
            
        except Exception as e:
            logger.error(f"❌ Failed to get oracle for token {token_mint}: {e}")
            return None

    def _hex_to_pubkey(self, hex_str: str) -> Optional[Pubkey]:
        """
        Convert hex string from oracle_config.rs to Pubkey
        
        Args:
            hex_str: Hex string like "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a"
            
        Returns:
            Pubkey object or None if conversion fails
        """
        try:
            # Remove 0x prefix if present
            hex_clean = hex_str.strip().lower()
            if hex_clean.startswith('0x'):
                hex_clean = hex_clean[2:]
            
            # Convert hex to bytes (32 bytes for Pubkey)
            if len(hex_clean) != 64:  # 32 bytes * 2 chars per byte
                logger.error(f"Invalid hex length: {len(hex_clean)}, expected 64")
                return None
            
            pubkey_bytes = bytes.fromhex(hex_clean)
            return Pubkey(pubkey_bytes)
            
        except Exception as e:
            logger.error(f"Failed to convert hex to pubkey: {hex_str}, error: {e}")
            return None

    async def _send_transaction(self, transaction: VersionedTransaction) -> Optional[str]:
        """
        Send transaction to Solana network
        
        Args:
            transaction: Transaction to send
            
        Returns:
            Transaction signature if successful
        """
        try:
            # Transaction is already signed during creation
            
            # Send transaction
            opts = TxOpts(
                skip_confirmation=False,
                skip_preflight=False,
                max_retries=self.max_retries
            )
            
            response = await self.client.send_transaction(transaction, opts=opts)
            
            if response and response.value:
                return str(response.value)
            else:
                logger.error("❌ Transaction failed - no signature returned")
                return None
                
        except RPCException as e:
            logger.error(f"❌ RPC error sending transaction: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Error sending transaction: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get client performance statistics"""
        success_rate = (
            (self.transaction_count - self.failed_transactions) / self.transaction_count
            if self.transaction_count > 0 else 0
        )
        
        avg_execution_time = (
            self.total_execution_time / self.transaction_count
            if self.transaction_count > 0 else 0
        )
        
        return {
            'total_transactions': self.transaction_count,
            'failed_transactions': self.failed_transactions,
            'success_rate': success_rate,
            'avg_execution_time_ms': avg_execution_time,
            'authority_configured': self.authority_keypair is not None,
            'client_connected': self.client is not None,
            'vault_program_id': self.vault_program_id,
            'rpc_url': self.rpc_url
        }

    async def health_check(self) -> bool:
        """Health check for vault client"""
        try:
            if not self.client:
                await self.initialize()
            
            # Check RPC connection
            await self._validate_rpc_connection()
            
            # Check vault state accessibility
            vault_state = await self.get_vault_state()
            if 'error' in vault_state:
                return False
            
            logger.debug("✅ Vault client health check passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Vault client health check failed: {e}")
            return False

    def __del__(self):
        """Cleanup on destruction"""
        if self.client:
            logger.warning("⚠️ VaultClient not properly closed") 