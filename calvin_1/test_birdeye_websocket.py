#!/usr/bin/env python3
"""
BirdEye WebSocket Feed Test Script

Tests the BirdEye WebSocket price feed with real Solana market data
for risk management and real-time price updates.
"""
import asyncio
import logging
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add the src directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from data.websocket_feed import BirdEyeWebSocketFeed, ConnectionConfig, PriceUpdate, PriceSubscription, ConnectionState

# Load environment variables
load_dotenv('../.env.dev')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BirdEyeTester:
    """Test harness for BirdEye WebSocket price feed"""
    
    def __init__(self):
        self.price_updates_received = 0
        self.connection_state_changes = 0
        self.errors_received = 0
        self.start_time = datetime.now()
        
    def handle_price_update(self, price_update: PriceUpdate):
        """Handle price update events"""
        self.price_updates_received += 1
        
        logger.info(f"📊 Price Update #{self.price_updates_received}")
        logger.info(f"   Token: {price_update.symbol} ({price_update.address[:8]}...)")
        logger.info(f"   📈 OHLC: O=${price_update.open_price} H=${price_update.high_price} L=${price_update.low_price} C=${price_update.close_price}")
        logger.info(f"   📊 Volume: {price_update.volume:,.2f}")
        logger.info(f"   📅 Chart Type: {price_update.chart_type}")
        logger.info(f"   🔢 Event Type: {price_update.event_type}")
        logger.info(f"   ⏰ Unix Time: {price_update.unix_time}")
        logger.info(f"   🕐 Timestamp: {price_update.timestamp}")
        logger.info("   " + "="*50)
    
    def handle_connection_state(self, state: ConnectionState):
        """Handle connection state changes"""
        self.connection_state_changes += 1
        logger.info(f"🔗 Connection State: {state.value}")
    
    def handle_error(self, error: Exception):
        """Handle error events"""
        self.errors_received += 1
        logger.error(f"❌ Error: {error}")
    
    def print_stats(self, feed: BirdEyeWebSocketFeed):
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
        logger.info(f"   Active Subscriptions: {feed_stats['active_subscriptions']}")

async def test_birdeye_websocket():
    """Main test function for BirdEye WebSocket"""
    logger.info("🚀 Starting BirdEye WebSocket Feed Test")
    logger.info("="*60)
    
    # Get API key from environment
    api_key = os.getenv('BIRDEYE_API_KEY_1')
    if not api_key:
        logger.error("❌ BIRDEYE_API_KEY_1 not found in environment")
        logger.info("   Please check your .env.dev file")
        return
    
    logger.info(f"🔑 Using BirdEye Key: {api_key[:8]}...")
    
    # Create configuration
    config = ConnectionConfig(
        api_key=api_key,
        chain="solana",
        reconnect_delay=2.0,
        max_reconnect_delay=30.0,
        max_reconnect_attempts=5,
        heartbeat_interval=30.0,
        connection_timeout=10.0
    )
    
    # Create test harness
    tester = BirdEyeTester()
    
    # Create WebSocket feed
    feed = BirdEyeWebSocketFeed(config)
    
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
        
        # Test 1: Subscribe to SOL price in USD
        logger.info("📡 Test 1: Subscribing to SOL/USD 1-minute OHLCV...")
        sol_subscription = PriceSubscription(
            query_type="simple",
            chart_type="1m",
            address="So11111111111111111111111111111111111111112",  # SOL token address
            currency="usd"
        )
        
        success = await feed.subscribe_price(sol_subscription)
        if success:
            logger.info("✅ SOL subscription successful")
        else:
            logger.error("❌ SOL subscription failed")
            return
        
        # Wait a bit, then add BONK
        await asyncio.sleep(5)
        
        # Test 2: Subscribe to BONK price in USD
        logger.info("📡 Test 2: Adding BONK/USD 1-minute OHLCV...")
        bonk_subscription = PriceSubscription(
            query_type="simple", 
            chart_type="1m",
            address="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",  # BONK token address
            currency="usd"
        )
        
        success = await feed.subscribe_price(bonk_subscription)
        if success:
            logger.info("✅ BONK subscription successful")
        else:
            logger.error("❌ BONK subscription failed")
        
        # Run for 2 minutes to see real-time updates
        logger.info("⏰ Running test for 2 minutes to collect real-time price updates...")
        await asyncio.sleep(120)
        
        # Print final stats
        tester.print_stats(feed)
        
    except KeyboardInterrupt:
        logger.info("⏹️  Test interrupted by user")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean shutdown
        logger.info("🛑 Stopping WebSocket feed...")
        await feed.stop()
        logger.info("✅ Test completed")

if __name__ == "__main__":
    # Run the test
    asyncio.run(test_birdeye_websocket()) 