#!/usr/bin/env python3
"""
Calvin AI Token Initialization Script
Fetches token metadata from BirdEye API and populates the database
"""

import os
import sys
import json
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv('../.env')

def get_env_var(name, required=True):
    """Get environment variable with optional requirement check"""
    value = os.getenv(name)
    if required and not value:
        print(f"❌ Environment variable {name} not set")
        return None
    return value

def fetch_token_metadata(api_key, token_addresses):
    """Fetch token metadata from BirdEye API"""
    url = "https://public-api.birdeye.so/defi/v3/token/meta-data/multiple"
    params = {"list_address": token_addresses}
    headers = {"X-API-KEY": api_key}
    
    print(f"📡 Fetching metadata for {len(token_addresses.split(','))} tokens...")
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"❌ API request failed: {e}")
        return None

def connect_to_database():
    """Connect to the Calvin AI database"""
    db_config = {
        'host': get_env_var('DB_HOST', False) or 'localhost',
        'port': get_env_var('DB_PORT', False) or '6432',
        'database': get_env_var('DB_NAME', False) or 'calvin_trading_dev',
        'user': get_env_var('DB_USER', False) or 'calvin_dev',
        'password': get_env_var('DB_PASSWORD_DEV', False) or get_env_var('DB_PASSWORD', False)
    }
    
    try:
        conn = psycopg2.connect(**db_config)
        conn.autocommit = True
        print(f"✅ Connected to database: {db_config['database']}")
        return conn
    except psycopg2.Error as e:
        print(f"❌ Database connection failed: {e}")
        return None

def insert_token(cursor, address, token_data):
    """Insert or update a single token in the database"""
    try:
        # Extract token fields with proper string trimming
        symbol = (token_data.get('symbol', 'UNKNOWN') or 'UNKNOWN').strip()
        name = (token_data.get('name', 'Unknown Token') or 'Unknown Token').strip()
        decimals = token_data.get('decimals', 9)
        
        # Extract extensions (metadata) with proper string trimming
        extensions = token_data.get('extensions') or {}
        coingecko_id = (extensions.get('coingecko_id') or '').strip() or None
        website = (extensions.get('website') or '').strip() or None
        twitter = (extensions.get('twitter') or '').strip() or None
        discord = (extensions.get('discord') or '').strip() or None
        telegram = (extensions.get('telegram') or '').strip() or None
        description = (extensions.get('description') or '').strip() or None
        
        logo_uri = (token_data.get('logo_uri') or '').strip() or None
        
        # SQL INSERT with ON CONFLICT UPDATE
        sql = """
        INSERT INTO tokens (
            address, symbol, name, decimals, 
            coingecko_id, website, twitter, discord, telegram, description, logo_uri,
            metadata_verified, trading_enabled, last_api_update
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s,
            true, true, NOW()
        ) ON CONFLICT (address) DO UPDATE SET
            symbol = EXCLUDED.symbol,
            name = EXCLUDED.name,
            decimals = EXCLUDED.decimals,
            coingecko_id = EXCLUDED.coingecko_id,
            website = EXCLUDED.website,
            twitter = EXCLUDED.twitter,
            discord = EXCLUDED.discord,
            telegram = EXCLUDED.telegram,
            description = EXCLUDED.description,
            logo_uri = EXCLUDED.logo_uri,
            metadata_verified = true,
            trading_enabled = true,
            last_api_update = NOW(),
            updated_at = NOW()
        """
        
        cursor.execute(sql, (
            address, symbol, name, decimals,
            coingecko_id, website, twitter, discord, telegram, description, logo_uri
        ))
        
        print(f"✅ Updated token: {symbol} ({address[:8]}...)")
        return True
        
    except Exception as e:
        print(f"❌ Failed to update token {address}: {e}")
        return False

def main():
    """Main function"""
    print("🪙 Calvin AI Token Initialization")
    print("="*50)
    
    # Get environment variables
    api_key = get_env_var('BIRDEYE_API_KEY')
    token_addresses = get_env_var('TRACKED_TOKENS')
    
    if not api_key or not token_addresses:
        print("❌ Missing required environment variables")
        print("   Ensure BIRDEYE_API_KEY and TRACKED_TOKENS are set")
        return 1
    
    # Fetch token metadata
    response_data = fetch_token_metadata(api_key, token_addresses)
    if not response_data:
        return 1
    
    # Check response structure
    if 'data' not in response_data:
        print(f"❌ Unexpected API response structure: {response_data}")
        return 1
    
    token_data = response_data['data']
    print(f"📊 Received metadata for {len(token_data)} tokens")
    
    # Connect to database
    conn = connect_to_database()
    if not conn:
        return 1
    
    # Process each token
    success_count = 0
    total_count = len(token_data)
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            for address, data in token_data.items():
                if insert_token(cursor, address, data):
                    success_count += 1
    finally:
        conn.close()
    
    # Summary
    print()
    print(f"📈 Token initialization complete!")
    print(f"   ✅ Successfully updated: {success_count}/{total_count}")
    print(f"   ❌ Failed: {total_count - success_count}")
    
    # Show token status
    if success_count > 0:
        print("\n📊 Checking token status...")
        conn = connect_to_database()
        if conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SELECT symbol, address, trading_enabled, metadata_verified FROM token_status ORDER BY symbol;")
                    tokens = cursor.fetchall()
                    for token in tokens:
                        status = "🟢" if token['trading_enabled'] else "🟡"
                        print(f"   {status} {token['symbol']}: {token['address'][:8]}...")
            finally:
                conn.close()
    
    return 0 if success_count == total_count else 1

if __name__ == "__main__":
    sys.exit(main()) 