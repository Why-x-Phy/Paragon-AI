#!/usr/bin/env python3
"""
Test Pyth Oracle Price Parsing

This script tests our Pyth oracle price parsing implementation by:
1. Using REAL Solana price feed account addresses from Pyth Network
2. Testing Switchboard fallbacks when Pyth fails
3. Fetching and parsing real price data
4. Comparing both oracle sources

Usage: python test_pyth_parsing.py
"""

import asyncio
import sys
import os
sys.path.insert(0, 'src')

from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from src.vault.vault_client import VaultClient
from src.utils.logger import log
import logging

logger = log
# Set debug level to see detailed parsing info
logging.getLogger().setLevel(logging.DEBUG)

async def test_pyth_and_switchboard_parsing():
    """Test both Pyth and Switchboard oracle price parsing with real data"""
    try:
        print("🧪 Testing Pyth & Switchboard Oracle Price Parsing")
        print("=" * 60)
        
        # Initialize Solana client
        rpc_url = "https://api.mainnet-beta.solana.com"
        client = AsyncClient(rpc_url)
        
        # Create a minimal vault client just for the parsing function
        vault_client = VaultClient(
            vault_program="tXMJu1KaBQU5DSk94QXMtigQpzxbK62WJVUs2Xmxz7z",
            connection=client,
            authority_keypair=None
        )
        
        # REAL Solana Pyth Price Feed Addresses (from Pyth Network official list)
        # These are the actual on-chain accounts, not derived from hex IDs
        PYTH_SOLANA_FEEDS = {
            "USDC": "Dpw1EAVrSB1ibxiDQyTAW6Zip3J4Btk2x4SgApQCeFbX",  # USDC/USD
            "SOL": "H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG",   # SOL/USD
            "JUP": "g6eRCbboSwK4tSWngn773RCMexr1APQr4uA9bGZBYfo",    # JUP/USD
            "BONK": "8ihFLu5FimgTQ1Unh4dVyEHUGodJ5gJQCrQf4KUVB9bN",  # BONK/USD
            "WIF": "6B23K3tkb51vLZA14jcEQVCA1pfHptzEHFA93V5dYwbT",   # WIF/USD - CORRECTED
            "PYTH": "nrYkQQQur7z8rYTST3G9GqATviK5SxTDkrqd21MW6Ue",  # PYTH/USD
            "RAY": "AnLf8tVYCM816gmBjiy8n53eXKKEDydT5piYjjQDPgTB",    # RAY/USD
            "ORCA": "4ivThkX8uRxBpHsdWSqyXYihzKF3zpRGAUCqyuagnLoV", # ORCA/USD
            # User-provided correct addresses:
            "ATH": "5DTjTmrKZqUWcmfwfW2pRtFBK94HGeNR6i67Y5jLkdRg",    # ATH/USD
            "TRUMP": "9vNb2tQoZ8bB4vzMbQLWViGwNaDJVtct13AGgno1wazp",  # TRUMP/USD
            "RENDER": "HAm5DZhrgrWa12heKSxocQRyJWGCtXegC77hFQ8F5QTH", # RENDER/USD
            "FARTCOIN": "2t8eUbYKjidMs3uSeYM9jXM9uudYZwGkSeTB4TKjmvnC", # FARTCOIN/USD
            "JTO": "7ajR2zA4MGMMTqRAVjghTKqPPn4kbrj3pYkAVRVwTGzP",    # JTO/USD
            "VIRTUAL": "AgDofjBKQuJRzTSPxfjUyERiZuptR874wHxCHB6Pg4vF", # VIRTUAL/USD
            "PENGU": "27zzC5wXCeZeuJ3h9uAJzV5tGn6r5Tzo98S1ZceYKEb8",  # PENGU/USD
            "W": "BEMsCSQEGi2kwPA4mKnGjxnreijhMki7L4eeb96ypzF9",      # W/USD (Wormhole)
            "POPCAT": "6UxPR2nXJNNM1nESVWGAf8NXMVu3SGgYf3ZfUFoGB9cs", # POPCAT/USD
            "MEW": "EF6U755BdHMXim8RBw6XSC6Yk6XaouTKpwcBZ7QkcanB",   # MEW/USD
            "MNDE": "GHKcxocPyzSjy7tWApQjKRkDNuVXd4Kk624zhuaR7xhC",  # MNDE/USD
            "SPX": "7YmBpFooNruexenhJLU1wwUWUCzgETLQGVF1jLjqqaWq",   # SPX6900/USD
        }
        
        # Switchboard feed addresses (as backup/fallback)
        SWITCHBOARD_FEEDS = {
            "TRUMP": "9wcBMATS8bGLQ2UcRuYjsRAD7TPqB1CMhqfueBx78Uj2",
            "WIF": "8GqzQoqqKzJoNaWZtf2udVGV3Fn74W9DQayYu1S1zvkt",
            "ATH": "21JapEAFu8r8SAAQjB2fURfjiosnTHAFFm4S27qe4vVF",
            "BONK": "7GCiue6chgGuk6BvaurQNWD1Ervho8zEdcNWt5ZCYQhu",
            "FARTCOIN": "EE8Uyquv38j2JmyCiPprCNUxDBTrzpCXqR4hL3RGDUGh",
            "JTO": "E9fHVUZnvT4i8H3jQLb6g2tSpcagunJpjwCGNTYxwKSE",
            "JUP": "2F9M59yYc28WMrAymNWceaBEk8ZmDAjUAKULp8seAJF3",
            "MEW": "7Eev1vbsrgEmiRbVjyyFL8nqRKQt7jNPVtxiS4C6ewns",
            "PENGU": "DAG9yMr4FbTVd41Jojw6X589EHiPgR375SP5AdAAW7tH",
            "POPCAT": "5FWVcePyDK5jF6ZqFgmEMyu9qu5qdsswwvMd7GvRmfFW",
            "PYTH": "72ukr6M31f9cCzxvZT4Ba7AGyWSFLQGHjXU6WUzN4xD7",
            "RAY": "AJkAFiXdbMonys8rTXZBrRnuUiLcDFdkyoPuvrVKXhex",
            "RENDER": "B6xHth4K3fj3KK1TASXtHfbAReShYW3EihgwSKvhsugz",
            "SPX": "8m5YKLgnftRTcVXJLk7bV37xc2qrWR9TkXq4TY3FP3pz",
            "VIRTUAL": "34aJFwk2jTKmB2C6zWnT641ABCQv1P2ghrob57i1gFdg",
            "W": "DwjV47HwtHW5YR1CPndw3Fq1QMeYyvYA7jYXhMtcUCte",
            "SOL": "E8TLLh5jkYDvSXfAES7qe3s8Cfjj4hyvjksuvUHe8NEw",
            "USDC": "aHTvxuDvCRRnmJDDR1JkfLa4SpCNsgC4vDeLMEcN3zY",
            "ORCA": "BFWHemmj4ZtvqQVsWrGrFrL2U8tz7Lzq8nhy1KRMVezL",
            "W": "DwjV47HwtHW5YR1CPndw3Fq1QMeYyvYA7jYXhMtcUCte",
            "MEW": "7Eev1vbsrgEmiRbVjyyFL8nqRKQt7jNPVtxiS4C6ewns",
            "MNDE": "CwtLbG7w71oCasCMYR8KARZYEVJK5x1GXdoYpqjctp7E",
            "SPX": "8m5YKLgnftRTcVXJLk7bV37xc2qrWR9TkXq4TY3FP3pz"
        }
        
        results = []
        
        # Test each token with both Pyth and Switchboard
        for symbol in PYTH_SOLANA_FEEDS.keys():
            print(f"\n🔍 Testing {symbol}/USD...")
            
            pyth_result = None
            switchboard_result = None
            
            # Test Pyth Price Feed
            pyth_address = PYTH_SOLANA_FEEDS[symbol]
            print(f"   📊 Pyth Feed: {pyth_address}")
            
            try:
                pyth_pubkey = Pubkey.from_string(pyth_address)
                pyth_account = await client.get_account_info(pyth_pubkey)
                
                if pyth_account and pyth_account.value:
                    print(f"   ✅ Pyth account data: {len(pyth_account.value.data)} bytes")
                    
                    # Parse price using our implementation
                    pyth_price = vault_client._parse_pyth_price_data(pyth_account.value.data)
                    
                    if pyth_price and pyth_price > 0:
                        print(f"   💰 Pyth price: ${pyth_price:.8f}")
                        pyth_result = pyth_price
                    else:
                        print(f"   ❌ Pyth: Invalid price data")
                else:
                    print(f"   ❌ Pyth: No account data")
                    
            except Exception as e:
                print(f"   ❌ Pyth error: {e}")
            
            # Test Switchboard Fallback (if available)
            if symbol in SWITCHBOARD_FEEDS:
                switchboard_address = SWITCHBOARD_FEEDS[symbol]
                print(f"   📈 Switchboard Feed: {switchboard_address}")
                
                try:
                    sb_pubkey = Pubkey.from_string(switchboard_address)
                    sb_account = await client.get_account_info(sb_pubkey)
                    
                    if sb_account and sb_account.value:
                        print(f"   ✅ Switchboard account data: {len(sb_account.value.data)} bytes")
                        
                        # Parse Switchboard price (simpler JSON-like format)
                        try:
                            sb_price = vault_client._parse_switchboard_price_data(sb_account.value.data)
                            if sb_price and sb_price > 0:
                                print(f"   💰 Switchboard price: ${sb_price:.8f}")
                                switchboard_result = sb_price
                            else:
                                print(f"   ❌ Switchboard: Invalid price data")
                                switchboard_result = "Available"
                        except Exception as parse_error:
                            print(f"   🔄 Switchboard parsing failed: {parse_error}")
                            switchboard_result = "Available"
                    else:
                        print(f"   ❌ Switchboard: No account data")
                        
                except Exception as e:
                    print(f"   ❌ Switchboard error: {e}")
            else:
                print(f"   ℹ️ No Switchboard feed configured for {symbol}")
            
            # Compile results
            status = "FAILED"
            if pyth_result:
                status = "PYTH_SUCCESS"
            elif switchboard_result:
                status = "SWITCHBOARD_AVAILABLE"
            
            results.append({
                "symbol": symbol,
                "status": status,
                "pyth_price": pyth_result,
                "switchboard_available": switchboard_result is not None,
                "pyth_address": pyth_address,
                "switchboard_address": SWITCHBOARD_FEEDS.get(symbol, "N/A")
            })
        
        # Print comprehensive summary
        print("\n" + "=" * 60)
        print("📋 ORACLE TESTING SUMMARY")
        print("=" * 60)
        
        pyth_successes = sum(1 for r in results if r['pyth_price'] is not None)
        switchboard_available = sum(1 for r in results if r['switchboard_available'])
        total_tokens = len(results)
        
        print(f"\n📊 Overall Results:")
        print(f"   • Total tokens tested: {total_tokens}")
        print(f"   • Pyth successful: {pyth_successes}/{total_tokens}")
        print(f"   • Switchboard available: {switchboard_available}/{total_tokens}")
        
        print(f"\n📈 Per-Token Results:")
        for result in results:
            status_emoji = {
                'PYTH_SUCCESS': '✅',
                'SWITCHBOARD_AVAILABLE': '🔄',
                'FAILED': '❌'
            }.get(result['status'], '❓')
            
            price_str = f"${result['pyth_price']:.8f}" if result['pyth_price'] else "No price"
            sb_str = "SB Available" if result['switchboard_available'] else "No SB"
            
            print(f"   {status_emoji} {result['symbol']}: {price_str} ({sb_str})")
        
        print(f"\n🎯 Key Findings:")
        if pyth_successes > 0:
            print(f"   ✅ Pyth oracle parsing is working!")
            print(f"   ✅ Using REAL Solana price feed addresses")
        else:
            print(f"   ❌ No Pyth prices parsed successfully")
            print(f"   💡 Check if _parse_pyth_price_data() function is working")
        
        if switchboard_available > 0:
            print(f"   🔄 Switchboard fallbacks are available for {switchboard_available} tokens")
            print(f"   💡 Need to implement Switchboard parsing for complete fallback system")
        
        print(f"\n🔧 Next Steps:")
        print(f"   1. Fix any Pyth parsing issues found above")
        print(f"   2. Implement Switchboard price parsing for fallbacks")
        print(f"   3. Update smart contract to use these REAL account addresses")
        print(f"   4. Test with the NAV calculation in the vault")
        
        await client.close()
        
        return pyth_successes > 0
        
    except Exception as e:
        print(f"💥 Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_pyth_and_switchboard_parsing())
    sys.exit(0 if success else 1) 