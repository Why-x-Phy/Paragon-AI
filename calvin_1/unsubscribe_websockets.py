#!/usr/bin/env python3
"""
Unsubscribe from BirdEye WebSocket feeds

This script connects to BirdEye WebSocket and sends unsubscribe messages
to clean up any lingering subscriptions.
"""

import asyncio
import aiohttp
import json
import os
import sys
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config.config import config


async def unsubscribe_all():
    """Connect to BirdEye WebSocket and unsubscribe from all feeds"""
    
    # Get all API keys
    api_keys = []
    for i in range(1, 8):
        key_name = 'BIRDEYE_API_KEY' if i == 1 else f'BIRDEYE_API_KEY_{i}'
        api_key = config.get(key_name)
        if api_key:
            api_keys.append((key_name, api_key))
    
    if not api_keys:
        print("❌ No BIRDEYE_API_KEY found in environment")
        return
    
    print(f"🔑 Found {len(api_keys)} API keys to unsubscribe")
    
    # WebSocket URL (includes chain specification)
    ws_url = "wss://public-api.birdeye.so/socket/solana"
    
    # Unsubscribe with each API key
    for key_name, api_key in api_keys:
        print(f"\n{'='*60}")
        print(f"🔑 Unsubscribing with {key_name}: {api_key[:8]}...{api_key[-4:]}")
        
        # Headers with API key
        headers = {
            "X-Api-Key": api_key,
            "User-Agent": "Calvin-AI/1.0",
            "Origin": "ws://public-api.birdeye.so",
            "Sec-WebSocket-Origin": "ws://public-api.birdeye.so"
        }
        
        # Include API key in URL as per documentation
        ws_url_with_key = f"{ws_url}?x-api-key={api_key}"
        
        try:
            # Create session
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Connect to WebSocket
                async with session.ws_connect(
                    ws_url_with_key,
                    headers=headers,
                    protocols=['echo-protocol']
                ) as ws:
                    print(f"✅ Connected to BirdEye WebSocket with {key_name}")
                    
                    # Send unsubscribe messages for both price and transaction feeds
                    unsubscribe_messages = [
                        {
                            "type": "UNSUBSCRIBE_PRICE",
                            "data": {}
                        },
                        {
                            "type": "UNSUBSCRIBE_TXS", 
                            "data": {}
                        }
                    ]
                    
                    for msg in unsubscribe_messages:
                        print(f"📤 Sending: {msg['type']}")
                        await ws.send_str(json.dumps(msg))
                        
                        # Wait for response
                        try:
                            response = await asyncio.wait_for(ws.receive(), timeout=5.0)
                            if response.type == aiohttp.WSMsgType.TEXT:
                                print(f"📥 Response: {response.data}")
                            else:
                                print(f"📥 Response type: {response.type}")
                        except asyncio.TimeoutError:
                            print("⏱️ No response received (timeout)")
                    
                    # Send a close message
                    print("🔌 Closing connection...")
                    await ws.close()
                    print(f"✅ WebSocket connection closed for {key_name}")
                    
        except Exception as e:
            print(f"❌ Error with {key_name}: {e}")
            
        # Small delay between API keys
        await asyncio.sleep(1)


async def check_active_connections():
    """Check for any active WebSocket connections"""
    print("\n📊 Checking for active connections...")
    
    # Get all API keys
    api_keys = []
    for i in range(1, 8):
        key_name = 'BIRDEYE_API_KEY' if i == 1 else f'BIRDEYE_API_KEY_{i}'
        api_key = config.get(key_name)
        if api_key:
            api_keys.append((key_name, api_key))
    
    print(f"Found {len(api_keys)} API keys to check")
    
    # For each API key, try to connect and check status
    for key_name, api_key in api_keys:
        print(f"\n🔑 Checking {key_name}: {api_key[:8]}...{api_key[-4:]}")
        
        try:
            # Try to connect with this API key
            ws_url = "wss://public-api.birdeye.so/socket/solana"
            headers = {
                "X-Api-Key": api_key,
                "User-Agent": "Calvin-AI/1.0",
                "Origin": "ws://public-api.birdeye.so",
                "Sec-WebSocket-Origin": "ws://public-api.birdeye.so"
            }
            
            # Include API key in URL as per documentation
            ws_url_with_key = f"{ws_url}?x-api-key={api_key}"
            
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(
                    ws_url_with_key,
                    headers=headers,
                    protocols=['echo-protocol']
                ) as ws:
                    print(f"   ✅ Connected successfully")
                    
                    # Try to receive any pending messages
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            print(f"   📥 Pending message: {msg.data[:100]}...")
                    except asyncio.TimeoutError:
                        print(f"   ✓ No pending messages")
                    
                    await ws.close()
                    
        except Exception as e:
            print(f"   ❌ Connection failed: {e}")


async def main():
    """Main function"""
    print("🧹 BirdEye WebSocket Cleanup Tool")
    print("=" * 50)
    
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        # Just check connections
        await check_active_connections()
    else:
        # Unsubscribe from all feeds
        await unsubscribe_all()
        
        # Check remaining connections
        await check_active_connections()
    
    print("\n✅ Done!")


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main()) 