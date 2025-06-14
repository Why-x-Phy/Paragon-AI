import time
import requests
import pandas as pd
from typing import Dict, List, Optional, Union, Any
from datetime import datetime, timedelta

from ..config.config import config
from ..utils.logger import log_manager

logger = log_manager.get_logger("lunarcrush_api")

class LunarCrushAPI:
    """Client for the LunarCrush API to fetch social sentiment data"""
    
    BASE_URL = "https://lunarcrush.com/api/v2"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.lunarcrush_api_key
        if not self.api_key:
            raise ValueError("LunarCrush API key is required")
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make a request to the LunarCrush API"""
        url = f"{self.BASE_URL}/{endpoint}"
        
        # Add API key to parameters
        params = params or {}
        params["key"] = self.api_key
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making request to LunarCrush API: {e}")
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            raise
    
    def get_coin_info(self, symbol: str = "SOL") -> Dict:
        """Get detailed information about a specific coin"""
        endpoint = "assets"
        params = {
            "symbol": symbol,
            "data": "full"
        }
        
        response = self._make_request(endpoint, params)
        
        if "data" not in response or not response["data"]:
            logger.error(f"Invalid response format or coin not found: {response}")
            raise ValueError(f"Invalid response or coin {symbol} not found")
        
        logger.info(f"Got coin info for {symbol}")
        return response["data"][0]
    
    def get_coin_list(self, limit: int = 100) -> List[Dict]:
        """Get a list of coins with basic information"""
        endpoint = "assets"
        params = {
            "limit": limit,
            "sort": "mc",  # Market cap
            "desc": True
        }
        
        response = self._make_request(endpoint, params)
        
        if "data" not in response or not response["data"]:
            logger.error(f"Invalid response format: {response}")
            raise ValueError("Invalid response format")
        
        logger.info(f"Got list of {len(response['data'])} coins")
        return response["data"]
    
    def get_social_feeds(self, symbol: str = "SOL", limit: int = 50) -> List[Dict]:
        """Get social media feeds related to a coin"""
        endpoint = "feeds"
        params = {
            "symbol": symbol,
            "limit": limit
        }
        
        response = self._make_request(endpoint, params)
        
        if "data" not in response or not response["data"]:
            logger.error(f"Invalid response format: {response}")
            raise ValueError("Invalid response format")
        
        logger.info(f"Got {len(response['data'])} social feeds for {symbol}")
        return response["data"]
    
    def get_influencers(self, symbol: str = "SOL", limit: int = 20) -> List[Dict]:
        """Get top influencers for a specific coin"""
        endpoint = "influencers"
        params = {
            "symbol": symbol,
            "limit": limit
        }
        
        response = self._make_request(endpoint, params)
        
        if "data" not in response or not response["data"]:
            logger.error(f"Invalid response format: {response}")
            raise ValueError("Invalid response format")
        
        logger.info(f"Got {len(response['data'])} influencers for {symbol}")
        return response["data"]
    
    def get_social_dominance(self, symbols: List[str], limit: int = 30) -> Dict:
        """
        Get social dominance comparison between multiple coins
        
        Args:
            symbols: List of coin symbols to compare
            limit: Number of days of historical data
            
        Returns:
            Dict with social dominance data
        """
        endpoint = "assets/dominance"
        params = {
            "symbol": ",".join(symbols),
            "limit": limit,
            "data": "social",
        }
        
        response = self._make_request(endpoint, params)
        
        if "data" not in response or not response["data"]:
            logger.error(f"Invalid response format: {response}")
            raise ValueError("Invalid response format")
        
        logger.info(f"Got social dominance data for {len(symbols)} coins")
        return response["data"]
    
    def get_historical_metrics(
        self, 
        symbol: str = "SOL", 
        interval: str = "1d", 
        days: int = 30
    ) -> pd.DataFrame:
        """
        Get historical metrics for a coin
        
        Args:
            symbol: Coin symbol
            interval: Time interval (1d, 1h, etc.)
            days: Number of days of historical data
            
        Returns:
            DataFrame with historical metrics
        """
        endpoint = "assets"
        params = {
            "symbol": symbol,
            "interval": interval,
            "time_series_days": days,
            "data": "full"
        }
        
        response = self._make_request(endpoint, params)
        
        if "data" not in response or not response["data"] or "timeSeries" not in response["data"][0]:
            logger.error(f"Invalid response format: {response}")
            raise ValueError("Invalid response format")
        
        # Convert to DataFrame
        ts_data = response["data"][0]["timeSeries"]
        df = pd.DataFrame(ts_data)
        
        # Format timestamps
        if "time" in df.columns:
            df["timestamp"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("timestamp", inplace=True)
        
        logger.info(f"Got historical metrics for {symbol}: {len(df)} records")
        return df
    
    def get_social_sentiment(self, symbol: str = "SOL", days: int = 30) -> pd.DataFrame:
        """
        Get social sentiment metrics for a coin
        
        Args:
            symbol: Coin symbol
            days: Number of days of historical data
            
        Returns:
            DataFrame with social sentiment metrics
        """
        df = self.get_historical_metrics(symbol, "1d", days)
        
        # Select only sentiment-related columns
        sentiment_columns = [
            "time", "social_score", "social_volume", "social_impact_score",
            "social_dominant_sentiment", "social_contributors", "social_volume_global",
            "average_sentiment", "news", "social_impact", "social_engagement"
        ]
        sentiment_columns = [col for col in sentiment_columns if col in df.columns]
        
        return df[sentiment_columns]
