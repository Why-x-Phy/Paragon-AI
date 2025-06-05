#!/usr/bin/env python3
"""
Script to fetch social data for tokens from LunarCrush API

Usage:
    python src/scripts/fetch_social_data.py --days 90
    python src/scripts/fetch_social_data.py --schedule <minutes>
"""
import os
import sys
import time
import argparse
import schedule
import asyncio
from datetime import datetime
from loguru import logger
import random
from typing import List, Optional

# Add the parent directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.config.config import config
from src.database.production_db import ProductionDBManager
from src.utils.social_data_fetcher import LunarCrushAPI

def setup_logger(log_level="INFO"):
    """Setup logger with appropriate log level"""
    logger.remove()  # Remove default handler
    logger.add(sys.stderr, level=log_level)
    
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    logger.add(
        os.path.join("logs", f"social_data_fetcher_{datetime.now().strftime('%Y%m%d')}.log"),
        rotation="500 MB",
        level=log_level,
    )

async def fetch_and_store_social_data_timescale(
    symbol: str, 
    interval: str = "1w", 
    days: int = 30,
    batch_size: int = 100,
    token_data: dict = None
) -> bool:
    """
    Fetch social data from LunarCrush API and store in TimescaleDB
    
    Args:
        symbol: Token symbol to fetch data for
        interval: Data resolution interval (e.g., '1w' for 1 week)
        days: Number of days of history to fetch
        batch_size: Number of records to process in each database batch
        token_data: Pre-fetched token data (optional, to avoid duplicate DB queries)
        
    Returns:
        bool: True if successful, False otherwise
    """
    db_manager = ProductionDBManager()
    api = LunarCrushAPI()
    
    try:
        await db_manager.initialize()
        
        # Use provided token_data or fetch from database
        if not token_data:
            # Get or create token in database - FIXED to prevent duplicates
            token_data = None
            
            # Try to find existing token by address first (most reliable)
            try:
                # Check if we have this token by symbol with fuzzy matching
                existing_tokens = await db_manager.get_active_tokens()
                for token in existing_tokens:
                    # Clean both symbols for comparison (remove spaces, normalize case)
                    db_symbol = token['symbol'].strip().upper()
                    input_symbol = symbol.strip().upper()
                    
                    if db_symbol == input_symbol:
                        logger.info(f"Found existing token: {token['symbol']} (ID: {token['token_id']}) for {symbol}")
                        token_data = token
                        break
                        
                # If still not found, try partial matches (for cases like "Fartcoin " vs "FARTCOIN")
                if not token_data:
                    for token in existing_tokens:
                        db_symbol_clean = token['symbol'].strip().upper().replace(' ', '')
                        input_symbol_clean = symbol.strip().upper().replace(' ', '')
                        
                        if db_symbol_clean == input_symbol_clean:
                            logger.info(f"Found existing token via fuzzy match: {token['symbol']} (ID: {token['token_id']}) for {symbol}")
                            token_data = token
                            break
                            
            except Exception as e:
                logger.warning(f"Error searching for existing token {symbol}: {e}")
            
            # Only create new token if absolutely not found
            if not token_data:
                logger.warning(f"No existing token found for {symbol} - creating new token (this should be rare!)")
                token_data = await db_manager.get_or_create_token(
                    address="",  # LunarCrush doesn't always provide addresses
                    symbol=symbol.upper(),
                    name=symbol  # Will be updated if we get better data from API
                )
        
        if not token_data:
            logger.error(f"Failed to get/create token for {symbol}")
            return False
            
        token_id = token_data['token_id']
        logger.info(f"Using token_id {token_id} for {symbol}")
        
        # Extract LunarCrush data from token - NEW LUNARCRUSH ID SUPPORT
        lunarcrush_id = token_data.get('lunarcrush_id')
        token_address = token_data.get('address')
        
        if lunarcrush_id:
            logger.info(f"🎯 Using LunarCrush ID {lunarcrush_id} for {symbol} - this ensures accurate data!")
        elif token_address:
            logger.info(f"Using token address {token_address} for {symbol}")
        else:
            logger.warning(f"⚠️  No LunarCrush ID or address for {symbol} - using symbol fallback (may get wrong token data)")
        
        # Fetch social data from LunarCrush with improved API
        try:
            social_data = api.get_asset_data(
                symbol=symbol, 
                address=token_address, 
                lunarcrush_id=lunarcrush_id,  # NEW: Pass LunarCrush ID
                interval=interval, 
                days=days
            )
            if not social_data:
                logger.warning(f"No social data returned for {symbol}")
                return False
                
            logger.info(f"Fetched {len(social_data)} social data points for {symbol}")
            
            # Store data using the new social_data table
            stored_count = 0
            for data_point in social_data:
                try:
                    # Convert LunarCrush data to format compatible with social_data table
                    social_metrics = {
                        # Timestamp handling
                        'time': datetime.fromtimestamp(data_point.get("time", 0)) if data_point.get("time") else datetime.now(),
                        
                        # Core social metrics (hourly data from API)
                        'sentiment': data_point.get('sentiment'),
                        'galaxy_score': data_point.get('galaxy_score'),
                        'alt_rank': data_point.get('alt_rank'),
                        'social_dominance': data_point.get('social_dominance'),
                        'interactions': data_point.get('interactions'),  # Hourly interactions
                        
                        # Social engagement metrics (hourly data)
                        'contributors_active': data_point.get('contributors_active'),
                        'contributors_created': data_point.get('contributors_created'),
                        'posts_active': data_point.get('posts_active'),
                        'posts_created': data_point.get('posts_created'),
                        'spam': data_point.get('spam'),
                        
                        # Market metrics included in social data
                        'market_dominance': data_point.get('market_dominance'),
                        'market_cap': data_point.get('market_cap'),
                        'circulating_supply': data_point.get('circulating_supply'),
                        'close_price': data_point.get('close'),
                        'open_price': data_point.get('open'),
                        'high_price': data_point.get('high'),
                        'low_price': data_point.get('low'),
                        'volume_24h': data_point.get('volume_24h'),  # 24h rolling volume from API
                        
                        # Data source tracking
                        'data_source': 'lunarcrush',
                        'lunarcrush_id': lunarcrush_id
                    }
                    
                    # Store using the new dedicated social_data table
                    success = await db_manager.store_social_data(token_id, social_metrics)
                    if success:
                        stored_count += 1
                    
                except Exception as e:
                    logger.error(f"Error storing social data point for {symbol}: {e}")
                    continue
            
            logger.info(f"Successfully stored {stored_count}/{len(social_data)} social data points for {symbol}")
            return stored_count > 0
            
        except Exception as e:
            logger.error(f"Error fetching social data from LunarCrush for {symbol}: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Database error for {symbol}: {e}")
        return False
    finally:
        await db_manager.close()

