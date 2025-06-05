import os
import json
import time
import requests
import datetime
import random
from loguru import logger
from typing import List, Dict, Optional, Union, Any


class RateLimiter:
    """Simple rate limiter to avoid exceeding API limits"""
    
    def __init__(self, max_requests: int = 10, period: int = 60):
        """Initialize rate limiter
        
        Args:
            max_requests: Maximum number of requests allowed in period
            period: Time period in seconds
        """
        self.max_requests = max_requests
        self.period = period
        self.request_times = []
        
    def wait_if_needed(self):
        """Wait if we're approaching rate limits"""
        now = time.time()
        
        # Remove timestamps older than our period
        self.request_times = [t for t in self.request_times if now - t < self.period]
        
        # If we've hit our limit, wait until we can make another request
        if len(self.request_times) >= self.max_requests:
            oldest = min(self.request_times)
            sleep_time = oldest + self.period - now
            if sleep_time > 0:
                logger.warning(f"Rate limit approaching. Waiting {sleep_time:.2f} seconds...")
                time.sleep(sleep_time + random.uniform(0.1, 1.0))  # Add jitter
                
        # Add current request time
        self.request_times.append(time.time())


class LunarCrushAPI:
    """Interface for the LunarCrush API to fetch social metrics for tokens"""
    
    # Updated to API v4
    BASE_URL = "https://lunarcrush.com/api4/public/coins"
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the LunarCrush API client
        
        Args:
            api_key: LunarCrush API key (can also be set via LUNARCRUSH_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("LUNARCRUSH_API_KEY")
        if not self.api_key:
            logger.warning("No LunarCrush API key provided - API calls will be limited")
        
        # Initialize rate limiter (10 requests per minute)
        self.rate_limiter = RateLimiter(max_requests=10, period=60)
    
    def _make_request(self, token_address: str, bucket: str = "hour", interval: str = "1w", 
                     start: Optional[int] = None, end: Optional[int] = None, 
                     max_retries: int = 5) -> Dict:
        """Make a request to the LunarCrush API v4 with exponential backoff for rate limiting
        
        Args:
            token_address: Token address on LunarCrush (e.g. token ID or symbol)
            bucket: Data bucket size ('hour', 'day', etc.)
            interval: Time interval to fetch ('1w', '1m', etc.)
            start: Starting timestamp (Unix timestamp)
            end: Ending timestamp (Unix timestamp)
            max_retries: Maximum number of retry attempts
            
        Returns:
            JSON response from the API
        """
        # Construct URL with query parameters
        url = f"{self.BASE_URL}/{token_address}/time-series/v2"
        params = {
            "bucket": bucket,
            "interval": interval
        }
        
        # Add optional timestamp parameters if provided
        if start:
            params["start"] = start
        if end:
            params["end"] = end
            
        # Append query parameters to URL
        url += "?" + "&".join([f"{k}={v}" for k, v in params.items()])
        
        # Set authorization header
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        # Apply rate limiting before initial request
        self.rate_limiter.wait_if_needed()
        
        # Exponential backoff parameters
        retry = 0
        base_delay = 2  # Base delay in seconds
        
        while retry <= max_retries:
            try:
                response = requests.request("GET", url, headers=headers, timeout=10)
                
                # Check if we hit rate limits (HTTP 429)
                if response.status_code == 429:
                    retry += 1
                    if retry > max_retries:
                        logger.error(f"Max retries exceeded for rate limit")
                        return {"data": []}
                    
                    # Calculate exponential backoff with jitter
                    delay = min(60, base_delay * (2 ** (retry - 1)))  # Cap at 60 seconds
                    jitter = random.uniform(0, 0.5 * delay)  # Add up to 50% jitter
                    total_delay = delay + jitter
                    
                    logger.warning(f"Rate limited by API. Retry {retry}/{max_retries} in {total_delay:.2f}s")
                    time.sleep(total_delay)
                    continue
                
                # Handle other HTTP errors
                response.raise_for_status()
                
                # Success - return the data
                return response.json()
                
            except requests.exceptions.RequestException as e:
                retry += 1
                if retry > max_retries:
                    logger.error(f"Max retries exceeded: {e}")
                    return {"data": []}
                
                # Check if we should retry based on error type
                if isinstance(e, requests.exceptions.Timeout) or \
                   isinstance(e, requests.exceptions.ConnectionError) or \
                   getattr(e.response, 'status_code', 0) in [500, 502, 503, 504]:
                    
                    # Calculate backoff time
                    delay = min(60, base_delay * (2 ** (retry - 1)))
                    jitter = random.uniform(0, 0.5 * delay)
                    total_delay = delay + jitter
                    
                    logger.warning(f"Request failed: {e}. Retry {retry}/{max_retries} in {total_delay:.2f}s")
                    time.sleep(total_delay)
                else:
                    # Other errors we don't handle with retries
                    logger.error(f"Error fetching data from LunarCrush: {e}")
                    return {"data": []}
    
    def get_asset_data(self, symbol: str, address: str = None, lunarcrush_id: int = None, interval: str = "1w", days: int = 7) -> List[Dict]:
        """Get social and market data for a specific token
        
        Args:
            symbol: Token symbol (e.g. 'BTC') - used as fallback
            address: Token address (used as fallback if no LunarCrush ID)
            lunarcrush_id: LunarCrush internal asset ID (preferred, most accurate)
            interval: Data interval ('1w', '1m', etc.)
            days: Number of days of historical data to fetch
            
        Returns:
            List of data points with social metrics
        """
        # For large timeframes, split into multiple requests to avoid overwhelming the API
        chunk_size = 20  # Reduced from 30 to better handle rate limits
        all_data = []
        
        # Determine the best identifier to use (in order of preference)
        if lunarcrush_id:
            primary_identifier = str(lunarcrush_id)
            identifier_type = "LunarCrush ID"
            logger.info(f"Using LunarCrush ID: {lunarcrush_id} for {symbol}")
        elif address:
            primary_identifier = address
            identifier_type = "token address"
            logger.info(f"Using token address: {address} for {symbol}")
        else:
            primary_identifier = f"${symbol}"
            identifier_type = "dollar symbol"
            logger.info(f"Using dollar symbol: ${symbol} (no LunarCrush ID or address available)")
        
        logger.info(f"Fetching data using {identifier_type}: {primary_identifier}")
        data = self._fetch_data_in_chunks(primary_identifier, symbol, address, lunarcrush_id, interval, days, chunk_size)
        
        logger.info(f"Total data points fetched for {symbol}: {len(data)}")
        return data
    
    def _fetch_data_in_chunks(self, primary_identifier: str, symbol: str, address: str, lunarcrush_id: int, interval: str, days: int, chunk_size: int) -> List[Dict]:
        """Helper method to fetch data in chunks to handle rate limits with fallback strategies
        
        Args:
            primary_identifier: Primary identifier to try first (LunarCrush ID, address, or $symbol)
            symbol: Original token symbol (for logging)
            address: Token address as fallback
            lunarcrush_id: LunarCrush internal asset ID
            interval: Data interval ('1w', '1m', etc.)
            days: Number of days of historical data to fetch
            chunk_size: Size of each chunk in days
            
        Returns:
            List of data points with social metrics
        """
        all_data = []
        
        logger.info(f"Fetching {days} days of data for {symbol} in chunks of {chunk_size} days")
        
        # Track if we've ever successfully found data for this token
        # This helps determine if token exists but is just too new for some chunks
        found_data_once = False
        
        # Process chunks from most recent to oldest
        for i in range(0, days, chunk_size):
            # Calculate chunk size for this iteration
            chunk_days = min(chunk_size, days - i)
            
            # Calculate time range for this chunk
            end_time = int(time.time()) - (i * 24 * 60 * 60)
            start_time = end_time - (chunk_days * 24 * 60 * 60)
            
            chunk_num = (i // chunk_size) + 1
            logger.info(f"Fetching chunk {chunk_num}: {chunk_days} days from {datetime.datetime.fromtimestamp(start_time)} to {datetime.datetime.fromtimestamp(end_time)}")
            
            # FIRST ATTEMPT: Try with primary identifier (LunarCrush ID, address, or $symbol)
            token_identifier = primary_identifier
            logger.info(f"Attempt 1: Using primary identifier {token_identifier}")
            
            response = self._make_request(
                token_address=token_identifier,
                bucket="hour",
                interval=interval,
                start=start_time,
                end=end_time
            )
            
            data_points = []
            if "data" in response and response["data"]:
                data_points = response["data"]
                found_data_once = True
                logger.info(f"Success! Received {len(data_points)} data points using primary identifier")
            else:
                logger.warning(f"No data received using primary identifier: {token_identifier}")
                
                # FALLBACK ATTEMPTS: Only if primary identifier wasn't a LunarCrush ID
                if not lunarcrush_id:
                    # SECOND ATTEMPT: Try with token address if available and wasn't primary
                    if address and primary_identifier != address:
                        token_identifier = address
                        logger.info(f"Attempt 2: Using token address {token_identifier}")
                        
                        response = self._make_request(
                            token_address=token_identifier,
                            bucket="hour",
                            interval=interval,
                            start=start_time,
                            end=end_time
                        )
                        
                        if "data" in response and response["data"]:
                            data_points = response["data"]
                            found_data_once = True
                            logger.info(f"Success! Received {len(data_points)} data points using token address")
                        else:
                            logger.warning(f"No data received using token address")
                    
                    # THIRD ATTEMPT: Try with $symbol if not already tried
                    if not data_points and primary_identifier != f"${symbol}":
                        token_identifier = f"${symbol}"
                        logger.info(f"Attempt 3: Using dollar symbol {token_identifier}")
                        
                        response = self._make_request(
                            token_address=token_identifier,
                            bucket="hour",
                            interval=interval,
                            start=start_time,
                            end=end_time
                        )
                        
                        if "data" in response and response["data"]:
                            data_points = response["data"]
                            found_data_once = True
                            logger.info(f"Success! Received {len(data_points)} data points using dollar symbol")
                        else:
                            logger.warning(f"No data received using dollar symbol")
                else:
                    # If LunarCrush ID failed, it's likely the token isn't in their system
                    # or there's an API issue - don't waste time on fallbacks for this chunk
                    logger.warning(f"LunarCrush ID {lunarcrush_id} failed - this is unusual and may indicate API issues")
                
                # If we've never found data and this isn't the first chunk,
                # the token might be too new - skip older chunks
                if chunk_num > 2 and not found_data_once:
                    logger.warning(f"No data found in first {chunk_num} chunks. Token {symbol} might be newer than requested time range.")
                    logger.warning(f"Skipping remaining older chunks to avoid wasting API calls.")
                    break
            
            # Add data points to overall results
            all_data.extend(data_points)
            
            # Always sleep between chunks to reduce chances of rate limiting
            if i + chunk_size < days:  # If not the last chunk
                sleep_time = random.uniform(5, 7)  # Conservative sleep
                logger.debug(f"Sleeping {sleep_time:.2f}s between API requests to avoid rate limits")
                time.sleep(sleep_time)
        
        return all_data
    
    def get_assets_by_category(self, category: str = "meme", limit: int = 10) -> List[Dict]:
        """Get list of top assets by category
        
        Args:
            category: Asset category (e.g. 'meme', 'defi', etc.)
            limit: Maximum number of assets to return
            
        Returns:
            List of assets in the category
        """
        # Note: This method might need to be updated for API v4
        # For now, we'll log a warning and return an empty list
        logger.warning("get_assets_by_category method needs to be updated for API v4")
        return []


def fetch_and_store_social_data(
    symbol: str,
    interval: str = "1w",
    days: int = 7,
    api_key: Optional[str] = None,
    batch_size: int = 100
) -> bool:
    """
    ⚠️  DEPRECATED FUNCTION ⚠️
    
    This function used old SQLAlchemy models and stored social data in the wrong table.
    
    Please use the updated script instead:
        python src/scripts/fetch_social_data.py --days 90
        
    The new script uses:
    - TimescaleDB with ProductionDBManager
    - Dedicated social_data table (not market_events)
    - Proper LunarCrush ID mapping for accuracy
    - Improved error handling and batch processing
    
    This function will be removed in a future version.
    """
    logger.error("⚠️  fetch_and_store_social_data() is DEPRECATED!")
    logger.error("Please use: python src/scripts/fetch_social_data.py --days 90")
    logger.error("This function uses outdated SQLAlchemy models and stores data incorrectly.")
    return False


def update_token_metadata_from_lunarcrush(symbols: Optional[List[str]] = None) -> int:
    """
    ⚠️  DEPRECATED FUNCTION ⚠️
    
    This function uses old SQLAlchemy Token model.
    
    Token metadata updates are now handled automatically during social data fetching.
    Use: python src/scripts/fetch_social_data.py --days 90
    
    This function will be removed in a future version.
    """
    logger.error("⚠️  update_token_metadata_from_lunarcrush() is DEPRECATED!")
    logger.error("Token metadata is now updated automatically during social data fetching.")
    logger.error("Use: python src/scripts/fetch_social_data.py --days 90")
    return 0


if __name__ == "__main__":
    # Example usage
    fetch_and_store_social_data("FART", interval="1h", days=7)
    update_token_metadata_from_lunarcrush(["FART", "BONK", "WIF"]) 