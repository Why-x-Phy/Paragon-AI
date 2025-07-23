#!/usr/bin/env python3
"""
Calvin Vault Token Liquidation Script

This script liquidates a specific token from the Calvin vault back to USDC.
Simply provide the token mint address and it will sell all tokens.

Usage:
    python test_vault_swap.py <token_mint_address> [--network mainnet]
    
Example:
    python test_vault_swap.py 2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv  # Sell all WIF

WARNING: This script will execute real transactions with real vault funds.
"""

import asyncio
import argparse
import logging
import sys
import json
from typing import Dict, Optional
from pathlib import Path
from datetime import datetime

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.vault.vault_client import VaultClient
from src.vault.jupiter_client import JupiterV6Client
from src.database.production_db import get_db_manager

# Constants
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def get_token_info(db_manager, token_mint: str) -> Dict[str, any]:
    """Get token info from database or return basic info"""
    try:
        if db_manager:
            # Try to get token info from database
            for token in db_manager._token_cache.values():
                if token.address == token_mint:
                    return {
                        'symbol': token.symbol,
                        'name': token.name,
                        'decimals': token.decimals
                    }
        
        # If not found, return default info
        return {
            'symbol': f'TOKEN_{token_mint[:6]}',
            'name': 'Unknown Token',
            'decimals': 6  # Most SPL tokens use 6 decimals
        }
    except Exception as e:
        logger.warning(f"Could not get token info: {e}")
        return {
            'symbol': f'TOKEN_{token_mint[:6]}',
            'name': 'Unknown Token',
            'decimals': 6
        }

