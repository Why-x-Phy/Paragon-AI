#!/usr/bin/env python3
"""
CoinAPI WebSocket Feed Test Script

Tests the CoinAPI WebSocket price feed with real market data
and verifies connectivity and data flow.
"""
import asyncio
import logging
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add the src directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from data.websocket_feed import CoinAPIWebSocketFeed, ConnectionConfig, PriceUpdate, ConnectionState, SubscriptionConfig, SubscriptionType

# Load environment variables
load_dotenv('../.env.dev')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CoinAPITester:
    """Test harness for CoinAPI WebSocket price feed"""
    
    def __init__(self):
        self.price_updates_received = 0
        self.trade_updates = 0
        self.ohlcv_updates = 0
        self.quote_updates = 0
        self.connection_state_changes = 0
        self.errors_received = 0
        self.start_time = datetime.now()
        
    def handle_price_update(self, price_update: PriceUpdate):
        """Handle price update events"""
        self.price_updates_received += 1
        
        # Count by data type
        if price_update.data_type == 'trade':
            self.trade_updates += 1
        elif price_update.data_type == 'ohlcv':
            self.ohlcv_updates += 1
        elif price_update.data_type == 'quote':
            self.quote_updates += 1
        
        logger.info(f"📊 OHLCV Update #{self.price_updates_received}")
        logger.info(f"   Symbol: {price_update.symbol_id}")
        
        if price_update.data_type == 'ohlcv':
            logger.info(f"   Period: {price_update.period_id}")
            logger.info(f"   📈 OHLC: O=${price_update.price_open:.6f} H=${price_update.price_high:.6f} L=${price_update.price_low:.6f} C=${price_update.price_close:.6f}")
            logger.info(f"   📊 Volume: {price_update.volume_traded:,.2f}")
            logger.info(f"   🔢 Trades: {price_update.trades_count}")
            logger.info(f"   ⏰ Period: {price_update.time_period_start} to {price_update.time_period_end}")
        else:
            # Handle non-OHLCV data (shouldn't happen with our subscription but just in case)
            logger.info(f"   Type: {price_update.data_type}")
            if hasattr(price_update, 'price') and price_update.price:
                logger.info(f"   Price: ${price_update.price:.6f}")
        
        logger.info(f"   CoinAPI Time: {price_update.time_coinapi}")
        logger.info("   " + "="*50)
    
    def handle_connection_state(self, state: ConnectionState):
        """Handle connection state changes"""
        self.connection_state_changes += 1
        logger.info(f"🔗 Connection State: {state.value}")
    
    def handle_error(self, error: Exception):
        """Handle error events"""
        self.errors_received += 1
        logger.error(f"❌ Error: {error}")
    
    def print_stats(self, feed: CoinAPIWebSocketFeed):
        """Print test statistics"""
        runtime = (datetime.now() - self.start_time).total_seconds()
        feed_stats = feed.get_stats()
        
        logger.info("📈 Test Statistics:")
        logger.info(f"   Runtime: {runtime:.1f} seconds")
        logger.info(f"   Total Updates: {self.price_updates_received}")
        logger.info(f"     Trades: {self.trade_updates}")
        logger.info(f"     OHLCV: {self.ohlcv_updates}")
        logger.info(f"     Quotes: {self.quote_updates}")
        logger.info(f"   Connection Changes: {self.connection_state_changes}")
        logger.info(f"   Errors: {self.errors_received}")
        logger.info(f"   Feed Messages Received: {feed_stats['messages_received']}")
        logger.info(f"   Feed Messages Processed: {feed_stats['messages_processed']}")

async def test_coinapi_websocket():
    """Main test function"""
    logger.info("🚀 Starting CoinAPI WebSocket Feed Test")
    logger.info("="*60)
    
    # Get API key from environment
    api_key = os.getenv('COINAPI_KEY')
    if not api_key or api_key == 'your_coinapi_key_here':
        logger.error("❌ COINAPI_KEY not found or not set in environment")
        logger.info("   Please set your CoinAPI key in .env.dev file")
        return
    
    logger.info(f"🔑 Using CoinAPI Key: {api_key[:8]}...")
    
    # Create configuration
    config = ConnectionConfig(
        api_key=api_key,
        reconnect_delay=2.0,
        max_reconnect_delay=30.0,
        max_reconnect_attempts=5,
        heartbeat_interval=30.0,
        connection_timeout=10.0
    )
    
    # Create test harness
    tester = CoinAPITester()
    
    # Create WebSocket feed
    feed = CoinAPIWebSocketFeed(config)
    
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
        
        # Create subscription configuration
        # Use specific symbols where BTC is priced in USD/USDT (not BTC pricing other assets)
        subscription = SubscriptionConfig(
            data_types=[SubscriptionType.OHLCV],  # OHLCV data specifically
            symbol_ids=[
                "COINBASE_SPOT_BTC_USD"   # BTC priced in USD
            ],
            period_ids=["1MIN"],  # Back to 1-minute for realistic risk management
            heartbeat=True
        )
        
        logger.info("📡 Subscribing to BTC/USD and BTC/USDT 1-minute OHLCV for risk management...")
        logger.info("   (Only getting BTC price, not BTC pricing other assets)")
        success = await feed.subscribe(subscription)
        
        if success:
            logger.info("✅ Subscription configured successfully")
        else:
            logger.error("❌ Failed to configure subscription")
            return
        
        # Run for 2 minutes to allow 1-minute OHLCV candles to complete
        logger.info("⏰ Running test for 2 minutes (waiting for 1-minute OHLCV completion)...")
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
    asyncio.run(test_coinapi_websocket()) 