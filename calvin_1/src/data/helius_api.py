import json
import time
import aiohttp
import asyncio
import requests
import pandas as pd
from typing import Dict, List, Optional, Union, Any
from datetime import datetime, timedelta

from src.config.config import config
from utils.logger import log_manager

logger = log_manager.get_logger("helius_api")

class HeliusAPI:
    """Client for the Helius API to fetch Solana blockchain data"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.helius_api_key
        if not self.api_key:
            raise ValueError("Helius API key is required")
        
        self.base_url = f"https://api.helius.xyz/v0"
        self.rpc_url = f"https://mainnet.helius-rpc.com/?api-key={self.api_key}"
    
    async def _make_async_request(self, method: str, params: List, is_rpc: bool = True) -> Dict:
        """Make an async JSON-RPC request to the Helius API"""
        url = self.rpc_url if is_rpc else f"{self.base_url}/{method}?api-key={self.api_key}"
        
        payload = {
            "jsonrpc": "2.0",
            "id": str(int(time.time())),
            "method": method,
            "params": params
        } if is_rpc else params
        
        async with aiohttp.ClientSession() as session:
            try:
                if is_rpc:
                    async with session.post(url, json=payload) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"Error from Helius API: {error_text}")
                            response.raise_for_status()
                        
                        result = await response.json()
                        if "error" in result:
                            logger.error(f"RPC error: {result['error']}")
                            raise ValueError(f"RPC error: {result['error']}")
                        
                        return result["result"]
                else:
                    async with session.get(url, params=payload) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"Error from Helius API: {error_text}")
                            response.raise_for_status()
                        
                        return await response.json()
            except Exception as e:
                logger.error(f"Error making async request to Helius API: {e}")
                raise
    
    def _make_request(self, method: str, params: List, is_rpc: bool = True) -> Dict:
        """Make a synchronous JSON-RPC request to the Helius API"""
        url = self.rpc_url if is_rpc else f"{self.base_url}/{method}?api-key={self.api_key}"
        
        payload = {
            "jsonrpc": "2.0",
            "id": str(int(time.time())),
            "method": method,
            "params": params
        } if is_rpc else params
        
        try:
            if is_rpc:
                response = requests.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                
                if "error" in result:
                    logger.error(f"RPC error: {result['error']}")
                    raise ValueError(f"RPC error: {result['error']}")
                
                return result["result"]
            else:
                response = requests.get(url, params=payload)
                response.raise_for_status()
                return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making request to Helius API: {e}")
            if hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            raise
    
    def get_balance(self, wallet_address: str) -> float:
        """Get the SOL balance of a wallet"""
        method = "getBalance"
        params = [wallet_address]
        
        result = self._make_request(method, params)
        
        # Convert from lamports to SOL
        balance_in_sol = result["value"] / 1_000_000_000
        logger.debug(f"Wallet {wallet_address} has balance of {balance_in_sol} SOL")
        
        return balance_in_sol
    
    def get_token_balances(self, wallet_address: str) -> List[Dict]:
        """Get all token balances for a wallet"""
        method = "getTokenAccountsByOwner"
        params = [
            wallet_address,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"}
        ]
        
        result = self._make_request(method, params)
        
        token_accounts = []
        for account in result["value"]:
            info = account["account"]["data"]["parsed"]["info"]
            token_accounts.append({
                "mint": info["mint"],
                "owner": info["owner"],
                "amount": int(info["tokenAmount"]["amount"]),
                "decimals": info["tokenAmount"]["decimals"],
                "uiAmount": float(info["tokenAmount"]["uiAmount"] or 0)
            })
        
        logger.info(f"Found {len(token_accounts)} token accounts for {wallet_address}")
        return token_accounts
    
    async def get_transaction_history(
        self, 
        wallet_address: str, 
        limit: int = 100, 
        before: Optional[str] = None
    ) -> List[Dict]:
        """Get transaction history for a wallet address"""
        method = "getSignaturesForAddress"
        params = [wallet_address, {"limit": limit}]
        
        if before:
            params[1]["before"] = before
        
        result = await self._make_async_request(method, params)
        logger.info(f"Retrieved {len(result)} transactions for {wallet_address}")
        
        return result
    
    async def get_transaction_details(self, signature: str) -> Dict:
        """Get detailed information about a transaction"""
        method = "getTransaction"
        params = [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
        
        result = await self._make_async_request(method, params)
        return result
    
    async def get_transactions_with_details(
        self, 
        wallet_address: str, 
        limit: int = 20
    ) -> List[Dict]:
        """Get transaction history with full details for a wallet address"""
        tx_history = await self.get_transaction_history(wallet_address, limit)
        
        # Get details for each transaction
        detail_tasks = []
        for tx in tx_history:
            detail_tasks.append(self.get_transaction_details(tx["signature"]))
        
        tx_details = await asyncio.gather(*detail_tasks)
        
        # Combine history with details
        result = []
        for i, tx in enumerate(tx_history):
            tx_data = {
                "signature": tx["signature"],
                "timestamp": tx["blockTime"],
                "slot": tx["slot"],
                "details": tx_details[i]
            }
            result.append(tx_data)
        
        return result
    
    def get_token_metadata(self, token_address: str) -> Dict:
        """Get metadata for a specific token"""
        method = "getTokenMetadata"
        params = {"mintAccounts": [token_address]}
        
        result = self._make_request("token-metadata", params, is_rpc=False)
        if not result or not isinstance(result, list) or len(result) == 0:
            logger.error(f"Invalid response format: {result}")
            return {}
        
        return result[0]
    
    def get_nft_events(
        self, 
        wallet_address: Optional[str] = None,
        collection: Optional[str] = None,
        types: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get NFT events (sales, listings, etc.)
        
        Args:
            wallet_address: Filter by wallet address
            collection: Filter by collection address
            types: Filter by event types ('NFT_SALE', 'NFT_LISTING', 'NFT_CANCEL_LISTING')
            limit: Number of events to return
        """
        params = {"limit": limit}
        
        if wallet_address:
            params["walletAddress"] = wallet_address
        if collection:
            params["collection"] = collection
        if types:
            params["types"] = types
        
        result = self._make_request("nft-events", params, is_rpc=False)
        return result
    
    def get_dex_trades(
        self,
        limit: int = 100,
        token_address: Optional[str] = None
    ) -> List[Dict]:
        """
        Get DEX trades from Solana
        
        Args:
            limit: Number of trades to return
            token_address: Filter by token address
        """
        params = {"limit": limit}
        
        if token_address:
            params["tokenAddress"] = token_address
        
        result = self._make_request("dex-trades", params, is_rpc=False)
        return result
