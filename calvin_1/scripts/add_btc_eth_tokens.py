#!/usr/bin/env python3
"""
Add BTC and ETH wrapped tokens to the database for intermarket correlation features
"""

import os
import sys
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables
# Try multiple possible locations for .env file
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))

# Try different .env locations
env_paths = [
    os.path.join(project_root, '.env'),  # /mnt/d/calvin_ai/.env
    os.path.join(os.path.dirname(project_root), '.env'),  # One level up
    os.path.join(current_dir, '..', '..', '.env'),  # Relative path
    '.env'  # Current directory
]

# Load the first .env file found
env_loaded = False
for env_path in env_paths:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"✅ Loaded environment from: {env_path}")
        env_loaded = True
        break

if not env_loaded:
    print("⚠️ No .env file found, trying system environment variables")

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
    
    print(f"📡 Fetching metadata for BTC and ETH tokens...")
    
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
        'port': get_env_var('DB_PORT', False) or '5432',
        'database': get_env_var('DB_NAME', False) or 'calvin_db',
        'user': get_env_var('DB_USER', False) or 'calvin',
        'password': get_env_var('DB_PASSWORD')
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
        # Extract token fields
        symbol = (token_data.get('symbol', 'UNKNOWN') or 'UNKNOWN').strip()
        name = (token_data.get('name', 'Unknown Token') or 'Unknown Token').strip()
        decimals = token_data.get('decimals', 9)
        
        # For BTC/ETH correlation features, we don't need social data
        # But we'll add coingecko_id for potential future use
        extensions = token_data.get('extensions') or {}
        coingecko_id = symbol.lower() if symbol in ['BTC', 'ETH'] else None
        
        # SQL INSERT with ON CONFLICT UPDATE
        sql = """
        INSERT INTO tokens (
            address, symbol, name, decimals, coingecko_id, lunarcrush_id
        ) VALUES (
            %s, %s, %s, %s, %s, NULL
        ) ON CONFLICT (address) DO UPDATE SET
            symbol = EXCLUDED.symbol,
            name = EXCLUDED.name,
            decimals = EXCLUDED.decimals,
            coingecko_id = EXCLUDED.coingecko_id,
            updated_at = NOW()
        RETURNING token_id
        """
        
        cursor.execute(sql, (address, symbol, name, decimals, coingecko_id))
        result = cursor.fetchone()
        token_id = result['token_id'] if result else None
        
        print(f"✅ Updated token: {symbol} (ID: {token_id}, Address: {address[:8]}...)")
        return token_id
        
    except Exception as e:
        print(f"❌ Failed to update token {address}: {e}")
        return None

def main():
    """Main function"""
    print("🪙 Adding BTC and ETH tokens for intermarket correlation")
    print("="*50)
    
    # BTC and ETH wrapped token addresses on Solana
    btc_eth_addresses = [
        "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh",  # Wrapped BTC (Wormhole)
        "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs"   # Wrapped ETH (Wormhole)
    ]
    
    # Get API key
    api_key = get_env_var('BIRDEYE_API_KEY')
    if not api_key:
        print("❌ Missing BIRDEYE_API_KEY environment variable")
        return 1
    
    # Fetch token metadata
    response_data = fetch_token_metadata(api_key, ",".join(btc_eth_addresses))
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
    
    # Process each token and track IDs
    token_ids = {}
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            for address, data in token_data.items():
                token_id = insert_token(cursor, address, data)
                if token_id:
                    symbol = data.get('symbol', 'UNKNOWN')
                    token_ids[symbol] = token_id
    finally:
        conn.close()
    
    # Summary
    print()
    print(f"📈 Token initialization complete!")
    print()
    print("🔧 Update your data_processor.py with these token IDs:")
    print("="*50)
    
    if 'BTC' in token_ids:
        print(f"btc_token_id = {token_ids['BTC']}  # Wrapped BTC")
    if 'ETH' in token_ids:
        print(f"eth_token_id = {token_ids['ETH']}  # Wrapped ETH")
    
    print()
    print("📝 Replace the placeholder values in add_intermarket_correlation_features()")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())