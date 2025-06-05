"""
Database initialization script for Solana ML Trading Bot
"""
import os
import sys
import argparse
from src.database.utils import create_tables, add_token

def main():
    parser = argparse.ArgumentParser(description='Initialize the Solana ML Trading Bot database')
    parser.add_argument('--add-token', action='store_true', help='Add a token to the database')
    parser.add_argument('--address', type=str, help='Token address')
    parser.add_argument('--symbol', type=str, help='Token symbol')
    parser.add_argument('--name', type=str, help='Token name')
    parser.add_argument('--decimals', type=int, help='Token decimals')
    
    args = parser.parse_args()
    
    # Initialize database tables
    print("Initializing database tables...")
    engine = create_tables()
    print("Database initialization complete!")
    
    # Add token if requested
    if args.add_token:
        if not args.address or not args.symbol:
            print("Error: --address and --symbol are required when adding a token")
            return
        
        print(f"Adding token {args.symbol} ({args.address})...")
        token = add_token(
            address=args.address,
            symbol=args.symbol,
            name=args.name,
            decimals=args.decimals
        )
        
        if token:
            print(f"Token added successfully with ID {token.token_id}")
        else:
            print("Failed to add token")

if __name__ == "__main__":
    main() 