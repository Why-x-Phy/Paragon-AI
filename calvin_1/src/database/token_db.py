#!/usr/bin/env python
"""
Token Database Module

Provides functions to store and retrieve token-related information
from the database.
"""

import os
import sqlite3
from typing import Dict, Optional, List, Tuple
import logging

from ..utils.logger import log_manager

# Set up logger
logger = log_manager.get_logger("token_db")

# Get database path from environment or use default
DB_PATH = os.environ.get('CALVIN_DB_PATH', 'calvin.db')

def get_db_connection():
    """
    Create a connection to the SQLite database
    
    Returns:
        SQLite connection object
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_token_table():
    """
    Initialize the tokens table if it doesn't exist
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create tokens table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tokens (
        id INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        address TEXT NOT NULL UNIQUE,
        name TEXT,
        decimals INTEGER DEFAULT 9,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        category TEXT,
        has_website BOOLEAN DEFAULT 0,
        is_verified BOOLEAN DEFAULT 0
    )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Token table initialized")

def add_token(symbol: str, address: str, name: str = None, 
              decimals: int = 9, category: str = None, 
              has_website: bool = False, is_verified: bool = False) -> bool:
    """
    Add a token to the database
    
    Args:
        symbol: Token symbol
        address: Token contract address
        name: Token name (optional)
        decimals: Token decimal places (default 9)
        category: Token category (optional)
        has_website: Whether the token has a website (default False)
        is_verified: Whether the token is verified (default False)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if token already exists
        cursor.execute("SELECT id FROM tokens WHERE address = ?", (address,))
        existing = cursor.fetchone()
        
        if existing:
            # Update existing token
            cursor.execute('''
            UPDATE tokens 
            SET symbol = ?, name = ?, decimals = ?, 
                category = ?, has_website = ?, is_verified = ?
            WHERE address = ?
            ''', (symbol, name, decimals, category, 
                  has_website, is_verified, address))
        else:
            # Insert new token
            cursor.execute('''
            INSERT INTO tokens (symbol, address, name, decimals, category, has_website, is_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (symbol, address, name, decimals, category, has_website, is_verified))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error adding token {symbol}: {e}")
        return False

def get_token_address(symbol: str) -> Optional[str]:
    """
    Get token address by symbol
    
    Args:
        symbol: Token symbol to look up
        
    Returns:
        Token address or None if not found
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Find matching token by symbol (case insensitive)
        cursor.execute("SELECT address FROM tokens WHERE LOWER(symbol) = LOWER(?)", (symbol,))
        result = cursor.fetchone()
        
        conn.close()
        
        if result:
            return result['address']
        return None
    except Exception as e:
        logger.error(f"Error fetching address for token {symbol}: {e}")
        return None

def get_token_info(address: str) -> Optional[Dict]:
    """
    Get all token information by address
    
    Args:
        address: Token contract address
        
    Returns:
        Dictionary with token information or None if not found
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
        SELECT symbol, address, name, decimals, category, 
               has_website, is_verified, created_at
        FROM tokens 
        WHERE address = ?
        """, (address,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return dict(result)
        return None
    except Exception as e:
        logger.error(f"Error fetching token info for {address}: {e}")
        return None

def get_all_tokens() -> List[Dict]:
    """
    Get all tokens in the database
    
    Returns:
        List of dictionaries with token information
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
        SELECT symbol, address, name, decimals, category, 
               has_website, is_verified, created_at
        FROM tokens
        ORDER BY symbol
        """)
        
        results = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in results]
    except Exception as e:
        logger.error(f"Error fetching all tokens: {e}")
        return []

def import_known_tokens():
    """
    Import well-known tokens to the database
    """
    tokens = [
        ("BTC", "9n4nbM75f5Ui33ZbPYXn59EwSgE8CGsHtAeTH5YFeJ9E", "Bitcoin (Wrapped)", 6, "crypto", True, True),
        ("ETH", "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs", "Ethereum (Wrapped)", 8, "crypto", True, True),
        ("SOL", "So11111111111111111111111111111111111111112", "Solana", 9, "crypto", True, True),
        ("USDC", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "USD Coin", 6, "stable", True, True),
        ("USDT", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "Tether USD", 6, "stable", True, True),
        ("BONK", "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "Bonk", 5, "meme", True, True),
        ("FART", "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump", "Fartcoin", 9, "meme", False, False),
        ("WIF", "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "WIF", 6, "meme", True, True),
        ("BOME", "Fj4n2nx3VKZ2G4MUny9v1eLPhEP5HsRQvfW6dWFaSVLF", "Bambi Meme Coin", 9, "meme", True, False),
        ("STRK", "StrikeNs4TZMYDSZvqQvXFwjR3lbQzEaQmC5C1Tf13WB", "Strike", 9, "gaming", True, True),
        ("JUP", "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvFK", "Jupiter", 6, "defi", True, True),
        ("PYTH", "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", "Pyth Network", 6, "defi", True, True),
    ]
    
    success_count = 0
    for token in tokens:
        symbol, address, name, decimals, category, has_website, is_verified = token
        if add_token(symbol, address, name, decimals, category, has_website, is_verified):
            success_count += 1
    
    logger.info(f"Imported {success_count}/{len(tokens)} known tokens")
    
# Initialize the table when the module is imported
init_token_table()

# Try to import known tokens if the table is empty
try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM tokens")
    result = cursor.fetchone()
    conn.close()
    
    if result and result['count'] == 0:
        import_known_tokens()
except:
    # Database may not be ready yet, will try again later
    pass 