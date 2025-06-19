#!/usr/bin/env python3
"""
BirdEye Transaction WebSocket Test Script

Tests transaction feeds for order book building and real-time market analysis.
Storage integration will be added after fixing import structure.
"""
import asyncio
import logging
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add the src directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.data.websocket_feed import (
    BirdEyeWebSocketFeed, 
    ConnectionConfig, 
    PriceUpdate, 
    PriceSubscription,
    TransactionUpdate,
    TransactionSubscription,
    ConnectionState
)
from src.data.realtime_storage import RealtimeDataStorage
from src.database.production_db import get_db_manager

# Load environment variables
load_dotenv('../.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OrderBookTester:
    """Test harness for BirdEye price and transaction feeds"""
    
    def __init__(self):
        self.price_updates_received = 0
        self.transaction_updates_received = 0
        self.connection_state_changes = 0
        self.errors_received = 0
        self.start_time = datetime.now()
        
        # Order book analysis counters
        self.buy_transactions = 0
        self.sell_transactions = 0
        self.total_volume_usd = 0.0
        self.unique_traders = set()
        self.platforms = set()
        
    def handle_price_update(self, price_update: PriceUpdate):
        """Handle price update events for order book reference"""
        self.price_updates_received += 1
        
        logger.info(f"📊 Price Update #{self.price_updates_received}")
        logger.info(f"   Token: {price_update.symbol} | Close: ${price_update.close_price}")
        logger.info(f"   OHLC: ${price_update.open_price}/${price_update.high_price}/${price_update.low_price}/${price_update.close_price}")
        logger.info(f"   Volume: {price_update.volume:,.2f}")
        
    def handle_transaction_update(self, tx_update: TransactionUpdate):
        """Handle transaction events for order book building"""
        self.transaction_updates_received += 1
        
        # Update order book stats
        if tx_update.side == "buy":
            self.buy_transactions += 1
        elif tx_update.side == "sell":
            self.sell_transactions += 1
            
        if tx_update.volume_usd:
            self.total_volume_usd += tx_update.volume_usd
            
        if tx_update.owner:
            self.unique_traders.add(tx_update.owner)
            
        if tx_update.platform:
            self.platforms.add(tx_update.platform)
        
        logger.info(f"🔄 Transaction #{self.transaction_updates_received}")
        logger.info(f"   📝 Hash: {tx_update.tx_hash[:16]}...")
        logger.info(f"   👤 Trader: {tx_update.owner[:8]}...")
        logger.info(f"   📈 Side: {tx_update.side or 'N/A'}")
        logger.info(f"   🏪 Platform: {tx_update.platform}")
        logger.info(f"   💰 Volume USD: ${tx_update.volume_usd:,.2f}" if tx_update.volume_usd else "   💰 Volume USD: N/A")
        logger.info(f"   💱 Price: ${tx_update.token_price}" if tx_update.token_price else "   💱 Price: N/A")
        
        # Show token swap details for order book
        if tx_update.from_symbol and tx_update.to_symbol:
            logger.info(f"   🔄 Swap: {tx_update.from_ui_amount:,.6f} {tx_update.from_symbol} → {tx_update.to_ui_amount:,.6f} {tx_update.to_symbol}")
        
        logger.info(f"   ⏰ Block Time: {tx_update.timestamp}")
        logger.info("   " + "="*60)
    
    def handle_connection_state(self, state: ConnectionState):
        """Handle connection state changes"""
        self.connection_state_changes += 1
        logger.info(f"🔗 Connection State: {state.value}")
    
    def handle_error(self, error: Exception):
        """Handle error events"""
        self.errors_received += 1
        logger.error(f"❌ Error: {error}")
    
    def print_order_book_stats(self, feed: BirdEyeWebSocketFeed):
        """Print order book analysis statistics"""
        runtime = (datetime.now() - self.start_time).total_seconds()
        feed_stats = feed.get_stats()
        
        logger.info("📊 ORDER BOOK ANALYSIS STATISTICS")
        logger.info("="*70)
        logger.info(f"📅 Runtime: {runtime:.1f} seconds")
        logger.info(f"📈 Price Updates: {self.price_updates_received}")
        logger.info(f"🔄 Transaction Updates: {self.transaction_updates_received}")
        logger.info("")
        logger.info("🛒 TRADING ACTIVITY:")
        logger.info(f"   📊 Buy Transactions: {self.buy_transactions}")
        logger.info(f"   📉 Sell Transactions: {self.sell_transactions}")
        logger.info(f"   💰 Total Volume USD: ${self.total_volume_usd:,.2f}")
        logger.info(f"   👥 Unique Traders: {len(self.unique_traders)}")
        logger.info("")
        logger.info("🏪 PLATFORMS OBSERVED:")
        for platform in sorted(self.platforms):
            logger.info(f"   • {platform}")
        logger.info("")
        logger.info("📡 WEBSOCKET STATS:")
        logger.info(f"   Messages Received: {feed_stats['messages_received']}")
        logger.info(f"   Messages Processed: {feed_stats['messages_processed']}")
        logger.info(f"   Active Subscriptions: {feed_stats['active_subscriptions']}")
        logger.info(f"   Connection Changes: {self.connection_state_changes}")
        logger.info(f"   Errors: {self.errors_received}")

async def test_transaction_feed():
    """Test transaction feed with integrated storage"""
    logger.info("🚀 Starting BirdEye Transaction WebSocket Test with Storage...")
    
    # Configuration
    config = ConnectionConfig(
        api_key=os.getenv('BIRDEYE_API_KEY'),
        chain='solana'
    )
    
    # Initialize components
    feed = BirdEyeWebSocketFeed(config)
    tester = OrderBookTester()
    db_manager = await get_db_manager()
    storage = RealtimeDataStorage(feed, db_manager)
    
    # Add event handlers
    feed.add_price_update_handler(tester.handle_price_update)
    feed.add_transaction_update_handler(tester.handle_transaction_update)
    feed.add_connection_handler(tester.handle_connection_state)
    feed.add_error_handler(tester.handle_error)
    
    try:
        # Initialize storage system
        await storage.initialize()
        logger.info("✅ Storage system initialized")
        
        # Start storage system
        await storage.start()
        logger.info("✅ Storage system started - transactions will be saved to database")
        
        # Token addresses
        SOL_ADDRESS = "So11111111111111111111111111111111111111112"
        BONK_ADDRESS = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        
        # Subscribe to price feeds
        await feed.subscribe_price(PriceSubscription(
            chart_type="1m",
            address=SOL_ADDRESS,
            currency="usd"
        ))
        logger.info("✅ Subscribed to SOL price feed")
        
        await feed.subscribe_price(PriceSubscription(
            chart_type="1m", 
            address=BONK_ADDRESS,
            currency="usd"
        ))
        logger.info("✅ Subscribed to BONK price feed")
        
        # Subscribe to transaction feeds
        await feed.subscribe_transactions(TransactionSubscription(
            address=BONK_ADDRESS
        ))
        logger.info("✅ Subscribed to BONK transaction feed")
        
        # Run for 2 minutes
        logger.info("📊 Collecting transaction data for 2 minutes...")
        await asyncio.sleep(120)
        
        # Print final statistics
        tester.print_order_book_stats(feed)
        storage_stats = storage.get_statistics()
        logger.info(f"📈 Storage Statistics:")
        logger.info(f"   💹 Ticks processed: {storage_stats['ticks_processed']}")
        logger.info(f"   🔄 Transactions processed: {storage_stats['transactions_processed']}")
        logger.info(f"   📊 Candles created: {storage_stats['candles_created']}")
        logger.info(f"   ⚡ Triggers fired: {storage_stats['triggers_fired']}")
        
    except KeyboardInterrupt:
        logger.info("🛑 Stopping WebSocket feed...")
    except Exception as e:
        logger.error(f"❌ Error in transaction feed test: {e}")
    finally:
        # Clean shutdown
        await storage.stop()
        await feed.stop()
        await db_manager.close()
        logger.info("✅ Test completed and resources cleaned up")

if __name__ == "__main__":
    # Run the test
    asyncio.run(test_transaction_feed()) 