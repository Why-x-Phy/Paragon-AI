#!/usr/bin/env python
"""
Script to fetch and store historical OHLCV data from BirdEye API
with support for multiple API keys, configurable resolution, and time periods.

Usage:
    python src/scripts/fetch_historical_data.py --token-address 3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh --resolution 1H --days 90 --max-workers 4
"""

import os
import sys
import argparse
import time
import asyncio
from datetime import datetime, timedelta
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
import random
import logging
import concurrent.futures
from tqdm import tqdm
from dotenv import load_dotenv
from pathlib import Path

# Find and load environment variables from .env file
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent.parent  # Navigate to project root
root_env_path = project_root / '.env'

if root_env_path.exists():
    load_dotenv(root_env_path)
else:
    # Fallback to the current directory
    current_dir_env = current_file.parent.parent.parent / '.env'
    if current_dir_env.exists():
        load_dotenv(current_dir_env)
    else:
        # Last resort, try default behavior
        load_dotenv()

# Add the project root directory to sys.path to import project modules
current_dir = os.path.dirname(os.path.abspath(__file__))
scripts_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(scripts_dir)
sys.path.append(project_root)

from src.data.birdeye_api import BirdEyeAPI
from src.database.production_db import ProductionDBManager, TokenInfo, OHLCVData
from src.utils.logger import log_manager

logger = log_manager.get_logger("fetch_historical_data")

# Configure API keys - rotate through these to avoid rate limiting
API_KEYS = [
    os.environ.get("BIRDEYE_API_KEY_1", ""),
    os.environ.get("BIRDEYE_API_KEY_2", ""),
    os.environ.get("BIRDEYE_API_KEY_3", ""),
    os.environ.get("BIRDEYE_API_KEY_4", ""),
    os.environ.get("BIRDEYE_API_KEY_5", ""),
    os.environ.get("BIRDEYE_API_KEY_6", ""),
    os.environ.get("BIRDEYE_API_KEY_7", ""),
]
# Filter out empty API keys
API_KEYS = [key for key in API_KEYS if key]

if not API_KEYS:
    raise ValueError("No BirdEye API keys found. Please set BIRDEYE_API_KEY_1, BIRDEYE_API_KEY_2, etc.")

class APIKeyRotator:
    """Rotate through multiple API keys to avoid rate limiting"""
    
    def __init__(self, api_keys: List[str]):
        self.api_keys = api_keys
        self.current_index = 0
        self.api_instances = {}
        
    def get_api_instance(self) -> BirdEyeAPI:
        """Get a BirdEye API instance with the next API key"""
        key = self.api_keys[self.current_index]
        
        # Create API instance if it doesn't exist
        if key not in self.api_instances:
            self.api_instances[key] = BirdEyeAPI(api_key=key)
        
        # Rotate to next key for next call
        self.current_index = (self.current_index + 1) % len(self.api_keys)
        
        return self.api_instances[key]

