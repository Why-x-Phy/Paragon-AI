#!/usr/bin/env python3
"""
LunarCrush ID Mapping Script
Maps LunarCrush internal IDs to our tracked tokens by address validation.

This script:
1. Fetches the LunarCrush coins list filtered for Solana ecosystem
2. Matches token addresses with our database tokens
3. Updates our tokens table with LunarCrush internal IDs
4. Enables accurate social data fetching without symbol conflicts

Usage:
    python map_lunarcrush_ids.py --dry-run --verbose
"""

import os
import sys
import logging
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime
import argparse

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/lunarcrush_mapping.log')
    ]
)
logger = logging.getLogger(__name__)


def load_environment():
    """Load environment variables from .env files"""
    env_files = ['../../.env', '../../.env.dev']  # Prioritize .env over .env.dev
    env_vars = {}
    
    for env_file in env_files:
        if os.path.exists(env_file):
            logger.info(f"Loading environment from {env_file}")
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key] = value
    
    return env_vars


def get_database_connection(env_vars):
    """Get database connection with multiple fallback configurations"""
    connection_configs = [
        {
            'host': env_vars.get('DB_HOST', 'localhost'),
            'port': int(env_vars.get('DB_PORT', 6432)),
            'database': env_vars.get('DB_NAME', 'calvin_trading_dev'),
            'user': env_vars.get('DB_USER', 'calvin_dev'),
            'password': env_vars.get('DB_PASSWORD', env_vars.get('DB_PASSWORD_DEV', 'calvin_dev_password'))
        },
        {
            'host': 'localhost',
            'port': 5432,
            'database': 'calvin_trading_dev',
            'user': 'calvin_dev',
            'password': 'calvin_dev_password'
        }
    ]
    
    for config in connection_configs:
        try:
            logger.info(f"Attempting database connection to {config['host']}:{config['port']}")
            conn = psycopg2.connect(**config)
            logger.info("Database connection successful")
            return conn
        except Exception as e:
            logger.warning(f"Connection failed: {e}")
            continue
    
    raise Exception("Could not establish database connection with any configuration")