async def fetch_data_for_all_tokens(interval="1w", days=30, batch_size=100):
    """Fetch social data for all active tokens in the database
    
    Args:
        interval: Data resolution interval (e.g., '1w' for 1 week)
        days: Number of days of history to fetch
        batch_size: Number of records to process in each database batch
    """
    db_manager = ProductionDBManager()
    
    try:
        await db_manager.initialize()
        
        # Get all active tokens with LunarCrush data
        tokens = await db_manager.get_active_tokens()
        
        if not tokens:
            logger.warning("No active tokens found in database")
            return
        
        # Filter and categorize tokens by their LunarCrush status
        tokens_with_lunarcrush = []
        tokens_with_address = []
        tokens_symbol_only = []
        
        for token in tokens:
            if token.get('lunarcrush_id'):
                tokens_with_lunarcrush.append(token)
            elif token.get('address'):
                tokens_with_address.append(token)
            else:
                tokens_symbol_only.append(token)
        
        logger.info(f"Fetching {days} days of social data for {len(tokens)} tokens:")
        logger.info(f"  📍 {len(tokens_with_lunarcrush)} tokens with LunarCrush IDs (most accurate)")
        logger.info(f"  🏠 {len(tokens_with_address)} tokens with addresses only")
        logger.info(f"  🔤 {len(tokens_symbol_only)} tokens with symbols only (least reliable)")
        
        # Warn if fetching a large amount of data
        if days > 90:
            logger.warning(f"Fetching {days} days of data - this may take a while and could be rate limited")
        
        # Process tokens in order of reliability (LunarCrush ID first)
        all_tokens_ordered = tokens_with_lunarcrush + tokens_with_address + tokens_symbol_only
        
        success_count = 0
        failed_count = 0
        
        # Fetch data for each token
        for i, token in enumerate(all_tokens_ordered, 1):
            try:
                symbol = token['symbol']
                lunarcrush_id = token.get('lunarcrush_id')
                address = token.get('address')
                
                # Log the fetching method being used
                if lunarcrush_id:
                    method_info = f"🎯 LunarCrush ID {lunarcrush_id}"
                elif address:
                    method_info = f"🏠 Address {address[:8]}..."
                else:
                    method_info = f"🔤 Symbol only"
                
                logger.info(f"[{i}/{len(all_tokens_ordered)}] Fetching {symbol} using {method_info}")
                
                result = await fetch_and_store_social_data_timescale(
                    symbol=symbol, 
                    interval=interval, 
                    days=days, 
                    batch_size=batch_size,
                    token_data=token  # Pass complete token data to avoid duplicate DB queries
                )
                
                if result:
                    success_count += 1
                    logger.info(f"✅ Successfully fetched social data for {symbol}")
                else:
                    failed_count += 1
                    logger.warning(f"❌ Failed to fetch social data for {symbol}")
                
                # Sleep between tokens to avoid hitting rate limits
                # More conservative rate limiting between tokens
                sleep_time = random.uniform(8, 12)  # 8-12 seconds between tokens
                logger.info(f"Sleeping {sleep_time:.2f}s before processing next token")
                await asyncio.sleep(sleep_time)
                
            except Exception as e:
                failed_count += 1
                logger.error(f"❌ Error fetching social data for {symbol}: {e}")
        
        # Final summary
        logger.info(f"\n🏁 Social data fetch completed:")
        logger.info(f"   ✅ Success: {success_count}/{len(all_tokens_ordered)} tokens")
        logger.info(f"   ❌ Failed: {failed_count}/{len(all_tokens_ordered)} tokens")
        
        if tokens_symbol_only:
            logger.warning(f"\n⚠️  {len(tokens_symbol_only)} tokens have no LunarCrush ID or address mapping.")
            logger.warning("   Consider running the LunarCrush ID mapping script to improve accuracy:")
            logger.warning("   docker/scripts/setup.sh lunarcrush")
        
    except Exception as e:
        logger.error(f"Error in fetch_data_for_all_tokens: {e}")
    finally:
        await db_manager.close()

