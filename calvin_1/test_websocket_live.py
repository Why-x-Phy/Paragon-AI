#!/usr/bin/env python3
"""
Live WebSocket Feed Test Script

Tests the WebSocket price feed with real BirdEye data
and verifies database connectivity.
"""
import asyncio
import logging
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add the src directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from data.websocket_feed import WebSocketPriceFeed, ConnectionConfig, PriceUpdate, ConnectionState

# Load environment variables
load_dotenv('../.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test tokens (SOL and USDC from your tracked tokens)
TEST_TOKENS = {
    'SOL': 'So11111111111111111111111111111111111111112',
    'USDC': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
}

class WebSocketTester:
    """Test harness for WebSocket price feed"""
    
    def __init__(self):
        self.price_updates_received = 0
        self.connection_state_changes = 0
        self.errors_received = 0
        self.start_time = datetime.now()
        
    def handle_price_update(self, price_update: PriceUpdate):
        """Handle price update events"""
        self.price_updates_received += 1
        
        logger.info(f"📊 Price Update #{self.price_updates_received}")
        logger.info(f"   Token: {price_update.symbol} ({price_update.token_address[:8]}...)")
        logger.info(f"   OHLCV Data:")
        logger.info(f"     Open:   ${price_update.open_price:.6f}")
        logger.info(f"     High:   ${price_update.high_price:.6f}")
        logger.info(f"     Low:    ${price_update.low_price:.6f}")
        logger.info(f"     Close:  ${price_update.close_price:.6f}")
        logger.info(f"     Volume: {price_update.volume:,.2f}")
        logger.info(f"   Chart Type: {price_update.chart_type}")
        logger.info(f"   Time: {price_update.timestamp} (Unix: {price_update.unix_time})")
        
        logger.info("   " + "="*50)
    
    def handle_connection_state(self, state: ConnectionState):
        """Handle connection state changes"""
        self.connection_state_changes += 1
        logger.info(f"🔗 Connection State: {state.value}")
    
    def handle_error(self, error: Exception):
        """Handle error events"""
        self.errors_received += 1
        logger.error(f"❌ Error: {error}")
    
    def print_stats(self, feed: WebSocketPriceFeed):
        """Print test statistics"""
        runtime = (datetime.now() - self.start_time).total_seconds()
        feed_stats = feed.get_stats()
        
        logger.info("📈 Test Statistics:")
        logger.info(f"   Runtime: {runtime:.1f} seconds")
        logger.info(f"   Price Updates: {self.price_updates_received}")
        logger.info(f"   Connection Changes: {self.connection_state_changes}")
        logger.info(f"   Errors: {self.errors_received}")
        logger.info(f"   Feed Messages Received: {feed_stats['messages_received']}")
        logger.info(f"   Feed Messages Processed: {feed_stats['messages_processed']}")
        logger.info(f"   Active Subscriptions: {len(feed.get_subscribed_tokens())}")

async def test_websocket_feed():
    """Main test function"""
    logger.info("🚀 Starting WebSocket Feed Test")
    logger.info("="*60)
    
    # Get API key from environment
    api_key = os.getenv('BIRDEYE_API_KEY_1')
    if not api_key:
        logger.error("❌ BIRDEYE_API_KEY_1 not found in environment")
        return
    
    logger.info(f"🔑 Using API Key: {api_key[:8]}...")
    
    # Create configuration
    config = ConnectionConfig(
        api_key=api_key,
        chain="solana",
        max_tokens_per_connection=50,
        reconnect_delay=2.0,
        max_reconnect_delay=30.0,
        max_reconnect_attempts=5,
        heartbeat_interval=30.0,
        connection_timeout=10.0
    )
    
    # Create test harness
    tester = WebSocketTester()
    
    # Create WebSocket feed
    feed = WebSocketPriceFeed(config)
    
    # Add event handlers
    feed.add_price_update_handler(tester.handle_price_update)
    feed.add_connection_handler(tester.handle_connection_state)
    feed.add_error_handler(tester.handle_error)
    
    try:
        # Start the feed
        logger.info("🔌 Starting WebSocket connection...")
        await feed.start()
        
        # Wait for connection
        await asyncio.sleep(2)
        
        # Subscribe to test tokens
        logger.info("📡 Subscribing to tokens...")
        for token_name, token_address in TEST_TOKENS.items():
            success = await feed.subscribe_to_token(token_address, "1m")
            if success:
                logger.info(f"✅ Subscribed to {token_name} ({token_address[:8]}...)")
            else:
                logger.error(f"❌ Failed to subscribe to {token_name}")
        
        # Run for 30 seconds
        logger.info("⏰ Running test for 30 seconds...")
        await asyncio.sleep(30)
        
        # Print final stats
        tester.print_stats(feed)
        
    except KeyboardInterrupt:
        logger.info("⏹️  Test interrupted by user")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
    finally:
        # Clean shutdown
        logger.info("🛑 Stopping WebSocket feed...")
        await feed.stop()
        logger.info("✅ Test completed")

if __name__ == "__main__":
    # Run the test
    asyncio.run(test_websocket_feed()) 