"""
Pyth Oracle Handler for Calvin AI Vault System

This module handles fetching price updates from Pyth's Hermes API
and creating PriceUpdateV2 accounts on Solana for use in vault operations.
"""

import json
import asyncio
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

import aiohttp
import base64
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.message import Message
from solders.instruction import Instruction, AccountMeta
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
from solana.rpc.types import TxOpts


@dataclass
class PriceUpdate:
    """Represents a price update from Pyth"""
    price_feed_id: str
    price: int
    confidence: int
    exponent: int
    publish_time: int
    prev_publish_time: int
    ema_price: int
    ema_confidence: int


class PythOracleHandler:
    """Handles Pyth oracle operations for Calvin vault"""
    
    # Pyth Hermes API endpoint
    HERMES_API_BASE = "https://hermes.pyth.network"
    
    # Pyth program IDs
    PYTH_SOLANA_RECEIVER_PROGRAM_ID = Pubkey.from_string("rec5EKMGg6MxZYaMdyBfgwp4d5rB9T1VQH5pJv5LtFJ")
    
    def __init__(self, rpc_client: AsyncClient, authority_keypair: Keypair):
        """
        Initialize the Pyth oracle handler
        
        Args:
            rpc_client: Solana RPC client
            authority_keypair: Keypair that will pay for oracle account creation
        """
        self.rpc_client = rpc_client
        self.authority_keypair = authority_keypair
        
    async def fetch_price_updates(self, price_feed_ids: List[str]) -> List[bytes]:
        """
        Fetch price updates from Pyth Hermes API
        
        Args:
            price_feed_ids: List of hex price feed IDs (e.g., "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a")
            
        Returns:
            List of encoded price update data
        """
        # Clean price feed IDs - remove 0x prefix as per Hermes API
        clean_ids = []
        for fid in price_feed_ids:
            if fid.startswith("0x"):
                fid = fid[2:]  # Remove 0x prefix
            clean_ids.append(fid)
        
        # Use the correct Hermes API endpoint as per documentation
        url = f"{self.HERMES_API_BASE}/v2/updates/price/latest"
        
        # Build query parameters according to the working curl example
        # Note: aiohttp will handle the array parameter encoding
        params = [
            ("ids[]", fid) for fid in clean_ids
        ] + [
            ("encoding", "base64"),
            ("parsed", "true"),
            ("ignore_invalid_price_ids", "true")
        ]
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Hermes API error {response.status}: {error_text}")
                
                data = await response.json()
                
                # According to Hermes docs, the response has a 'binary' field with 'data' array
                if "binary" not in data:
                    raise Exception(f"No binary data in Hermes response. Keys: {list(data.keys())}")
                
                binary_field = data["binary"]
                if "data" not in binary_field:
                    raise Exception(f"No data in binary field. Keys: {list(binary_field.keys())}")
                
                # Extract the VAA (Verifiable Action Attestation) data
                vaa_data_list = binary_field["data"]
                
                price_updates = []
                for vaa_data in vaa_data_list:
                    # Each VAA is base64 encoded
                    try:
                        decoded_vaa = base64.b64decode(vaa_data)
                        price_updates.append(decoded_vaa)
                    except Exception as e:
                        print(f"Failed to decode VAA data: {e}")
                        continue
                
                print(f"✅ Fetched {len(price_updates)} price update VAAs from Hermes")
                return price_updates
    
    async def create_price_update_accounts(self, price_update_data: List[bytes]) -> List[Pubkey]:
        """
        Create PriceUpdateV2 accounts on Solana using multiple smaller transactions
        
        Args:
            price_update_data: List of encoded price update data from Hermes
            
        Returns:
            List of created account addresses
        """
        created_accounts = []
        
        for update_data in price_update_data:
            try:
                # Split into multiple transactions to stay under size limit
                # Transaction 1: Create the account
                account_keypair = Keypair()
                account_pubkey = account_keypair.pubkey()
                
                # Calculate rent for the account (price updates are typically ~304 bytes)
                rent_response = await self.rpc_client.get_minimum_balance_for_rent_exemption(
                    len(update_data) + 8  # 8 bytes for discriminator
                )
                rent_lamports = rent_response.value
                
                # Create the account creation instruction using proper system program format
                from solders.system_program import CreateAccountParams, create_account
                create_account_ix = create_account(
                    CreateAccountParams(
                        from_pubkey=self.authority_keypair.pubkey(),
                        to_pubkey=account_pubkey,
                        lamports=rent_lamports,
                        space=len(update_data) + 8,  # 8 bytes for discriminator
                        owner=self.PYTH_SOLANA_RECEIVER_PROGRAM_ID
                    )
                )
                
                # Send account creation transaction first
                recent_blockhash = await self.rpc_client.get_latest_blockhash()
                
                from solders.message import MessageV0
                create_message = MessageV0.try_compile(
                    payer=self.authority_keypair.pubkey(),
                    instructions=[create_account_ix],
                    address_lookup_table_accounts=[],
                    recent_blockhash=recent_blockhash.value.blockhash
                )
                
                create_transaction = VersionedTransaction(create_message, [self.authority_keypair, account_keypair])
                
                create_response = await self.rpc_client.send_transaction(
                    create_transaction,
                    opts=TxOpts(skip_confirmation=False, preflight_commitment=Commitment("confirmed"))
                )
                
                if not create_response.value:
                    print(f"Failed to create account for price update")
                    continue
                
                print(f"✅ Created price update account: {account_pubkey}")
                
                # Transaction 2: Write the price update data
                # Split data into chunks if it's too large
                chunk_size = 800  # Conservative chunk size to stay under transaction limits
                data_chunks = [update_data[i:i+chunk_size] for i in range(0, len(update_data), chunk_size)]
                
                for chunk_index, chunk in enumerate(data_chunks):
                    # Create write instruction with offset
                    write_data_ix = Instruction(
                        program_id=self.PYTH_SOLANA_RECEIVER_PROGRAM_ID,
                        accounts=[
                            AccountMeta(account_pubkey, is_signer=False, is_writable=True),
                            AccountMeta(self.authority_keypair.pubkey(), is_signer=True, is_writable=False),
                        ],
                        data=chunk  # Just the chunk data
                    )
                    
                    # Get fresh blockhash for each chunk transaction
                    recent_blockhash = await self.rpc_client.get_latest_blockhash()
                    
                    write_message = MessageV0.try_compile(
                        payer=self.authority_keypair.pubkey(),
                        instructions=[write_data_ix],
                        address_lookup_table_accounts=[],
                        recent_blockhash=recent_blockhash.value.blockhash
                    )
                    
                    write_transaction = VersionedTransaction(write_message, [self.authority_keypair])
                    
                    write_response = await self.rpc_client.send_transaction(
                        write_transaction,
                        opts=TxOpts(skip_confirmation=False, preflight_commitment=Commitment("confirmed"))
                    )
                    
                    if not write_response.value:
                        print(f"Failed to write data chunk {chunk_index} to price update account")
                        break
                    
                    print(f"✅ Wrote data chunk {chunk_index + 1}/{len(data_chunks)} to {account_pubkey}")
                
                created_accounts.append(account_pubkey)
                    
            except Exception as e:
                print(f"Error creating price update account: {e}")
                continue
        
        return created_accounts
    
    async def get_oracle_accounts_for_tokens(self, token_mints: List[str]) -> Dict[str, Pubkey]:
        """
        Get oracle accounts for a set of tokens by calling the Node.js Pyth oracle generator
        
        Args:
            token_mints: List of token mint addresses
            
        Returns:
            Dict mapping token mints to their oracle account addresses
        """
        try:
            import subprocess
            import json
            import os
            import base58
            
            # Get the private key for the authority (needed to pay for oracle account creation)
            # The keypair stores the private key as a 64-byte array, pass it as JSON array format
            authority_private_key_bytes = bytes(self.authority_keypair)
            authority_private_key_json = json.dumps(list(authority_private_key_bytes))
            
            # Prepare the command to call the Node.js script
            script_path = os.path.join(os.path.dirname(__file__), '..', '..', 'pyth_oracle_generator.js')
            token_mints_json = json.dumps(token_mints)
            
            cmd = [
                'node',
                script_path,
                token_mints_json,
                str(self.rpc_client._provider.endpoint_uri),
                authority_private_key_json
            ]
            
            print(f"🔄 Creating oracle accounts for {len(token_mints)} tokens...")
            print(f"   Command: {' '.join(cmd[:3])} [token_mints] [rpc_url] [private_key]")
            
            # Call the Node.js script
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout
            )
            
            if result.returncode != 0:
                print(f"❌ Node.js script failed with return code {result.returncode}")
                print(f"   stdout: {result.stdout}")
                print(f"   stderr: {result.stderr}")
                raise Exception(f"Oracle account creation failed: {result.stderr}")
            
            # Parse the output to get the oracle accounts
            output_lines = result.stdout.strip().split('\n')
            oracle_accounts_json = None
            
            # Look for the JSON result in the output
            for line in output_lines:
                if line.startswith('ORACLE_ACCOUNTS_RESULT:'):
                    continue
                if line.startswith('{') and line.endswith('}'):
                    oracle_accounts_json = line
                    break
            
            if not oracle_accounts_json:
                print(f"❌ Could not find oracle accounts result in output:")
                print(result.stdout)
                raise Exception("Failed to parse oracle accounts from Node.js output")
            
            # Parse the JSON result
            oracle_accounts_dict = json.loads(oracle_accounts_json)
            
            # Convert string addresses to Pubkey objects
            result_dict = {}
            for mint, account_address in oracle_accounts_dict.items():
                result_dict[mint] = Pubkey.from_string(account_address)
            
            print(f"✅ Successfully created {len(result_dict)} oracle accounts")
            return result_dict
            
        except Exception as e:
            print(f"❌ Error getting oracle accounts: {e}")
            raise


