#!/usr/bin/env python3
"""
Calvin AI - Find Pyth Oracle Accounts for Tracked Tokens

This script helps you find the correct Pyth oracle accounts for your tracked tokens
by querying the Pyth price feed directory and mapping token addresses to oracle accounts.
"""

import os
import sys
import asyncio
import aiohttp
import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not installed. Install with: pip install python-dotenv")
    print("Attempting to load .env file manually...")
    
    # Manual .env loading as fallback
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
        print(f"Loaded environment variables from {env_file}")
    else:
        print(f"No .env file found at {env_file}")

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class TokenInfo:
    """Token information from database/BirdEye"""
    address: str
    symbol: str
    name: str
    
@dataclass
class PythOracleInfo:
    """Pyth oracle account information"""
    price_account: str
    product_account: str
    symbol: str
    description: str
    asset_type: str
    base: str
    quote_currency: str

class PythOracleFinder:
    """Find Pyth oracle accounts for tracked tokens"""
    
    def __init__(self):
        # Pyth API endpoints
        self.pyth_api_base = "https://hermes.pyth.network"
        self.solana_price_feeds_url = f"{self.pyth_api_base}/v2/price_feeds"
        
        logger.info("Pyth Oracle Finder initialized")

    async def get_tracked_tokens(self) -> List[str]:
        """Get tracked token addresses from environment"""
        tracked_tokens_str = os.getenv('TRACKED_TOKENS', '')
        if not tracked_tokens_str:
            # Try to read directly from .env file as a fallback
            env_file = Path(__file__).parent.parent / ".env"
            if env_file.exists():
                with open(env_file, 'r') as f:
                    for line in f:
                        if line.strip().startswith('TRACKED_TOKENS='):
                            tracked_tokens_str = line.split('=', 1)[1].strip()
                            break
        
        if not tracked_tokens_str:
            logger.error("TRACKED_TOKENS environment variable not set")
            logger.info("Please ensure TRACKED_TOKENS is set in your .env file")
            return []
        
        tokens = [addr.strip() for addr in tracked_tokens_str.split(',') if addr.strip()]
        logger.info(f"Found {len(tokens)} tracked tokens")
        return tokens

    async def fetch_token_metadata(self, token_address: str) -> Optional[TokenInfo]:
        """Fetch token metadata from BirdEye API"""
        try:
            api_key = os.getenv('BIRDEYE_API_KEY')
            if not api_key:
                logger.warning("BIRDEYE_API_KEY not set, using address as symbol")
                return TokenInfo(address=token_address, symbol=token_address[:8], name="Unknown")
            
            # Use the correct v3 endpoint
            url = f"https://public-api.birdeye.so/defi/v3/token/meta-data/single"
            headers = {"X-API-KEY": api_key}
            params = {"address": token_address}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('success') and data.get('data'):
                            token_data = data['data']
                            return TokenInfo(
                                address=token_address,
                                symbol=token_data.get('symbol', token_address[:8]),
                                name=token_data.get('name', 'Unknown')
                            )
                    else:
                        logger.warning(f"BirdEye API error for {token_address}: {response.status}")
        
        except Exception as e:
            logger.warning(f"Failed to fetch metadata for {token_address}: {e}")
        
        # Fallback: use address as symbol
        return TokenInfo(address=token_address, symbol=token_address[:8], name="Unknown")

    async def fetch_pyth_price_feeds(self) -> List[Dict]:
        """Fetch all available Pyth price feeds"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.solana_price_feeds_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Handle the case where the response is directly a list
                        if isinstance(data, list):
                            return data
                        # Handle the case where it's wrapped in an object
                        elif isinstance(data, dict):
                            return data.get('price_feeds', data.get('data', []))
                        else:
                            logger.error(f"Unexpected Pyth API response format: {type(data)}")
                            return []
                    else:
                        logger.error(f"Failed to fetch Pyth price feeds: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching Pyth price feeds: {e}")
            return []

    def find_oracle_for_symbol(self, symbol: str, pyth_feeds: List[Dict]) -> Optional[PythOracleInfo]:
        """Find Pyth oracle for a specific token symbol"""
        
        # Search through Pyth feeds
        symbol_upper = symbol.upper()
        possible_matches = []
        
        for feed in pyth_feeds:
            feed_symbol = feed.get('attributes', {}).get('symbol', '').upper()
            base_symbol = feed.get('attributes', {}).get('base', '').upper()
            
            # Direct symbol match
            if feed_symbol == f"{symbol_upper}/USD" or feed_symbol == f"{symbol_upper}USD":
                possible_matches.append((feed, 100))  # Perfect match
            elif base_symbol == symbol_upper:
                possible_matches.append((feed, 90))   # Base symbol match
            elif symbol_upper in feed_symbol:
                possible_matches.append((feed, 50))   # Partial match
        
        if possible_matches:
            # Sort by match score and return best match
            possible_matches.sort(key=lambda x: x[1], reverse=True)
            best_feed = possible_matches[0][0]
            
            # Debug: Print the feed structure for the first few matches
            if len([f for f in pyth_feeds if f == best_feed]) <= 3:
                logger.info(f"DEBUG: Best feed structure for {symbol}: {json.dumps(best_feed, indent=2)}")
            
            # Extract Solana price account ID - try multiple possible structures
            price_account_id = None
            
            # Method 1: Check if 'id' is directly a string (price account)
            if isinstance(best_feed.get('id'), str):
                price_account_id = best_feed['id']
            
            # Method 2: Check if 'id' is a list with objects containing Solana accounts
            elif isinstance(best_feed.get('id'), list):
                for feed_id in best_feed['id']:
                    if isinstance(feed_id, dict):
                        # Try different possible field names
                        if feed_id.get('type') == 'solana' and feed_id.get('id'):
                            price_account_id = feed_id['id']
                            break
                        elif 'solana' in str(feed_id).lower():
                            # Look for any field that might contain the Solana account
                            for key, value in feed_id.items():
                                if isinstance(value, str) and len(value) > 40:  # Solana addresses are ~44 chars
                                    price_account_id = value
                                    break
                            if price_account_id:
                                break
            
            # Method 3: Look for other common field names
            if not price_account_id:
                for key in ['price_account', 'solana_price_account', 'account', 'address']:
                    if key in best_feed and isinstance(best_feed[key], str):
                        price_account_id = best_feed[key]
                        break
            
            # Method 4: Look in nested structures
            if not price_account_id and 'price' in best_feed:
                price_data = best_feed['price']
                if isinstance(price_data, dict):
                    for key in ['account', 'id', 'address', 'solana']:
                        if key in price_data and isinstance(price_data[key], str):
                            price_account_id = price_data[key]
                            break
            
            if not price_account_id:
                logger.warning(f"No Solana price account found for {symbol}")
                logger.debug(f"Available keys in feed: {list(best_feed.keys())}")
                return None
            
            attributes = best_feed.get('attributes', {})
            logger.info(f"✅ Found oracle for {symbol}: {price_account_id}")
            
            return PythOracleInfo(
                price_account=price_account_id,
                product_account="",  # Not needed
                symbol=symbol.upper(),
                description=attributes.get('description', f"{symbol}/USD"),
                asset_type=attributes.get('asset_type', 'Crypto'),
                base=attributes.get('base', symbol.upper()),
                quote_currency=attributes.get('quote_currency', 'USD')
            )
        
        return None

    async def find_all_oracles(self) -> Dict[str, Optional[PythOracleInfo]]:
        """Find Pyth oracles for all tracked tokens"""
        
        # Get tracked tokens
        token_addresses = await self.get_tracked_tokens()
        if not token_addresses:
            return {}
        
        # Fetch token metadata
        logger.info("Fetching token metadata...")
        tokens = []
        for address in token_addresses:
            token_info = await self.fetch_token_metadata(address)
            if token_info:
                tokens.append(token_info)
        
        # Fetch Pyth price feeds
        logger.info("Fetching Pyth price feeds...")
        pyth_feeds = await self.fetch_pyth_price_feeds()
        logger.info(f"Found {len(pyth_feeds)} Pyth price feeds")
        
        # Find oracles for each token
        results = {}
        for token in tokens:
            logger.info(f"Finding oracle for {token.symbol} ({token.address})")
            oracle = self.find_oracle_for_symbol(token.symbol, pyth_feeds)
            results[token.address] = oracle
            
            if oracle:
                logger.info(f"✅ Found oracle for {token.symbol}: {oracle.price_account}")
            else:
                logger.warning(f"❌ No oracle found for {token.symbol}")
        
        return results

    def generate_rust_config(self, oracles: Dict[str, Optional[PythOracleInfo]]) -> str:
        """Generate Rust configuration for smart contract"""
        
        config_lines = [
            "// Pyth Oracle Accounts Configuration for Calvin Vault",
            "// Generated automatically - do not edit manually",
            "",
            "use anchor_lang::prelude::*;",
            "",
            "pub struct OracleConfig;",
            "",
            "impl OracleConfig {",
            "    /// Oracle accounts for supported tokens (devnet)",
            "    pub const ORACLE_ACCOUNTS: &'static [(Pubkey, &'static str)] = &[",
        ]
        
        # Add oracle accounts
        oracle_count = 0
        for token_address, oracle in oracles.items():
            if oracle:
                config_lines.append(f'        (pubkey!("{oracle.price_account}"), "{oracle.symbol}"), // {oracle.description}')
                oracle_count += 1
        
        config_lines.extend([
            "    ];",
            "",
            f"    /// Total number of supported oracles: {oracle_count}",
            f"    pub const ORACLE_COUNT: usize = {oracle_count};",
            "",
            "    /// Get oracle account for symbol",
            "    pub fn get_oracle_account(symbol: &str) -> Option<Pubkey> {",
            "        Self::ORACLE_ACCOUNTS",
            "            .iter()",
            "            .find(|(_, s)| *s == symbol)",
            "            .map(|(pubkey, _)| *pubkey)",
            "    }",
            "}",
        ])
        
        return "\n".join(config_lines)

    def generate_env_config(self, oracles: Dict[str, Optional[PythOracleInfo]]) -> str:
        """Generate environment variable configuration"""
        
        config_lines = [
            "# Pyth Oracle Configuration for Calvin AI",
            "# Add these to your .env file",
            "",
        ]
        
        # Generate oracle account list
        oracle_accounts = []
        oracle_symbols = []
        
        for token_address, oracle in oracles.items():
            if oracle:
                oracle_accounts.append(oracle.price_account)
                oracle_symbols.append(oracle.symbol)
        
        config_lines.extend([
            f"# Pyth Oracle Accounts (devnet) - {len(oracle_accounts)} oracles found",
            f'PYTH_ORACLE_ACCOUNTS={",".join(oracle_accounts)}',
            "",
            f"# Corresponding symbols",
            f'PYTH_ORACLE_SYMBOLS={",".join(oracle_symbols)}',
            "",
        ])
        
        return "\n".join(config_lines)

    async def export_results(self, oracles: Dict[str, Optional[PythOracleInfo]]):
        """Export results to files"""
        
        # Create output directory
        output_dir = Path("oracle_config")
        output_dir.mkdir(exist_ok=True)
        
        # Generate and save Rust config
        rust_config = self.generate_rust_config(oracles)
        rust_file = output_dir / "oracle_config.rs"
        with open(rust_file, 'w') as f:
            f.write(rust_config)
        logger.info(f"Rust configuration saved to: {rust_file}")
        
        # Generate and save environment config
        env_config = self.generate_env_config(oracles)
        env_file = output_dir / "oracle.env"
        with open(env_file, 'w') as f:
            f.write(env_config)
        logger.info(f"Environment configuration saved to: {env_file}")
        
        # Generate detailed JSON report
        json_report = {
            "generation_time": str(asyncio.get_event_loop().time()),
            "total_tokens": len(oracles),
            "oracles_found": len([o for o in oracles.values() if o]),
            "oracles_missing": len([o for o in oracles.values() if not o]),
            "oracles": {}
        }
        
        for token_address, oracle in oracles.items():
            if oracle:
                json_report["oracles"][token_address] = {
                    "price_account": oracle.price_account,
                    "symbol": oracle.symbol,
                    "description": oracle.description,
                    "asset_type": oracle.asset_type,
                    "base": oracle.base,
                    "quote_currency": oracle.quote_currency
                }
            else:
                json_report["oracles"][token_address] = None
        
        json_file = output_dir / "oracle_report.json"
        with open(json_file, 'w') as f:
            json.dump(json_report, f, indent=2)
        logger.info(f"Detailed report saved to: {json_file}")

async def main():
    """Main execution function"""
    
    print("🔍 Calvin AI - Pyth Oracle Account Finder")
    print("=" * 50)
    
    try:
        finder = PythOracleFinder()
        
        # Find all oracles
        oracles = await finder.find_all_oracles()
        
        if not oracles:
            print("❌ No tokens found to process")
            return
        
        # Print summary
        found_count = len([o for o in oracles.values() if o])
        total_count = len(oracles)
        
        print(f"\n📊 Summary:")
        print(f"   Total tokens: {total_count}")
        print(f"   Oracles found: {found_count}")
        print(f"   Missing oracles: {total_count - found_count}")
        
        # Print details
        print(f"\n📋 Oracle Details:")
        for token_address, oracle in oracles.items():
            if oracle:
                print(f"   ✅ {oracle.symbol:8} | {oracle.price_account} | {oracle.description}")
            else:
                print(f"   ❌ {token_address[:8]:8} | No oracle found")
        
        # Export results
        await finder.export_results(oracles)
        
        print(f"\n🎉 Oracle discovery complete!")
        print(f"   Check ./oracle_config/ directory for generated files")
        print(f"   Next steps:")
        print(f"   1. Add oracle_config.rs to your vault program")
        print(f"   2. Add oracle.env variables to your .env file")
        print(f"   3. Update vault state to include oracle accounts")
        
    except Exception as e:
        logger.error(f"Oracle discovery failed: {e}")
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 