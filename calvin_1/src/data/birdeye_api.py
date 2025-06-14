import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any
import os

from ..config.config import config
from ..utils.logger import log_manager

logger = log_manager.get_logger("birdeye_api")

class BirdEyeAPI:
    """Client for the BirdEye API to fetch Solana market data"""
    
    BASE_URL = "https://public-api.birdeye.so"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.birdeye_api_key
        if not self.api_key:
            raise ValueError("BirdEye API key is required")
        
        self.headers = {
            "X-API-KEY": self.api_key,
            "accept": "application/json",
            "x-chain": "solana"
        }
    
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a request to the BirdEye API"""
        url = f"{self.BASE_URL}/{endpoint}"
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making request to BirdEye API: {e}")
            if hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            raise
    
    def get_token_price(self, token_address: str) -> Dict:
        """Get the price for a specific token"""
        endpoint = "v1/token/price"
        params = {
            "address": token_address
        }
        
        response = self._make_request(endpoint, params)
        logger.debug(f"Got price for token {token_address}: {response}")
        return response
    
    def get_token_metadata(self, token_address: str) -> Dict:
        """Get metadata for a specific token using the v3 API"""
        endpoint = "defi/v3/token/meta-data/single"
        params = {
            "address": token_address
        }
        
        response = self._make_request(endpoint, params)
        logger.debug(f"Got metadata for token {token_address}")
        return response
    
    def get_token_ohlcv(
        self, 
        token_address: str, 
        resolution: str = "15m", 
        time_from: Optional[int] = None,
        time_to: Optional[int] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """
        Get OHLCV (Open, High, Low, Close, Volume) data for a token
        
        Args:
            token_address: The Solana token address
            resolution: Time resolution (1m, 5m, 15m, 1H, 4H, 1d)
            time_from: Start time in Unix timestamp (seconds)
            time_to: End time in Unix timestamp (seconds)
            limit: Number of candles to fetch (ignored if time_from and time_to are provided)
            
        Returns:
            DataFrame with OHLCV data where:
            - o, h, l, c (open, high, low, close) are denominated in USD
            - v (volume) is the token amount of the token
            - type field represents the interval (e.g., "15m" = 15-minute intervals)
        """
        endpoint = "defi/ohlcv"
        params = {
            "address": token_address,
            "type": resolution,
            "currency": "usd"
        }
        
        # Add optional time range parameters
        if time_from is not None:
            params["time_from"] = time_from
        if time_to is not None:
            params["time_to"] = time_to
        
        response = self._make_request(endpoint, params)
        
        if 'data' not in response or 'items' not in response['data']:
            logger.error(f"Invalid response format: {response}")
            raise ValueError("Invalid response format")
        
        # Convert to DataFrame
        ohlcv_data = response['data']['items']
        df = pd.DataFrame(ohlcv_data)
        
        # Format timestamps
        if 'unixTime' in df.columns:
            df['timestamp'] = pd.to_datetime(df['unixTime'], unit='s')
            df.set_index('timestamp', inplace=True)
            
            # Rename columns to match standard naming conventions
            df.rename(columns={
                'o': 'open',
                'h': 'high',
                'l': 'low',
                'c': 'close',
                'v': 'volume'
            }, inplace=True)
        
        logger.info(f"Fetched {len(df)} OHLCV records for {token_address}")
        return df
    
    def get_token_list(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get a list of tokens on Solana"""
        endpoint = "v1/token/list"
        params = {
            "limit": limit,
            "offset": offset
        }
        
        response = self._make_request(endpoint, params)
        if 'data' not in response or 'items' not in response['data']:
            logger.error(f"Invalid response format: {response}")
            raise ValueError("Invalid response format")
            
        return response['data']['items']
    
    def get_token_list_v3(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get a list of tokens on Solana (v3 endpoint)"""
        endpoint = "defi/v3/token/list"
        params = {
            "limit": limit,
            "offset": offset
        }
        
        response = self._make_request(endpoint, params)
        if 'data' not in response or 'items' not in response['data']:
            logger.error(f"Invalid response format: {response}")
            raise ValueError("Invalid response format")
            
        return response['data']['items']
    
    def get_markets(self, token_address: str) -> List[Dict]:
        """
        Get markets (trading pairs) for a specific token
        
        Args:
            token_address: The Solana token address
            
        Returns:
            List of market pairs containing the token
        """
        endpoint = "defi/v2/markets"
        params = {
            "address": token_address
        }
        
        response = self._make_request(endpoint, params)
        if 'data' not in response or 'items' not in response['data']:
            logger.error(f"Invalid response format: {response}")
            raise ValueError("Invalid response format")
            
        return response['data']['items']
    
    def get_top_tokens(self, limit: int = 50) -> List[Dict]:
        """Get the top tokens by market cap on Solana"""
        endpoint = "v1/token/list"
        params = {
            "limit": limit,
            "sortBy": "mc",
            "sortType": "desc"
        }
        
        response = self._make_request(endpoint, params)
        if 'data' not in response or 'items' not in response['data']:
            logger.error(f"Invalid response format: {response}")
            raise ValueError("Invalid response format")
            
        return response['data']['items']
    
    def get_defi_pools(self, token_address: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Get DeFi pools involving a specific token or top pools"""
        endpoint = "v1/defi/pools"
        params = {
            "limit": limit
        }
        
        if token_address:
            params['tokenAddress'] = token_address
        
        response = self._make_request(endpoint, params)
        if 'data' not in response or 'items' not in response['data']:
            logger.error(f"Invalid response format: {response}")
            raise ValueError("Invalid response format")
            
        return response['data']['items']
    
    def get_historical_data(
        self, 
        token_address: str, 
        resolution: str = "15m", 
        days: int = 30
    ) -> pd.DataFrame:
        """
        Get comprehensive historical data for a token over a given time period
        
        Args:
            token_address: The Solana token address
            resolution: Time resolution (1m, 5m, 15m, 1H, 4H, 1d)
            days: Number of days to fetch
            
        Returns:
            DataFrame with historical data where:
            - open, high, low, close are denominated in USD
            - volume is the token amount of the token
        """
        # Calculate time range for the request
        time_to = int(datetime.now().timestamp())
        time_from = int((datetime.now() - timedelta(days=days)).timestamp())
        
        # Make the request with time range parameters
        return self.get_token_ohlcv(
            token_address=token_address,
            resolution=resolution,
            time_from=time_from,
            time_to=time_to
        )