def get_aligned_timestamps(
    days: int,
    resolution: str
) -> Tuple[int, int, List[Tuple[int, int]]]:
    """
    Get aligned start and end timestamps for data fetching.
    Also return chunked time ranges for pagination.
    
    Args:
        days: Number of days of historical data to fetch
        resolution: Time resolution (1m, 5m, 15m, 1H, 4H, 1d)
        
    Returns:
        Tuple of (aligned_start_timestamp, aligned_end_timestamp, chunks)
        where chunks is a list of (chunk_start, chunk_end) tuples
    """
    # Resolution in seconds
    resolution_seconds = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1H": 3600,
        "4H": 14400,
        "1d": 86400
    }.get(resolution, 300)  # Default to 5m
    
    # Calculate end time (now, aligned to resolution boundary)
    now = datetime.now()
    # Round down to nearest resolution boundary
    aligned_end = now.replace(
        minute=(now.minute // (resolution_seconds // 60)) * (resolution_seconds // 60),
        second=0,
        microsecond=0
    )
    aligned_end_timestamp = int(aligned_end.timestamp())
    
    # Calculate start time (days ago from aligned end, also aligned)
    aligned_start = aligned_end - timedelta(days=days)
    aligned_start_timestamp = int(aligned_start.timestamp())
    
    # Calculate chunks based on BirdEye's 1000 record limit
    max_records_per_chunk = 1000
    records_needed = (days * 24 * 60 * 60) // resolution_seconds
    chunk_size_seconds = resolution_seconds * max_records_per_chunk
    
    chunks = []
    for chunk_start in range(aligned_start_timestamp, aligned_end_timestamp, chunk_size_seconds):
        chunk_end = min(chunk_start + chunk_size_seconds, aligned_end_timestamp)
        chunks.append((chunk_start, chunk_end))
    
    return aligned_start_timestamp, aligned_end_timestamp, chunks

def fetch_chunk(
    chunk_start: int, 
    chunk_end: int, 
    token_address: str, 
    resolution: str,
    api_rotator: APIKeyRotator
) -> pd.DataFrame:
    """Fetch a single chunk of OHLCV data"""
    # Get a fresh API instance for the chunk (with key rotation)
    api = api_rotator.get_api_instance()
    
    try:
        # Fetch data for this chunk
        df = api.get_token_ohlcv(
            token_address=token_address,
            resolution=resolution,
            time_from=chunk_start,
            time_to=chunk_end
        )
        
        if df.empty:
            logger.warning(f"No data returned for chunk ({datetime.fromtimestamp(chunk_start)} to {datetime.fromtimestamp(chunk_end)})")
            return pd.DataFrame()
            
        return df
        
    except Exception as e:
        logger.error(f"Error fetching chunk: {e}")
        return pd.DataFrame()

async def validate_token(token_address: str, api_rotator: APIKeyRotator, db_manager: ProductionDBManager) -> Optional[TokenInfo]:
    """
    Validate the token address and fetch its metadata
    
    Args:
        token_address: Token address to validate
        api_rotator: API key rotator
        db_manager: Database manager instance
        
    Returns:
        TokenInfo object or None if invalid
    """
    # Check if token already exists in database
    existing_token = db_manager.get_token_by_address(token_address)
    if existing_token:
        logger.info(f"Token found in database: {existing_token.symbol} ({existing_token.name})")
        return existing_token
    
    # Fetch from API if not in database
    api = api_rotator.get_api_instance()
    try:
        logger.info(f"Validating token address: {token_address}")
        metadata = api.get_token_metadata(token_address)
        
        if not metadata.get('success') or 'data' not in metadata:
            logger.error(f"Invalid token address: {token_address}")
            return None
            
        token_data = metadata['data']
        symbol = token_data.get('symbol', 'UNKNOWN')
        name = token_data.get('name', 'Unknown Token')
        decimals = token_data.get('decimals', 9)
        
        logger.info(f"Token validated: {symbol} ({name}), decimals: {decimals}")
        
        # Add token to database
        token_info = await db_manager.add_token(
            address=token_address,
            symbol=symbol,
            name=name,
            decimals=decimals
        )
        
        logger.info(f"Added token to database: {symbol} ({token_address})")
        return token_info
        
    except Exception as e:
        logger.error(f"Error validating token address: {e}")
        return None

def convert_df_to_ohlcv_data(df: pd.DataFrame, token_id: int, resolution: str) -> List[OHLCVData]:
    """Convert DataFrame to OHLCVData objects"""
    ohlcv_data = []
    
    for _, row in df.iterrows():
        # Convert timestamp to datetime
        if 'unixTime' in row:
            timestamp = datetime.fromtimestamp(row['unixTime'])
        elif 'time' in row:
            timestamp = pd.to_datetime(row['time'])
        else:
            logger.warning("No timestamp column found in data")
            continue
            
        ohlcv = OHLCVData(
            time=timestamp,
            token_id=token_id,
            resolution=resolution,
            open=float(row.get('o', row.get('open', 0))),
            high=float(row.get('h', row.get('high', 0))),
            low=float(row.get('l', row.get('low', 0))),
            close=float(row.get('c', row.get('close', 0))),
            volume=float(row.get('v', row.get('volume', 0))),
            volume_usd=float(row.get('volume_usd', 0)) if row.get('volume_usd') else None,
            trades_count=int(row.get('trades_count', 0)) if row.get('trades_count') else None,
            data_source='birdeye'
        )
        ohlcv_data.append(ohlcv)
    
    return ohlcv_data

async def fetch_and_store_data(
    token_info: TokenInfo,
    resolution: str,
    days: int,
    api_rotator: APIKeyRotator,
    db_manager: ProductionDBManager,
    batch_size: int = 2000,
    delay_between_chunks: float = 1.0,
    max_workers: int = 5
) -> Dict[str, Any]:
    """
    Fetch historical OHLCV data and store it in TimescaleDB
    
    Args:
        token_info: Token information from database
        resolution: Time resolution (1m, 5m, 15m, 1H, 4H, 1d)
        days: Number of days of historical data to fetch
        api_rotator: API key rotator
        db_manager: Database manager instance
        batch_size: Number of records to insert in a single database operation
        delay_between_chunks: Delay between API calls in seconds
        max_workers: Maximum number of parallel workers for fetching data
        
    Returns:
        Dict with summary of operation
    """    
    # Get aligned timestamps and chunks
    start_timestamp, end_timestamp, chunks = get_aligned_timestamps(days, resolution)
    logger.info(f"Fetching {len(chunks)} chunks of data for {token_info.symbol} from {datetime.fromtimestamp(start_timestamp)} to {datetime.fromtimestamp(end_timestamp)}")
    
    # Statistics
    total_records = 0
    stored_records = 0
    duplicate_records = 0
    
    # Progress bar
    progress_bar = tqdm(total=len(chunks), desc=f"Fetching {resolution} OHLCV data")
    
    # Calculate the number of groups to process (to maintain rate limits)
    # Process chunks in parallel within each group
    chunk_groups = [chunks[i:i + max_workers] for i in range(0, len(chunks), max_workers)]
    
    for group_idx, chunk_group in enumerate(chunk_groups):
        # Fetch chunks in parallel
        chunk_results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks for this group
            futures = {
                executor.submit(
                    fetch_chunk, 
                    chunk_start, 
                    chunk_end, 
                    token_info.address, 
                    resolution, 
                    api_rotator
                ): (i, (chunk_start, chunk_end)) 
                for i, (chunk_start, chunk_end) in enumerate(chunk_group)
            }
            
            # Process results as they complete
            for future in concurrent.futures.as_completed(futures):
                idx, (chunk_start, chunk_end) = futures[future]
                try:
                    df = future.result()
                    if not df.empty:
                        chunk_results.append(df)
                        logger.info(f"Successfully fetched chunk ({datetime.fromtimestamp(chunk_start)} to {datetime.fromtimestamp(chunk_end)}): {len(df)} records")
                    
                    # Update progress bar
                    progress_bar.update(1)
                except Exception as e:
                    logger.error(f"Error processing chunk result: {e}")
                    progress_bar.update(1)
        
        # Combine all dataframes from this group
        if chunk_results:
            combined_df = pd.concat(chunk_results, ignore_index=True)
            total_chunk_records = len(combined_df)
            total_records += total_chunk_records
            
            # Process in larger batches for database efficiency
            for batch_start in range(0, len(combined_df), batch_size):
                batch_end = min(batch_start + batch_size, len(combined_df))
                batch_df = combined_df.iloc[batch_start:batch_end]
                
                # Convert DataFrame to OHLCVData objects
                ohlcv_data = convert_df_to_ohlcv_data(batch_df, token_info.token_id, resolution)
                
                # Insert into TimescaleDB
                try:
                    inserted_count = await db_manager.insert_ohlcv_data(ohlcv_data)
                    stored_records += inserted_count
                    logger.info(f"Stored {inserted_count} records in batch")
                except Exception as e:
                    logger.error(f"Error storing batch: {e}")
                    # Continue with next batch
            
            logger.info(f"Processed group {group_idx+1}/{len(chunk_groups)}: {total_chunk_records} records")
        
        # Delay between groups to avoid rate limiting
        if group_idx < len(chunk_groups) - 1:
            time.sleep(delay_between_chunks * 2)  # Slightly longer delay between groups
    
    progress_bar.close()
    
    # Summary
    return {
        "token": token_info.symbol,
        "resolution": resolution,
        "days": days,
        "start_date": datetime.fromtimestamp(start_timestamp),
        "end_date": datetime.fromtimestamp(end_timestamp),
        "total_records_fetched": total_records,
        "records_stored": stored_records,
        "duplicate_records": duplicate_records
    }

async def fetch_data_for_all_tokens(
    resolution: str = "1H",
    days: int = 90,
    batch_size: int = 2000,
    delay_between_chunks: float = 1.0,
    delay_between_tokens: float = 1.0,
    max_workers: int = 5
):
    """Fetch historical OHLCV data for all active tokens in the database
    
    Args:
        resolution: Time resolution (1m, 5m, 15m, 1H, 4H, 1d)
        days: Number of days of historical data to fetch
        batch_size: Number of records to insert in a single database operation
        delay_between_chunks: Delay between API calls in seconds
        delay_between_tokens: Delay between processing different tokens in seconds
        max_workers: Maximum number of parallel workers for fetching data
    """
    # Initialize database manager
    db_manager = ProductionDBManager()
    try:
        await db_manager.initialize()
        logger.info("Database connection established")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        return
    
    try:
        # Initialize API key rotator
        api_rotator = APIKeyRotator(API_KEYS)
        
        # Get all active tokens
        active_tokens = await db_manager.get_active_tokens()
        
        if not active_tokens:
            logger.warning("No active tokens found in database")
            return
        
        logger.info(f"Fetching {days} days of {resolution} historical data for {len(active_tokens)} tokens")
        
        # Warn if fetching a large amount of data
        if days > 180:
            logger.warning(f"Fetching {days} days of data - this may take a very long time and could be rate limited")
        
        success_count = 0
        failed_count = 0
        total_records_fetched = 0
        total_records_stored = 0
        
        # Process tokens one by one
        for i, token_data in enumerate(active_tokens, 1):
            try:
                symbol = token_data['symbol']
                address = token_data['address']
                token_id = token_data['token_id']
                
                logger.info(f"[{i}/{len(active_tokens)}] Processing {symbol} ({address})")
                
                # Create TokenInfo object from database data
                token_info = TokenInfo(
                    token_id=token_id,
                    address=address,
                    symbol=symbol,
                    name=token_data.get('name', symbol),
                    decimals=token_data.get('decimals', 9),
                    is_active=token_data.get('is_active', True)
                )
                
                # Fetch and store data for this token
                start_time = time.time()
                result = await fetch_and_store_data(
                    token_info=token_info,
                    resolution=resolution,
                    days=days,
                    api_rotator=api_rotator,
                    db_manager=db_manager,
                    batch_size=batch_size,
                    delay_between_chunks=delay_between_chunks,
                    max_workers=max_workers
                )
                elapsed_time = time.time() - start_time
                
                if result['records_stored'] > 0:
                    success_count += 1
                    total_records_fetched += result['total_records_fetched']
                    total_records_stored += result['records_stored']
                    logger.info(f"✅ Successfully fetched {result['records_stored']} records for {symbol} in {elapsed_time:.2f}s")
                else:
                    failed_count += 1
                    logger.warning(f"❌ No records stored for {symbol}")
                
                # Sleep between tokens to avoid hitting rate limits
                if i < len(active_tokens):
                    logger.info(f"Sleeping {delay_between_tokens:.1f}s before processing next token")
                    await asyncio.sleep(delay_between_tokens)
                
            except Exception as e:
                failed_count += 1
                logger.error(f"❌ Error fetching historical data for {symbol}: {e}")
                
                # Still sleep to avoid hammering the API
                if i < len(active_tokens):
                    await asyncio.sleep(delay_between_tokens)
        
        # Final summary
        logger.info(f"\n🏁 Historical data fetch completed:")
        logger.info(f"   ✅ Success: {success_count}/{len(active_tokens)} tokens")
        logger.info(f"   ❌ Failed: {failed_count}/{len(active_tokens)} tokens")
        logger.info(f"   📊 Total records fetched: {total_records_fetched:,}")
        logger.info(f"   💾 Total records stored: {total_records_stored:,}")
        logger.info(f"   ⏱️  Resolution: {resolution}")
        logger.info(f"   📅 Period: {days} days")
        
    finally:
        # Close database connections
        await db_manager.close()
        logger.info("Database connections closed")

async def main_async():
    """Async main function to handle database operations"""
    parser = argparse.ArgumentParser(description="Fetch historical OHLCV data from BirdEye API")
    
    parser.add_argument(
        "--token-address", 
        type=str, 
        help="Solana token address (required unless --all-tokens is used)"
    )
    
    parser.add_argument(
        "--all-tokens",
        action="store_true",
        help="Fetch data for all active tokens in the database"
    )
    
    parser.add_argument(
        "--resolution", 
        type=str, 
        default="1H",
        choices=["1m", "5m", "15m", "1H", "4H", "1d"],
        help="Time resolution"
    )
    
    parser.add_argument(
        "--days", 
        type=int, 
        default=90,
        help="Number of days of historical data to fetch"
    )
    
    parser.add_argument(
        "--batch-size", 
        type=int, 
        default=2000,
        help="Number of records to insert in a single database operation"
    )
    
    parser.add_argument(
        "--delay", 
        type=float, 
        default=1.0,
        help="Delay between API calls in seconds"
    )
    
    parser.add_argument(
        "--delay-between-tokens", 
        type=float, 
        default=1.0,
        help="Delay between processing different tokens in seconds (for --all-tokens)"
    )
    
    parser.add_argument(
        "--max-workers", 
        type=int, 
        default=5,
        help="Maximum number of parallel workers for fetching data"
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.all_tokens and not args.token_address:
        parser.error("Either --token-address or --all-tokens must be specified")
    
    if args.all_tokens and args.token_address:
        parser.error("Cannot use both --token-address and --all-tokens at the same time")
    
    # Warn if fetching a large amount of data
    if args.days > 180:
        logger.warning(f"Fetching {args.days} days of data - this may take a very long time and could be rate limited")
        if not args.all_tokens:
            logger.info("For large data fetches, consider using smaller day ranges or higher resolution intervals")
    
    try:
        if args.all_tokens:
            # Fetch data for all tokens
            await fetch_data_for_all_tokens(
                resolution=args.resolution,
                days=args.days,
                batch_size=args.batch_size,
                delay_between_chunks=args.delay,
                delay_between_tokens=args.delay_between_tokens,
                max_workers=args.max_workers
            )
        else:
            # Original single token logic
            # Initialize database manager
            db_manager = ProductionDBManager()
            try:
                await db_manager.initialize()
                logger.info("Database connection established")
            except Exception as e:
                logger.error(f"Failed to initialize database: {e}")
                sys.exit(1)
            
            try:
                # Initialize API key rotator
                api_rotator = APIKeyRotator(API_KEYS)
                
                # Validate token and get/create in database
                token_info = await validate_token(args.token_address, api_rotator, db_manager)
                if not token_info:
                    logger.error("Token validation failed. Please check the token address and try again.")
                    sys.exit(1)
                
                # Fetch and store data
                logger.info(f"Starting historical data fetch for {token_info.symbol} ({args.token_address}) with resolution {args.resolution} for {args.days} days")
                
                start_time = time.time()
                result = await fetch_and_store_data(
                    token_info=token_info,
                    resolution=args.resolution,
                    days=args.days,
                    api_rotator=api_rotator,
                    db_manager=db_manager,
                    batch_size=args.batch_size,
                    delay_between_chunks=args.delay,
                    max_workers=args.max_workers
                )
                elapsed_time = time.time() - start_time
                
                # Print summary
                logger.info("=" * 50)
                logger.info(f"Data fetch completed in {elapsed_time:.2f} seconds")
                logger.info(f"Token: {result['token']}")
                logger.info(f"Resolution: {result['resolution']}")
                logger.info(f"Period: {result['start_date']} to {result['end_date']} ({result['days']} days)")
                logger.info(f"Records fetched: {result['total_records_fetched']}")
                logger.info(f"Records stored: {result['records_stored']}")
                logger.info(f"Duplicate records: {result['duplicate_records']}")
                logger.info("=" * 50)
                
            finally:
                # Close database connections
                await db_manager.close()
                logger.info("Database connections closed")
        
    except KeyboardInterrupt:
        logger.info("Historical data fetcher stopped by user")
    except Exception as e:
        logger.error(f"Error in historical data fetcher: {e}")

def main():
    """Main function to run async operations"""
    asyncio.run(main_async())

if __name__ == "__main__":
    main() 