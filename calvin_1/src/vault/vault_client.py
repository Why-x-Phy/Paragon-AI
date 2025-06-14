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
                    logger.info(f"✅ Trading authority loaded: {self.authority_keypair.public_key}")
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
        Get current vault state by querying the vault program account
        
        Uses Helius API to fetch the actual vault account data and decode it
        according to our Anchor program's account structure.
        
        Returns:
            Dictionary with vault state information
        """
        if not self.client:
            await self.initialize()
        
        try:
            # Derive the vault PDA (same as in transaction creation)
            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            vault_program_id = Pubkey.from_string(self.vault_program_id)
            usdc_mint_pubkey = Pubkey.from_string(usdc_mint)
            
            vault_pda, vault_bump = Pubkey.find_program_address(
                [b"vault", bytes(usdc_mint_pubkey)],
                vault_program_id
            )
            
            logger.debug(f"🔍 Querying vault account: {vault_pda}")
            
            # Query the vault account using Helius/Solana RPC
            account_info = await self.client.get_account_info(vault_pda)
            
            if not account_info or not account_info.value:
                logger.warning("⚠️ Vault account not found - may not be initialized")
                return {
                    'paused': True,
                    'initialized': False,
                    'error': 'Vault account not found'
                }
            
            # Decode the account data according to our Anchor program structure
            vault_data = await self._decode_vault_account(account_info.value.data)
            
            if not vault_data:
                logger.error("❌ Failed to decode vault account data")
                return {
                    'paused': True,
                    'error': 'Failed to decode vault data'
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
            logger.error(f"❌ Failed to get vault state: {e}")
            return {
                'paused': True,  # Fail-safe: assume paused on error
                'initialized': False,
                'error': str(e),
                'last_updated': datetime.utcnow().isoformat()
            }

    async def _decode_vault_account(self, account_data: bytes) -> Optional[Dict[str, Any]]:
        """
        Decode vault account data according to Anchor program structure
        
        Our Vault struct (from onchain/programs/calvin-vault/src/state/mod.rs):
        - discriminator: [u8; 8]
        - total_usdc: u64
        - total_shares: u64  
        - trading_authority: Pubkey
        - emergency_owner: Pubkey
        - paused: bool
        - performance_fee_bps: u16
        - deposit_fee_bps: u16
        - withdrawal_fee_bps: u16
        - jupiter_program_id: Pubkey
        - bump: u8
        
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
            
            if len(data) < 8 + 8 + 32 + 32 + 1 + 2 + 2 + 2 + 32 + 1:  # Minimum expected size
                logger.error(f"❌ Account data too short: {len(data)} bytes")
                return None
            
            offset = 0
            
            # Parse the vault data according to Rust struct layout
            # u64: total_usdc (8 bytes, little-endian)
            total_usdc = struct.unpack('<Q', data[offset:offset+8])[0]
            offset += 8
            
            # u64: total_shares (8 bytes, little-endian)  
            total_shares = struct.unpack('<Q', data[offset:offset+8])[0]
            offset += 8
            
            # Pubkey: trading_authority (32 bytes)
            trading_authority_bytes = data[offset:offset+32]
            trading_authority = str(Pubkey(trading_authority_bytes))
            offset += 32
            
            # Pubkey: emergency_owner (32 bytes)
            emergency_owner_bytes = data[offset:offset+32]
            emergency_owner = str(Pubkey(emergency_owner_bytes))
            offset += 32
            
            # bool: paused (1 byte)
            paused = data[offset] != 0
            offset += 1
            
            # u16: performance_fee_bps (2 bytes, little-endian)
            performance_fee_bps = struct.unpack('<H', data[offset:offset+2])[0]
            offset += 2
            
            # u16: deposit_fee_bps (2 bytes, little-endian)
            deposit_fee_bps = struct.unpack('<H', data[offset:offset+2])[0]
            offset += 2
            
            # u16: withdrawal_fee_bps (2 bytes, little-endian)
            withdrawal_fee_bps = struct.unpack('<H', data[offset:offset+2])[0]
            offset += 2
            
            # Pubkey: jupiter_program_id (32 bytes)
            jupiter_program_bytes = data[offset:offset+32]
            jupiter_program_id = str(Pubkey(jupiter_program_bytes))
            offset += 32
            
            # u8: bump (1 byte)
            bump = data[offset]
            
            decoded_data = {
                'total_usdc': total_usdc / 1e6,  # Convert micro-USDC to USDC
                'total_shares': total_shares,
                'trading_authority': trading_authority,
                'emergency_owner': emergency_owner,
                'paused': paused,
                'performance_fee_bps': performance_fee_bps,
                'deposit_fee_bps': deposit_fee_bps,
                'withdrawal_fee_bps': withdrawal_fee_bps,
                'jupiter_program_id': jupiter_program_id,
                'bump': bump
            }
            
            logger.debug(f"✅ Decoded vault data: {decoded_data}")
            return decoded_data
            
        except Exception as e:
            logger.error(f"❌ Failed to decode vault account data: {e}")
            return None

    async def get_user_position(self, user_pubkey: str) -> Dict[str, Any]:
        """
        Get user's vault position by querying the actual user position account
        
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
            
            if not account_info or not account_info.value:
                # User has no position (account doesn't exist)
                logger.debug(f"📊 No position found for {user_pubkey[:8]}...")
                return {
                    'shares': 0,
                    'usdc_value': 0.0,
                    'last_deposit': None,
                    'user': user_pubkey,
                    'initialized': False,
                    'position_address': str(user_position_pda)
                }
            
            # 3. Decode position data
            position_data = await self._decode_user_position(account_info.value.data)
            
            if not position_data:
                logger.error("❌ Failed to decode user position data")
                return {
                    'shares': 0,
                    'usdc_value': 0.0,
                    'last_deposit': None,
                    'user': user_pubkey,
                    'error': 'Failed to decode position data',
                    'position_address': str(user_position_pda)
                }
            
            # 4. Get current vault state to calculate USDC value
            vault_state = await self.get_vault_state()
            nav_per_share = vault_state.get('nav_per_share', 1.0)
            
            # 5. Calculate USDC value of shares
            usdc_value = position_data['shares'] * nav_per_share
            
            # 6. Convert timestamp to readable format
            last_deposit = None
            if position_data.get('last_deposit_ts') and position_data['last_deposit_ts'] > 0:
                last_deposit = datetime.fromtimestamp(position_data['last_deposit_ts']).isoformat()
            
            position = {
                'shares': position_data['shares'],
                'usdc_value': usdc_value,
                'last_deposit': last_deposit,
                'user': user_pubkey,
                'initialized': True,
                'position_address': str(user_position_pda),
                'nav_per_share': nav_per_share,
                'last_updated': datetime.utcnow().isoformat()
            }
            
            logger.debug(f"📊 Retrieved position for {user_pubkey[:8]}...: {position_data['shares']} shares = ${usdc_value:.2f}")
            return position
            
        except Exception as e:
            logger.error(f"❌ Failed to get user position: {e}")
            return {
                'shares': 0,
                'usdc_value': 0.0,
                'last_deposit': None,
                'user': user_pubkey,
                'error': str(e),
                'initialized': False
            }

    async def _decode_user_position(self, account_data: bytes) -> Optional[Dict[str, Any]]:
        """
        Decode user position account data according to Anchor program structure
        
        Our UserPosition struct (from onchain/programs/calvin-vault/src/state/mod.rs):
        - discriminator: [u8; 8]
        - shares: u64
        - last_deposit_ts: i64
        - bump: u8
        
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
            
            if len(data) < 8 + 8 + 1:  # shares + last_deposit_ts + bump
                logger.error(f"❌ Position account data too short: {len(data)} bytes")
                return None
            
            offset = 0
            
            # Parse the user position data according to Rust struct layout
            # u64: shares (8 bytes, little-endian)
            shares = struct.unpack('<Q', data[offset:offset+8])[0]
            offset += 8
            
            # i64: last_deposit_ts (8 bytes, little-endian, signed)
            last_deposit_ts = struct.unpack('<q', data[offset:offset+8])[0]
            offset += 8
            
            # u8: bump (1 byte)
            bump = data[offset]
            
            decoded_data = {
                'shares': shares,
                'last_deposit_ts': last_deposit_ts,
                'bump': bump
            }
            
            logger.debug(f"✅ Decoded user position: {decoded_data}")
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
            # First, try to parse as JSON array (Solana CLI format)
            if key_string.strip().startswith('['):
                import json
                key_array = json.loads(key_string)
                if isinstance(key_array, list) and len(key_array) == 64:
                    # Convert to bytes and create keypair
                    private_key_bytes = bytes(key_array)
                    return Keypair.from_secret_key(private_key_bytes)
                else:
                    raise ValueError("Invalid JSON array format - expected 64 bytes")
            
            # Try as base58 encoded string
            else:
                private_key_bytes = base64.b58decode(key_string)
                return Keypair.from_secret_key(private_key_bytes)
                
        except json.JSONDecodeError:
            # If JSON parsing fails, try base58
            try:
                private_key_bytes = base64.b58decode(key_string)
                return Keypair.from_secret_key(private_key_bytes)
            except Exception as e:
                raise ValueError(f"Failed to parse private key as JSON array or base58: {e}")
        
        except Exception as e:
            raise ValueError(f"Failed to load keypair: {e}")

    async def _validate_rpc_connection(self):
        """Validate RPC connection is working"""
        try:
            # Test with a simple getHealth call
            response = await self.client.get_health()
            if response:
                logger.debug("✅ Solana RPC connection validated")
            else:
                raise Exception("Health check returned None")
                
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
            
            # SPL Token Program ID
            TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
            
            logger.debug(f"🔨 Creating vault trade transaction: {source_mint} → {destination_mint}")
            
            # Convert string addresses to Pubkey objects
            source_mint_pubkey = Pubkey.from_string(source_mint)
            destination_mint_pubkey = Pubkey.from_string(destination_mint)
            vault_program_id = Pubkey.from_string(self.vault_program_id)
            jupiter_program_id = Pubkey.from_string("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4")  # Jupiter V6
            
            # Derive vault PDA
            vault_pda, vault_bump = Pubkey.find_program_address(
                [b"vault", bytes(source_mint_pubkey)],  # Vault seeded with USDC mint
                vault_program_id
            )
            
            # Derive vault authority PDA
            vault_authority_pda, authority_bump = Pubkey.find_program_address(
                [b"vault-authority"],
                vault_program_id
            )
            
            # Derive token accounts (vault's token accounts)
            vault_usdc_token_account, _ = Pubkey.find_program_address(
                [b"vault-token", bytes(vault_pda), bytes(source_mint_pubkey)],
                vault_program_id
            )
            
            vault_source_token_account = vault_usdc_token_account  # Same as USDC for source
            
            vault_destination_token_account, _ = Pubkey.find_program_address(
                [b"vault-token", bytes(vault_pda), bytes(destination_mint_pubkey)],
                vault_program_id
            )
            
            # Create vault trade instruction
            # This calls the vault program's trade() instruction
            accounts = [
                AccountMeta(pubkey=self.authority_keypair.public_key, is_signer=True, is_writable=False),  # authority
                AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),  # vault
                AccountMeta(pubkey=vault_usdc_token_account, is_signer=False, is_writable=True),  # vault_usdc_token
                AccountMeta(pubkey=source_mint_pubkey, is_signer=False, is_writable=False),  # source_mint
                AccountMeta(pubkey=destination_mint_pubkey, is_signer=False, is_writable=False),  # destination_mint
                AccountMeta(pubkey=vault_source_token_account, is_signer=False, is_writable=True),  # source_token_account
                AccountMeta(pubkey=vault_destination_token_account, is_signer=False, is_writable=True),  # destination_token_account
                AccountMeta(pubkey=vault_authority_pda, is_signer=False, is_writable=False),  # vault_authority
                AccountMeta(pubkey=jupiter_program_id, is_signer=False, is_writable=False),  # jupiter_program
                AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),  # token_program
                AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),  # system_program
                AccountMeta(pubkey=RENT, is_signer=False, is_writable=False),  # rent
                # remaining_accounts would be added here for Jupiter-specific accounts
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
            
            # Create the vault trade instruction
            vault_trade_ix = Instruction(
                program_id=vault_program_id,
                accounts=accounts,
                data=instruction_data
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
            
            logger.debug(f"✅ Created vault trade transaction with {len(accounts)} accounts")
            return transaction
            
        except Exception as e:
            logger.error(f"❌ Failed to create vault trade transaction: {e}")
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