# Price feed IDs for common tokens (from vault client mapping)
TOKEN_ORACLE_HEX_MAPPING = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a",  # USDC
    "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN": "0x879551021853eec7a7dc827578e8e69da7e4fa8148339aa0d3d5296405be4b1a",  # TRUMP
    "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof": "0x3d4a2bd9535be6ce8059d75eadeba507b043257321aa544717c56fa19b49e35d",  # RENDER
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "0x0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996",   # JUP
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "0x72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419",  # BONK
    "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump": "0x58cd29ef0e714c5affc44f269b2c1899a52da4169d7acc147b9da692e6953608",  # FARTCOIN
    "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": "0x91568baa8beb53db23eb3fb7f22c6e8bd303d103919e19733f2bb642d3e7987a",   # RAY
    "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL": "0xb43660a5f790c69354b0729a5ef9d50d68f1df92107540210b9cccba1f947cc2",   # JTO
    "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3": "0x0bbf28e9a841a1cc788f6a361b17ca072d0ea3098a1e5df1c3922d06719579ff",    # PYTH
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": "0x4ca4beeca86f0d164160323817a4e42b10010a724c2217c6ee41b54cd4cc61fc",  # WIF
    "3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y": "0x8132e3eb1dac3e56939a16ff83848d194345f6688bff97eb1c8bd462d558802b", # VIRTUAL
    "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv": "0xbed3097008b9b5e3c93bec20be79cb43986b85a996475589351a21e67bae9b61", # PENGU
    "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ": "0xeff7446475e218517566ea99e72a4abec2e1bd8498b43b7d8331e29dcb059389", # W (WORMHOLE)
    "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": "0xb9312a7ee50e189ef045aa3c7842e099b061bd9bdc99ac645956c3b660dc8cce", # POPCAT
    "Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7": "0xf6b551a947e7990089e2d5149b1e44b369fcc6ad3627cb822362a2b19d24ad4a", # ATH
    "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5": "0x514aed52ca5294177f20187ae883cec4a018619772ddce41efcc36a6448f5d5d", # MEW
    "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey": "0x3607bf4d7b78666bd3736c7aacaf2fd2bc56caa8667d3224971ebe3c0623292a", # MNDE
    "J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr": "0x8414cfadf82f6bed644d2e399c11df21ec0131aa574c56030b132113dbbf3a0a", # SPX (SPX6900)
    "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE": "0x37505261e557e251290b8c8899453064e8d760ed5c65a779726f2490980da74c", # ORCA
}

# Reverse mapping from mint address to price feed ID
PRICE_FEED_IDS = TOKEN_ORACLE_HEX_MAPPING


async def get_oracle_accounts_for_vault_operation(
    rpc_client: AsyncClient,
    authority_keypair: Keypair,
    required_token_mints: List[str]
) -> Dict[str, Pubkey]:
    """
    Convenience function to get oracle accounts for vault operations
    
    Args:
        rpc_client: Solana RPC client
        authority_keypair: Authority keypair for paying oracle costs
        required_token_mints: List of token mint addresses that need oracle accounts
        
    Returns:
        Dict mapping token mint addresses to oracle account addresses
    """
    handler = PythOracleHandler(rpc_client, authority_keypair)
    
    # Filter to only the required tokens that have price feeds
    supported_token_mints = [
        mint for mint in required_token_mints 
        if mint in PRICE_FEED_IDS
    ]
    
    return await handler.get_oracle_accounts_for_tokens(supported_token_mints) 