def fetch_lunarcrush_coins(api_key, limit=600):
    """
    Fetch LunarCrush coins list filtered for Solana ecosystem
    
    Args:
        api_key (str): LunarCrush API key
        limit (int): Number of coins to fetch (default 600)
    
    Returns:
        list: List of coin data from LunarCrush
    """
    url = "https://lunarcrush.com/api4/public/coins/list/v1"
    params = {
        'sort': 'market_cap_rank',
        'filter': 'solana-ecosystem',
        'limit': limit
    }
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    try:
        logger.info(f"Fetching LunarCrush coins list (limit: {limit})")
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        if 'data' not in data:
            logger.error(f"Unexpected response format: {data}")
            return []
        
        coins = data['data']
        logger.info(f"Successfully fetched {len(coins)} coins from LunarCrush")
        
        # Process coins and extract Solana addresses
        solana_coins = []
        for coin in coins:
            coin_info = {
                'lunarcrush_id': coin['id'],
                'symbol': coin['symbol'],
                'name': coin['name'],
                'topic': coin.get('topic', ''),
                'market_cap_rank': coin.get('market_cap_rank'),
                'galaxy_score': coin.get('galaxy_score'),
                'categories': coin.get('categories', ''),
                'addresses': []  # Will store all possible Solana addresses
            }
            
            # Parse blockchains array to find Solana addresses
            if 'blockchains' in coin and coin['blockchains']:
                for blockchain in coin['blockchains']:
                    network = blockchain.get('network', '').lower()
                    address = blockchain.get('address', '')
                    
                    # Handle different Solana address cases
                    if network == 'solana':
                        if address and address != '0' and address.strip():
                            # Regular Solana token with address
                            coin_info['addresses'].append({
                                'address': address.strip(),
                                'type': 'solana_token',
                                'original_case': address  # Preserve original case
                            })
                        else:
                            # Native SOL (address is 0 or empty)
                            coin_info['addresses'].append({
                                'address': 'So11111111111111111111111111111111111111112',  # Wrapped SOL address
                                'type': 'native_sol',
                                'original_case': 'So11111111111111111111111111111111111111112'
                            })
                    
                    # Handle native tokens where network matches symbol
                    elif network.lower() == coin['symbol'].lower():
                        # This is a native token (like Jupiter where network="jupiter")
                        # Add known Solana addresses for specific tokens
                        known_addresses = {
                            'jupiter': 'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',
                            'jup': 'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',
                            'orca': 'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE',
                            'raydium': '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
                            'ray': '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
                        }
                        
                        token_key = network.lower()
                        symbol_key = coin['symbol'].lower()
                        
                        if token_key in known_addresses:
                            # Use known Solana address
                            coin_info['addresses'].append({
                                'address': known_addresses[token_key],
                                'type': 'known_native_token',
                                'network': network,
                                'original_case': known_addresses[token_key]
                            })
                            logger.debug(f"Mapped {coin['symbol']} (network: {network}) to known address: {known_addresses[token_key]}")
                        elif symbol_key in known_addresses:
                            # Use known Solana address by symbol
                            coin_info['addresses'].append({
                                'address': known_addresses[symbol_key],
                                'type': 'known_native_token',
                                'network': network,
                                'original_case': known_addresses[symbol_key]
                            })
                            logger.debug(f"Mapped {coin['symbol']} (symbol: {symbol_key}) to known address: {known_addresses[symbol_key]}")
                        else:
                            # Generic native token handling (fallback)
                            coin_info['addresses'].append({
                                'address': f"native_{coin['symbol'].lower()}",
                                'type': 'generic_native_token',
                                'network': network,
                                'original_case': f"native_{coin['symbol']}"
                            })
                            logger.debug(f"Using generic native token handling for {coin['symbol']} (network: {network})")
                            
                    # Special case: Handle tokens with network name that matches common token names
                    elif network in ['jupiter', 'orca', 'raydium'] and not address:
                        # These are definitely Solana ecosystem tokens even without explicit solana network
                        known_addresses = {
                            'jupiter': 'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',
                            'orca': 'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE',
                            'raydium': '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
                        }
                        
                        if network in known_addresses:
                            coin_info['addresses'].append({
                                'address': known_addresses[network],
                                'type': 'special_case_token',
                                'network': network,
                                'original_case': known_addresses[network]
                            })
                            logger.debug(f"Special case mapping: {coin['symbol']} (network: {network}) -> {known_addresses[network]}")
            
            # Handle coins that might be missing blockchain info but are known Solana tokens
            if not coin_info['addresses']:
                # Check if this is a known Solana token by symbol
                symbol_lower = coin['symbol'].lower()
                known_solana_tokens = {
                    'jup': 'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',
                    'jupiter': 'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',
                    'orca': 'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE',
                    'ray': '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
                    'raydium': '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
                    'sol': 'So11111111111111111111111111111111111111112',
                    'solana': 'So11111111111111111111111111111111111111112',
                }
                
                if symbol_lower in known_solana_tokens:
                    coin_info['addresses'].append({
                        'address': known_solana_tokens[symbol_lower],
                        'type': 'symbol_fallback_token',
                        'original_case': known_solana_tokens[symbol_lower]
                    })
                    logger.debug(f"Symbol fallback mapping: {coin['symbol']} -> {known_solana_tokens[symbol_lower]}")
            
            # Only include coins that have at least one Solana-related address
            if coin_info['addresses']:
                # Set primary address for backwards compatibility
                primary_addr = coin_info['addresses'][0]
                coin_info['address'] = primary_addr['address']
                coin_info['address_type'] = primary_addr['type']
                
                solana_coins.append(coin_info)
                
                # Log for debugging
                addr_summary = []
                for addr_info in coin_info['addresses']:
                    addr_summary.append(f"{addr_info['type']}:{addr_info['address'][:8]}...")
                
                logger.debug(f"Processed {coin['symbol']}: {', '.join(addr_summary)}")
        
        logger.info(f"Found {len(solana_coins)} coins with Solana addresses")
        
        # Log some statistics
        address_types = {}
        for coin in solana_coins:
            for addr_info in coin['addresses']:
                addr_type = addr_info['type']
                address_types[addr_type] = address_types.get(addr_type, 0) + 1
        
        logger.info(f"Address type breakdown: {address_types}")
        
        return solana_coins
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching LunarCrush data: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return []