def run_scheduled_fetcher(interval="1w", days=30, schedule_interval=60, batch_size=100):
    """Run the social data fetcher on a schedule
    
    Args:
        interval: Data resolution interval (e.g., '1w' for 1 week)
        days: Number of days of history to fetch
        schedule_interval: Minutes between scheduled runs
        batch_size: Number of records to process in each database batch
    """
    logger.info(f"Starting scheduled social data fetcher (every {schedule_interval} minutes)")
    
    # Define async wrapper for scheduled job
    def scheduled_job():
        asyncio.run(fetch_data_for_all_tokens(interval=interval, days=days, batch_size=batch_size))
    
    # Schedule the job
    schedule.every(schedule_interval).minutes.do(scheduled_job)
    
    # Run immediately on startup
    asyncio.run(fetch_data_for_all_tokens(interval=interval, days=days, batch_size=batch_size))
    
    # Keep the script running
    while True:
        schedule.run_pending()
        time.sleep(1)

async def main_async(args):
    """Async main function"""
    # Warn if fetching a large amount of data
    if args.days > 90:
        logger.warning(f"Fetching {args.days} days of data - this may take a while and could be rate limited")
        if not args.log_level.upper() == "DEBUG":
            logger.info("For large data fetches, consider using --log-level DEBUG for more detailed progress")
    
    try:
        if args.symbol:
            # Fetch data for specific token
            logger.info(f"Fetching {args.days} days of social data for {args.symbol}")
            
            # Check if we have this token in the database to get its address
            db_manager = ProductionDBManager()
            try:
                await db_manager.initialize()
                token_data = await db_manager.get_token_by_symbol(args.symbol.upper())
                if token_data and token_data.get('address'):
                    logger.info(f"Found token address: {token_data['address']} for {args.symbol}")
                else:
                    logger.warning(f"No token address found for {args.symbol} - will use symbol for API call")
            except Exception as e:
                logger.warning(f"Error checking database for token {args.symbol}: {e}")
            finally:
                await db_manager.close()
            
            result = await fetch_and_store_social_data_timescale(
                args.symbol, 
                interval=args.interval, 
                days=args.days,
                batch_size=args.batch_size
            )
            if result:
                logger.info(f"Successfully fetched social data for {args.symbol}")
            else:
                logger.error(f"Failed to fetch social data for {args.symbol}")
        else:
            # Fetch data for all tokens once
            await fetch_data_for_all_tokens(args.interval, args.days, args.batch_size)
    
    except Exception as e:
        logger.error(f"Error in social data fetcher: {e}")

def main():
    """Main entry point for the script"""
    parser = argparse.ArgumentParser(description="Fetch social data for tokens from LunarCrush API")
    parser.add_argument("--symbol", "-s", type=str, help="Token symbol to fetch data for (default: all active tokens)")
    parser.add_argument("--interval", "-i", type=str, default="1w", help="Data resolution interval (e.g., '1w' for 1 week)")
    parser.add_argument("--days", "-d", type=int, default=30, help="Number of days of history to fetch (default: 30, can fetch months of data)")
    parser.add_argument("--batch-size", "-b", type=int, default=100, help="Number of records to process in each database batch")
    parser.add_argument("--schedule", "-t", type=int, default=0, help="Minutes between scheduled runs (0 = run once)")
    parser.add_argument("--log-level", "-l", type=str, default="INFO", help="Log level")
    
    args = parser.parse_args()
    
    # Setup logger
    setup_logger(args.log_level)
    
    try:
        if args.schedule > 0:
            # Run on a schedule (this uses sync wrapper due to schedule library limitations)
            run_scheduled_fetcher(args.interval, args.days, args.schedule, args.batch_size)
        else:
            # Run once (async)
            asyncio.run(main_async(args))
    
    except KeyboardInterrupt:
        logger.info("Social data fetcher stopped by user")
    except Exception as e:
        logger.error(f"Error in social data fetcher: {e}")

if __name__ == "__main__":
    main() 