import time
import requests
import threading
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any
import random
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
        # Retry/backoff configuration
        self.max_retries = int(os.environ.get("BIRDEYE_MAX_RETRIES", "6"))
        self.base_backoff = float(os.environ.get("BIRDEYE_BACKOFF_BASE", "0.4"))
        self.backoff_jitter = float(os.environ.get("BIRDEYE_BACKOFF_JITTER", "0.25"))
        # Rate limiting (token bucket in requests/sec)
        self.rps_limit = float(os.environ.get("BIRDEYE_RPS_LIMIT", "15"))
        self._bucket_capacity = self.rps_limit
        self._tokens = self._bucket_capacity
        self._last_refill = time.monotonic()
        self._rate_lock = threading.Lock()
        # HTTP session pooling
        self.session = requests.Session()
        try:
            from requests.adapters import HTTPAdapter
            adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=0)
            self.session.mount('http://', adapter)
            self.session.mount('https://', adapter)
        except Exception:
            pass

    def _rate_limit_wait(self):
        if self.rps_limit <= 0:
            return
        while True:
            with self._rate_lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                if elapsed > 0:
                    self._tokens = min(self._bucket_capacity, self._tokens + elapsed * self.rps_limit)
                    self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
                sleep_seconds = max(0.0, deficit / self.rps_limit)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            else:
                # In case of edge rounding issues, loop again
                time.sleep(0.001)
    
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a request to the BirdEye API with retry/backoff on transient errors"""
        url = f"{self.BASE_URL}/{endpoint}"
        
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                # Global rate limiter
                self._rate_limit_wait()
                response = self.session.get(url, headers=self.headers, params=params, timeout=20)
                # Retry on 429 and 5xx
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    raise requests.exceptions.HTTPError(f"HTTP {response.status_code}")
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                last_exc = e
                if attempt == self.max_retries - 1:
                    logger.error(f"Error making request to BirdEye API (attempt {attempt+1}/{self.max_retries}): {e}")
                    if hasattr(e, 'response') and getattr(e, 'response', None) is not None:
                        try:
                            logger.error(f"Response: {e.response.text}")
                        except Exception:
                            pass
                    raise
                # Backoff with jitter
                delay = self.base_backoff * (2 ** attempt) + random.uniform(0, self.backoff_jitter)
                logger.warning(f"BirdEye request failed (attempt {attempt+1}/{self.max_retries}). Retrying in {delay:.2f}s...")
                time.sleep(delay)
        # Should not reach here
        raise last_exc if last_exc else RuntimeError("Unknown request error")
    
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

    def get_token_txs(
        self,
        token_address: str,
        *,
        offset: Optional[int] = None,
        limit: int = 100,
        sort_by: str = "block_unix_time",
        sort_type: str = "desc",
        tx_type: Optional[str] = None,
        source: Optional[str] = None,
        owner: Optional[str] = None,
        pool_id: Optional[str] = None,
        before_time: Optional[int] = None,
        after_time: Optional[int] = None,
        before_block_number: Optional[int] = None,
        after_block_number: Optional[int] = None,
        ui_amount_mode: str = "scaled",
    ) -> Dict:
        """
        Get token transactions (swaps) from BirdEye V3 endpoint.

        Docs: Trades - Token (V3): defi/v3/token/txs
        Supports filtering by time or block number ranges, with sorting by the corresponding field.
        """
        endpoint = "defi/v3/token/txs"
        safe_limit = max(1, min(int(limit or 100), 100))
        params: Dict[str, Any] = {
            "address": token_address,
            "limit": safe_limit,
            "sort_by": sort_by,
            "sort_type": sort_type,
            "ui_amount_mode": ui_amount_mode,
        }

        # Optional basic filters
        if offset is not None:
            params["offset"] = int(offset)
        if tx_type:
            params["tx_type"] = tx_type
        if source:
            params["source"] = source
        if owner:
            params["owner"] = owner
        if pool_id:
            params["pool_id"] = pool_id

        # Apply optional range filters (only one type allowed by API)
        if before_time is not None:
            params["before_time"] = before_time
        if after_time is not None:
            params["after_time"] = after_time
        if before_block_number is not None:
            params["before_block_number"] = before_block_number
        if after_block_number is not None:
            params["after_block_number"] = after_block_number

        response = self._make_request(endpoint, params)
        if not isinstance(response, dict) or "data" not in response:
            logger.error(f"Invalid response for token txs: {response}")
            raise ValueError("Invalid response format")
        return response