def get_tracked_tokens(conn):
    """Get all tracked tokens from our database"""
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT token_id, address, symbol, name, lunarcrush_id, social_data_available
        FROM tokens 
        WHERE is_active = true
        ORDER BY symbol
    """)
    
    tokens = cursor.fetchall()
    cursor.close()
    
    logger.info(f"Found {len(tokens)} tracked tokens in database")
    return tokens


def match_and_update_tokens(conn, lunarcrush_coins, tracked_tokens, dry_run=False):
    """
    Match LunarCrush coins with our tracked tokens and update database
    
    Args:
        conn: Database connection
        lunarcrush_coins (list): LunarCrush coins data
        tracked_tokens (list): Our tracked tokens from database
        dry_run (bool): If True, don't actually update database
    
    Returns:
        dict: Summary of matches and updates
    """
    # Create comprehensive address lookup for LunarCrush coins
    lunarcrush_by_address = {}
    
    for coin in lunarcrush_coins:
        # Index by all possible addresses for this coin
        for addr_info in coin.get('addresses', []):
            address = addr_info['address']
            address_type = addr_info['type']
            
            # Create case-insensitive lookup keys
            lookup_keys = [
                address.upper(),  # Uppercase
                address.lower(),  # Lowercase
                address,          # Original case
            ]
            
            # For native tokens, also add the symbol-based lookup
            if address_type in ['native_token', 'known_native_token', 'generic_native_token', 'special_case_token', 'symbol_fallback_token']:
                lookup_keys.extend([
                    coin['symbol'].upper(),
                    coin['symbol'].lower(),
                    f"native_{coin['symbol'].upper()}",
                    f"native_{coin['symbol'].lower()}"
                ])
                
                # Add network name as lookup key for special cases
                if 'network' in addr_info:
                    lookup_keys.extend([
                        addr_info['network'].upper(),
                        addr_info['network'].lower()
                    ])
            
            # Add all lookup keys to the index
            for key in lookup_keys:
                if key not in lunarcrush_by_address:
                    lunarcrush_by_address[key] = []
                lunarcrush_by_address[key].append({
                    'coin': coin,
                    'matched_address': address,
                    'address_type': address_type,
                    'match_method': f"address_{address_type}"
                })
    
    matches = []
    updates = []
    no_matches = []
    
    for token in tracked_tokens:
        token_address = token['address']
        token_symbol = token['symbol']
        
        match_found = False
        best_match = None
        
        # Try different matching strategies
        matching_strategies = [
            # 1. Exact address match (case-sensitive)
            token_address,
            # 2. Case-insensitive address matches
            token_address.upper(),
            token_address.lower(),
            # 3. Symbol-based matching for native tokens
            token_symbol.upper(),
            token_symbol.lower(),
            f"native_{token_symbol.upper()}",
            f"native_{token_symbol.lower()}",
        ]
        
        for strategy in matching_strategies:
            if strategy in lunarcrush_by_address:
                candidates = lunarcrush_by_address[strategy]
                
                # If multiple candidates, prefer exact symbol match
                best_candidate = None
                for candidate in candidates:
                    lc_coin = candidate['coin']
                    
                    # Prefer exact symbol matches
                    if lc_coin['symbol'].upper() == token_symbol.upper():
                        best_candidate = candidate
                        break
                    
                    # Fallback to first candidate if no exact symbol match
                    if best_candidate is None:
                        best_candidate = candidate
                
                if best_candidate:
                    best_match = best_candidate
                    match_found = True
                    break
        
        if match_found and best_match:
            lc_coin = best_match['coin']
            
            match_info = {
                'token_id': token['token_id'],
                'our_symbol': token['symbol'],
                'our_name': token['name'],
                'our_address': token['address'],
                'lc_symbol': lc_coin['symbol'],
                'lc_name': lc_coin['name'],
                'lc_id': lc_coin['lunarcrush_id'],
                'lc_topic': lc_coin['topic'],
                'matched_address': best_match['matched_address'],
                'address_type': best_match['address_type'],
                'match_method': best_match['match_method'],
                'market_cap_rank': lc_coin.get('market_cap_rank'),
                'galaxy_score': lc_coin.get('galaxy_score')
            }
            
            matches.append(match_info)
            
            # Check if update is needed
            if (token['lunarcrush_id'] != lc_coin['lunarcrush_id'] or 
                not token['social_data_available']):
                updates.append(match_info)
        else:
            no_matches.append({
                'token_id': token['token_id'],
                'symbol': token['symbol'],
                'name': token['name'],
                'address': token_address
            })
    
    logger.info(f"Address matching results:")
    logger.info(f"  - Total matches: {len(matches)}")
    logger.info(f"  - Need updates: {len(updates)}")
    logger.info(f"  - No LunarCrush match: {len(no_matches)}")
    
    # Print matches with match method info
    if matches:
        logger.info("\nSuccessful matches:")
        for match in matches:
            symbol_match = "✓" if match['our_symbol'].upper() == match['lc_symbol'].upper() else "⚠"
            match_method = match['match_method']
            addr_type = match['address_type']
            
            logger.info(f"  {symbol_match} {match['our_symbol']} -> LC:{match['lc_id']} ({match['lc_symbol']}) | "
                       f"Rank: {match['market_cap_rank']} | Method: {match_method} ({addr_type})")
    
    # Print no matches
    if no_matches:
        logger.warning("\nTokens without LunarCrush matches:")
        for token in no_matches:
            logger.warning(f"  ❌ {token['symbol']} ({token['address']})")
    
    # Perform updates
    if updates and not dry_run:
        cursor = conn.cursor()
        
        for update in updates:
            try:
                cursor.execute("""
                    UPDATE tokens SET 
                        lunarcrush_id = %s,
                        lunarcrush_symbol = %s,
                        lunarcrush_topic = %s,
                        last_social_update = NOW(),
                        social_data_available = true,
                        updated_at = NOW()
                    WHERE token_id = %s
                """, (
                    update['lc_id'],
                    update['lc_symbol'],
                    update['lc_topic'],
                    update['token_id']
                ))
                
                logger.info(f"Updated {update['our_symbol']} with LunarCrush ID: {update['lc_id']} "
                           f"(matched via {update['match_method']})")
                
            except Exception as e:
                logger.error(f"Error updating token {update['our_symbol']}: {e}")
        
        conn.commit()
        cursor.close()
        
        logger.info(f"Successfully updated {len(updates)} tokens with LunarCrush IDs")
    
    elif dry_run and updates:
        logger.info(f"\nDRY RUN: Would update {len(updates)} tokens:")
        for update in updates:
            logger.info(f"  - {update['our_symbol']} -> LunarCrush ID: {update['lc_id']} "
                       f"(via {update['match_method']})")
    
    return {
        'total_matches': len(matches),
        'updates_performed': len(updates) if not dry_run else 0,
        'updates_needed': len(updates),
        'no_matches': len(no_matches),
        'matches': matches,
        'no_matches': no_matches
    }


def main():
    parser = argparse.ArgumentParser(description='Map LunarCrush IDs to tracked tokens')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without making changes')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Load environment
        env_vars = load_environment()
        
        # Get LunarCrush API key
        api_key = env_vars.get('LUNARCRUSH_API_KEY')
        if not api_key:
            logger.error("LUNARCRUSH_API_KEY not found in environment variables")
            sys.exit(1)
        
        # Connect to database
        conn = get_database_connection(env_vars)
        
        # Fetch LunarCrush coins
        lunarcrush_coins = fetch_lunarcrush_coins(api_key)
        if not lunarcrush_coins:
            logger.error("No LunarCrush coins data available")
            sys.exit(1)
        
        # Get tracked tokens
        tracked_tokens = get_tracked_tokens(conn)
        if not tracked_tokens:
            logger.error("No tracked tokens found in database")
            sys.exit(1)
        
        # Match and update
        results = match_and_update_tokens(conn, lunarcrush_coins, tracked_tokens, args.dry_run)
        
        # Print summary
        logger.info("\n" + "="*60)
        logger.info("LUNARCRUSH MAPPING SUMMARY")
        logger.info("="*60)
        logger.info(f"Total tracked tokens: {len(tracked_tokens)}")
        logger.info(f"LunarCrush matches: {results['total_matches']}")
        logger.info(f"Updates needed: {results['updates_needed']}")
        logger.info(f"Updates performed: {results['updates_performed']}")
        logger.info(f"Tokens without LunarCrush data: {results['no_matches']}")
        
        if args.dry_run:
            logger.info("\n🔍 DRY RUN MODE - No changes were made to the database")
            logger.info("Run without --dry-run to apply changes")
        elif results['updates_performed'] > 0:
            logger.info(f"\n✅ Successfully updated {results['updates_performed']} tokens with LunarCrush IDs")
            logger.info("Social data fetching will now use LunarCrush IDs instead of symbols")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"Script failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 