"""
Check Pyth SSE Client Status
"""

import asyncio
import json
from datetime import datetime
from src.pyth.pyth_sse_client import PythSSEClient, ConnectionState

async def check_pyth_status():
    """Check the status of Pyth SSE client"""
    
    # Create a test client
    client = PythSSEClient()
    await client.initialize()
    
    print("\n" + "="*60)
    print("PYTH SSE CLIENT STATUS CHECK")
    print("="*60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Loaded token mappings: {len(client.token_info_cache)}")
    
    # Test with a few symbols
    test_symbols = ["SOL", "JUP", "$WIF"]
    client.subscribe_to_symbols(test_symbols)
    
    print(f"\nSubscribed to: {list(client.subscribed_tokens.keys())}")
    print(f"Connection state: {client.connection_state.value}")
    
    # Start the client
    print("\nStarting SSE client...")
    await client.start()
    
    # Wait a bit for connection
    await asyncio.sleep(2)
    
    # Check status
    stats = client.get_stats()
    print(f"\nConnection state: {client.connection_state.value}")
    print(f"Stats: {json.dumps(stats, indent=2)}")
    
    # Wait for some price updates
    print("\nWaiting for price updates (10 seconds)...")
    await asyncio.sleep(10)
    
    # Final stats
    final_stats = client.get_stats()
    print(f"\nFinal stats after 10 seconds:")
    print(f"  Price updates: {final_stats['price_updates_processed']}")
    print(f"  Reconnects: {final_stats['reconnects']}")
    print(f"  Errors: {final_stats['errors']}")
    
    await client.stop()
    print("\nTest complete!")

if __name__ == "__main__":
    asyncio.run(check_pyth_status()) 