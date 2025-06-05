import os
import json
import base64
import time
from typing import Dict, List, Optional, Union, Any, Tuple
from solana.rpc.api import Client
from solana.rpc.types import TxOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solders.system_program import transfer, TransferParams
from solders.signature import Signature
from spl.token.instructions import get_associated_token_address

from src.config.config import config
from src.utils.logger import log_manager

logger = log_manager.get_logger("wallet")

class SolanaWallet:
    """Handles Solana wallet operations for trading"""
    
    def __init__(
        self, 
        private_key: Optional[str] = None, 
        public_key: Optional[str] = None,
        rpc_url: Optional[str] = None
    ):
        # Set up wallet
        self.private_key = private_key or config.wallet_private_key
        self.public_key = public_key or config.wallet_public_key
        
        if not self.private_key:
            logger.warning("No private key provided, generating new keypair")
            self.keypair = Keypair()
            self.public_key = str(self.keypair.public_key)
            logger.info(f"Generated new wallet with public key: {self.public_key}")
        else:
            # Convert private key to bytes and create keypair
            try:
                if self.private_key.startswith('['):  # JSON array format
                    private_key_bytes = bytes(json.loads(self.private_key))
                else:  # Base58 or Base64 format
                    try:
                        private_key_bytes = base64.b64decode(self.private_key)
                    except:
                        # If not Base64, assume it's a 64-byte hex string
                        private_key_bytes = bytes.fromhex(self.private_key)
                
                self.keypair = Keypair.from_secret_key(private_key_bytes)
                
                # Verify that the derived public key matches the provided one (if any)
                derived_public_key = str(self.keypair.public_key)
                if self.public_key and derived_public_key != self.public_key:
                    logger.warning(f"Derived public key {derived_public_key} doesn't match provided key {self.public_key}")
                
                self.public_key = derived_public_key
                logger.info(f"Wallet initialized with public key: {self.public_key}")
            except Exception as e:
                logger.error(f"Error initializing wallet with provided private key: {e}")
                raise ValueError(f"Invalid private key format: {e}")
        
        # Set up RPC client
        self.rpc_url = rpc_url or config.get_rpc_url()
        self.client = Client(self.rpc_url)
        
        # Check connection
        try:
            self.client.get_health()
            logger.info(f"Connected to Solana node at {self.rpc_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Solana node: {e}")
            raise ConnectionError(f"Failed to connect to Solana node: {e}")
    
    def get_balance(self) -> float:
        """Get SOL balance of the wallet"""
        try:
            response = self.client.get_balance(self.public_key)
            
            if response.get('result'):
                # Convert from lamports to SOL
                balance_in_sol = response['result']['value'] / 1_000_000_000
                logger.debug(f"Wallet balance: {balance_in_sol} SOL")
                return balance_in_sol
            else:
                logger.error(f"Failed to get balance: {response}")
                return 0.0
        except Exception as e:
            logger.error(f"Error getting wallet balance: {e}")
            return 0.0
    
    def get_token_accounts(self) -> List[Dict]:
        """Get all token accounts owned by this wallet"""
        try:
            response = self.client.get_token_accounts_by_owner(
                self.public_key,
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}
            )
            
            if response.get('result'):
                accounts = []
                for item in response['result']['value']:
                    account_info = item['account']['data']['parsed']['info']
                    token_amount = account_info['tokenAmount']
                    
                    accounts.append({
                        'mint': account_info['mint'],
                        'address': item['pubkey'],
                        'amount': int(token_amount['amount']),
                        'decimals': token_amount['decimals'],
                        'ui_amount': float(token_amount['uiAmount'] or 0)
                    })
                
                logger.info(f"Found {len(accounts)} token accounts")
                return accounts
            else:
                logger.error(f"Failed to get token accounts: {response}")
                return []
        except Exception as e:
            logger.error(f"Error getting token accounts: {e}")
            return []
    
    def get_token_balance(self, token_mint: str) -> float:
        """Get balance of a specific token"""
        token_accounts = self.get_token_accounts()
        
        for account in token_accounts:
            if account['mint'] == token_mint:
                logger.debug(f"Token {token_mint} balance: {account['ui_amount']}")
                return account['ui_amount']
        
        logger.debug(f"No account found for token {token_mint}")
        return 0.0
    
    def send_sol(
        self, 
        recipient: str, 
        amount: float, 
        wait_for_confirmation: bool = True,
        max_retries: int = 3
    ) -> Optional[str]:
        """
        Send SOL to another wallet
        
        Args:
            recipient: Recipient wallet address
            amount: Amount of SOL to send
            wait_for_confirmation: Whether to wait for transaction confirmation
            max_retries: Maximum number of retries on failure
            
        Returns:
            Transaction signature if successful, None otherwise
        """
        if amount <= 0:
            logger.error(f"Invalid amount: {amount}")
            return None
        
        # Convert SOL to lamports
        lamports = int(amount * 1_000_000_000)
        
        try:
            recipient_pubkey = Pubkey.from_string(recipient)
            
            # Create transfer instruction
            transfer_instruction = transfer(
                TransferParams(
                    from_pubkey=self.keypair.pubkey(),
                    to_pubkey=recipient_pubkey,
                    lamports=lamports
                )
            )
            
            # Create and sign transaction
            transaction = Transaction()
            transaction.add(transfer_instruction)
            
            # Send transaction
            retry_count = 0
            while retry_count < max_retries:
                try:
                    response = self.client.send_transaction(
                        transaction,
                        self.keypair,
                        opts=TxOpts(skip_preflight=False, preflight_commitment="confirmed")
                    )
                    
                    if 'result' in response:
                        signature = response['result']
                        logger.info(f"SOL transfer initiated: {amount} SOL to {recipient}, signature: {signature}")
                        
                        if wait_for_confirmation:
                            self._confirm_transaction(signature)
                        
                        return signature
                    else:
                        logger.error(f"Failed to send SOL: {response}")
                except Exception as e:
                    retry_count += 1
                    logger.warning(f"Transaction attempt {retry_count} failed: {e}")
                    time.sleep(1)  # Wait before retrying
            
            logger.error(f"Failed to send SOL after {max_retries} attempts")
            return None
        except Exception as e:
            logger.error(f"Error sending SOL: {e}")
            return None
    
    def _confirm_transaction(self, signature: str, max_timeout: int = 60) -> bool:
        """Wait for transaction confirmation"""
        logger.info(f"Waiting for transaction confirmation: {signature}")
        
        start_time = time.time()
        while time.time() - start_time < max_timeout:
            try:
                response = self.client.get_signature_statuses([signature])
                
                if 'result' in response and response['result']['value'][0]:
                    confirmation = response['result']['value'][0]
                    
                    if confirmation['confirmationStatus'] == 'confirmed' or confirmation['confirmationStatus'] == 'finalized':
                        logger.info(f"Transaction confirmed: {signature}")
                        return True
                
                # Wait a bit before checking again
                time.sleep(2)
            except Exception as e:
                logger.warning(f"Error checking transaction status: {e}")
                time.sleep(2)
        
        logger.error(f"Transaction confirmation timed out after {max_timeout}s: {signature}")
        return False
    
    def find_or_create_token_account(self, token_mint: str) -> Optional[str]:
        """Find existing token account or create a new one for the given token"""
        # First check if we already have an account for this token
        token_accounts = self.get_token_accounts()
        
        for account in token_accounts:
            if account['mint'] == token_mint:
                logger.debug(f"Found existing token account for {token_mint}: {account['address']}")
                return account['address']
        
        # If no account exists, we'd need to create one
        # This is a simplified version, in production you'd want to use the proper SPL token program
        logger.warning(f"Token account creation not implemented. No account for {token_mint}")
        return None
    
    def swap_tokens(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        slippage: float = 0.01  # 1% slippage
    ) -> Optional[str]:
        """
        Swap tokens using a DEX (simplified version)
        
        Note: This is a placeholder. In a real implementation, you would:
        1. Find the best route for the swap
        2. Create the appropriate instructions for the specific DEX
        3. Execute the transaction
        
        Args:
            from_token: Token to swap from (mint address)
            to_token: Token to swap to (mint address)
            amount: Amount to swap
            slippage: Maximum slippage percentage
            
        Returns:
            Transaction signature if successful, None otherwise
        """
        logger.info(f"Token swap not fully implemented. Would swap {amount} of {from_token} to {to_token}")
        
        # In a real implementation, you would:
        # 1. Get a quote from the DEX
        # 2. Create a swap transaction with the appropriate instructions
        # 3. Sign and send the transaction
        
        return None
    
    def save_wallet_info(self, filepath: str) -> None:
        """Save wallet information to a file (for development only)"""
        if not os.path.exists(os.path.dirname(filepath)):
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        wallet_info = {
            'public_key': self.public_key,
            'private_key': list(self.keypair.secret_key),  # Convert to list for JSON serialization
            'created_at': time.time()
        }
        
        with open(filepath, 'w') as f:
            json.dump(wallet_info, f)
        
        logger.info(f"Wallet information saved to {filepath}")
    
    @classmethod
    def load_wallet_from_file(cls, filepath: str) -> 'SolanaWallet':
        """Load wallet from a file (for development only)"""
        with open(filepath, 'r') as f:
            wallet_info = json.load(f)
        
        return cls(
            private_key=json.dumps(wallet_info['private_key']),
            public_key=wallet_info['public_key']
        )