async def execute_liquidation(vault_client, jupiter_client, token_mint: str, token_info: Dict):
    """Execute the liquidation of a token to USDC"""
    print(f"\n🔥 EXECUTING LIQUIDATION: {token_info['symbol']} → USDC")
    print("=" * 60)
    
    # Track execution time
    start_time = datetime.utcnow()
    
    try:
        # Get vault authority PDA
        from solders.pubkey import Pubkey
        vault_authority_pda = vault_client._get_vault_authority_pda()
        token_mint_pubkey = Pubkey.from_string(token_mint)
        
        # Get the vault's token account using proper ATA derivation
        from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
        
        # Calculate associated token address
        token_account_address, _ = Pubkey.find_program_address(
            [bytes(vault_authority_pda), bytes(TOKEN_PROGRAM_ID), bytes(token_mint_pubkey)],
            ASSOCIATED_TOKEN_PROGRAM_ID
        )
        
        # Get current token balance
        try:
            balance_response = await vault_client.client.get_token_account_balance(token_account_address)
            token_amount_lamports = int(balance_response.value.amount)
        except Exception as e:
            print(f"❌ Failed to get token balance: {e}")
            print(f"   Token account might not exist or have zero balance")
            return None
        
        # Calculate human-readable balance
        decimals = token_info['decimals']
        token_balance_human = token_amount_lamports / (10 ** decimals)
        
        print(f"📊 Token Balance:")
        print(f"  - Token: {token_info['symbol']} ({token_info['name']})")
        print(f"  - Mint: {token_mint}")
        print(f"  - Balance: {token_amount_lamports:,} lamports")
        print(f"  - Balance (human): {token_balance_human:.6f} {token_info['symbol']}")
        
        if token_amount_lamports == 0:
            print(f"❌ No {token_info['symbol']} tokens to liquidate")
            return None
        
        # Get Jupiter quote
        print(f"\n📈 Getting Jupiter quote...")
        vault_authority_pda_str = str(vault_authority_pda)
        
        quote_response = await jupiter_client.get_quote(
            input_mint=token_mint,
            output_mint=USDC_MINT,
            amount=token_amount_lamports,
            slippage_bps=50,  # 3% slippage
            payer_pubkey=vault_authority_pda_str
        )
        
        if not quote_response or 'error' in quote_response:
            logger.error(f"❌ Failed to get Jupiter quote: {quote_response}")
            return None
        
        # Parse quote details
        input_amount = int(quote_response.get('inAmount', 0))
        output_amount = int(quote_response.get('outAmount', 0))
        price_impact = float(quote_response.get('priceImpactPct', 0))
        
        output_usdc = output_amount / 1_000_000  # USDC has 6 decimals
        
        print(f"  ✅ Quote received:")
        print(f"    - Selling: {token_balance_human:.6f} {token_info['symbol']}")
        print(f"    - Expected USDC: ${output_usdc:,.2f}")
        print(f"    - Price impact: {price_impact:.4f}%")
        
        # Get swap instruction
        print(f"\n🔧 Building swap transaction...")
        
        swap_data = await jupiter_client.get_swap_transaction(
            quote_response=quote_response,
            payer_pubkey=vault_authority_pda_str,
            slippage_bps=50
        )
        
        if not swap_data:
            logger.error("❌ Failed to get swap instruction from Jupiter")
            return None
            
        print(f"  ✅ Swap instruction prepared")
        
        # Execute the swap through vault
        print(f"\n🚀 Executing swap through Calvin vault...")
        
        trade_result = await vault_client.execute_trade(
            jupiter_data=swap_data,
            source_mint=token_mint,
            destination_mint=USDC_MINT,
            amount_in=token_amount_lamports  # Pass the amount we're selling
        )
        
        if not trade_result:
            logger.error(f"❌ Vault trade execution failed")
            return None
        
        print(f"\n🎉 Liquidation executed successfully!")
        print(f"  - Transaction: {trade_result}")
        print(f"  - Sold: {token_balance_human:.6f} {token_info['symbol']}")
        print(f"  - Expected USDC: ${output_usdc:,.2f}")
        
        # Check and collect performance fees
        print(f"\n💰 Processing performance fees...")
        
        # Force NAV calculation using the dedicated script
        # It uses the same logic as the NAV service but forces an update
        print(f"  📊 Calculating fresh NAV...")
        
        import subprocess
        import os
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'force_nav_update.js')
        
        nav_process = subprocess.run(
            ['node', script_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if nav_process.returncode == 0:
            print(f"  ✅ NAV calculated successfully")
            
            # Now attempt to collect performance fees
            print(f"  💸 Attempting to collect performance fees...")
            fees_result = await vault_client.collect_performance_fees()
            
            if fees_result:
                print(f"  ✅ Performance fees collected: {fees_result}")
                
                # Get vault info to show what happened
                vault_account = await vault_client.get_vault_account()
                if vault_account:
                    nav = vault_account.get('cached_nav', 0) / 1_000_000
                    hwm = vault_account.get('high_water_mark_nav', 0) / 1_000_000
                    print(f"  📈 New NAV: ${nav:,.2f}")
                    print(f"  📏 New HWM: ${hwm:,.2f}")
            else:
                print(f"  ℹ️ No performance fees collected (NAV may be below HWM)")
        else:
            print(f"  ❌ Failed to calculate NAV")
            if nav_process.stderr:
                print(f"  Error: {nav_process.stderr}")
            if nav_process.stdout:
                print(f"  Output: {nav_process.stdout}")
        
        return {
            'transaction_signature': trade_result,
            'token_symbol': token_info['symbol'],
            'token_amount': token_balance_human,
            'usdc_amount': output_usdc,
            'price_impact': price_impact,
            'token_mint': token_mint,
            'execution_time_ms': int((datetime.utcnow() - start_time).total_seconds() * 1000)
        }
        
    except Exception as e:
        logger.error(f"❌ Liquidation failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return None

async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Liquidate Calvin Vault tokens to USDC',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_vault_swap.py EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm    # Liquidate WIF
  python test_vault_swap.py 7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr    # Liquidate POPCAT
  python test_vault_swap.py DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263   # Liquidate BONK
        """
    )
    parser.add_argument('token_mint', help='Token mint address to liquidate')
    parser.add_argument('--network', choices=['mainnet', 'devnet'], default='mainnet',
                       help='Network to use (default: mainnet)')
    parser.add_argument('--skip-confirm', action='store_true',
                       help='Skip confirmation prompt (use with caution!)')
    
    args = parser.parse_args()
    
    # Validate token mint address
    try:
        from solders.pubkey import Pubkey
        Pubkey.from_string(args.token_mint)
    except Exception:
        print(f"❌ Invalid token mint address: {args.token_mint}")
        sys.exit(1)
    
    print(f"🚀 Calvin Vault Token Liquidation Tool")
    print("=" * 60)
    print(f"🔥 WARNING: This will execute REAL transactions on {args.network}!")
    print(f"💰 Real tokens will be sold for USDC!")
    print()
    
    try:
        # Initialize components
        print("🔧 Initializing components...")
        
        # Initialize database manager (optional)
        db_manager = None
        try:
            db_manager = await get_db_manager()
            logger.info("✅ Database manager initialized")
        except Exception as e:
            logger.warning(f"⚠️ Database manager initialization failed: {e}")
            logger.info("   Continuing without database...")
        
        # Initialize vault client
        from solana.rpc.async_api import AsyncClient
        from solders.keypair import Keypair
        import os
        
        rpc_url = 'https://mainnet.helius-rpc.com/?api-key=acfda155-4d7f-4930-8ac4-ddd9eebfb70d'
        connection = AsyncClient(rpc_url)
        
        vault_program_id = os.getenv('CALVIN_VAULT_PROGRAM_ID')
        if not vault_program_id:
            logger.error("❌ CALVIN_VAULT_PROGRAM_ID not set")
            return False
        
        authority_private_key = os.getenv('CALVIN_AUTHORITY_PRIVATE_KEY')
        if not authority_private_key:
            logger.error("❌ CALVIN_AUTHORITY_PRIVATE_KEY not set")
            return False
            
        # Load authority keypair
        try:
            if authority_private_key.strip().startswith('['):
                import ast
                private_key_bytes = ast.literal_eval(authority_private_key)
                authority_keypair = Keypair.from_bytes(private_key_bytes)
            else:
                authority_keypair = Keypair.from_base58_string(authority_private_key)
            logger.info(f"✅ Using vault authority: {authority_keypair.pubkey()}")
        except Exception as e:
            try:
                if authority_private_key.strip().startswith('['):
                    authority_keypair = Keypair.from_base58_string(authority_private_key)
                else:
                    import ast
                    private_key_bytes = ast.literal_eval(authority_private_key)
                    authority_keypair = Keypair.from_bytes(private_key_bytes)
                logger.info(f"✅ Using vault authority: {authority_keypair.pubkey()}")
            except Exception as e2:
                logger.error(f"❌ Failed to load keypair: {e}, {e2}")
                return False
        
        # Initialize vault client
        vault_client = VaultClient(
            vault_program=vault_program_id,
            connection=connection,
            authority_keypair=authority_keypair
        )
        await vault_client.initialize()
        logger.info("✅ Vault client initialized")
        
        # Initialize Jupiter client
        jupiter_client = JupiterV6Client()
        await jupiter_client.initialize()
        logger.info("✅ Jupiter client initialized")
        
        # Get token info
        token_info = await get_token_info(db_manager, args.token_mint)
        
        # Show what we're about to do
        print(f"\n📋 Liquidation Summary:")
        print(f"  - Token: {token_info['symbol']} ({token_info['name']})")
        print(f"  - Mint: {args.token_mint}")
        print(f"  - Action: Sell ALL tokens for USDC")
        print(f"  - Network: {args.network}")
        print()
        
        # Confirm unless skipped
        if not args.skip_confirm:
            response = input("🔥 Continue with liquidation? (yes/no): ")
            if response.lower() != 'yes':
                print("   Cancelled.")
                return
        
        # Execute liquidation
        result = await execute_liquidation(vault_client, jupiter_client, args.token_mint, token_info)
        
        if result:
            # Record trade properly in database if available
            if db_manager:
                try:
                    # Get token ID from database
                    token_info_db = None
                    for token in db_manager._token_cache.values():
                        if token.address == result['token_mint']:
                            token_info_db = token
                            break
                    
                    if token_info_db:
                        # Calculate price from the liquidation
                        price_per_token = result['usdc_amount'] / result['token_amount'] if result['token_amount'] > 0 else 0
                        
                        # Create trade data matching the database schema
                        from src.database.production_db import TradeData
                        
                        trade_data = TradeData(
                            token_id=token_info_db.token_id,
                            trade_type='sell',  # This is a liquidation (sell)
                            price=price_per_token,
                            quantity=result['token_amount'],
                            value_usdc=result['usdc_amount'],
                            fee_usdc=0.0,  # Could calculate from price impact
                            tx_hash=result['transaction_signature'],
                            execution_time=datetime.utcnow(),
                            slippage_bps=50,  # We used 3% slippage
                            dex_name='jupiter',
                            processing_time_ms=result.get('execution_time_ms', 0),
                            
                            # Additional fields for vault trades
                            signal_confidence=100.0,  # Manual liquidation
                            model_version='manual_liquidation',
                            signal_strength='STRONG',  # Manual decisions are considered strong signals
                            predicted_change_pct=0.0,
                            cycle_timestamp=datetime.utcnow()
                        )
                        
                        # Record the trade
                        trade_id = await db_manager.record_trade(trade_data)
                        print(f"\n✅ Trade recorded in database with ID: {trade_id}")
                        
                        # Also record health check for monitoring
                        await db_manager.record_health_check(
                            component='vault_liquidation',
                            status='healthy',
                            details={
                                'trade_id': trade_id,
                                'token_mint': result['token_mint'],
                                'token_symbol': result['token_symbol'],
                                'token_amount': result['token_amount'],
                                'usdc_amount': result['usdc_amount'],
                                'price_impact': result['price_impact'],
                                'transaction_signature': result['transaction_signature'],
                                'timestamp': datetime.utcnow().isoformat()
                            }
                        )
                    else:
                        logger.warning(f"⚠️ Token not found in database cache, recording health check only")
                        await db_manager.record_health_check(
                            component='vault_liquidation',
                            status='healthy',
                            details={
                                'token_mint': result['token_mint'],
                                'token_symbol': result['token_symbol'],
                                'token_amount': result['token_amount'],
                                'usdc_amount': result['usdc_amount'],
                                'price_impact': result['price_impact'],
                                'transaction_signature': result['transaction_signature'],
                                'timestamp': datetime.utcnow().isoformat()
                            }
                        )
                        
                except Exception as e:
                    logger.warning(f"⚠️ Failed to record in database: {e}")
                    import traceback
                    traceback.print_exc()
            
            print(f"\n🎉 LIQUIDATION SUCCESSFUL!")
            print(f"   - Sold: {result['token_amount']:.6f} {result['token_symbol']}")
            print(f"   - Received: ${result['usdc_amount']:,.2f} USDC")
            print(f"   - Transaction: {result['transaction_signature']}")
            sys.exit(0)
        else:
            print(f"\n❌ Liquidation failed!")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 
