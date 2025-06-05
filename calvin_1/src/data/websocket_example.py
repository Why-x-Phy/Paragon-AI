"""
Example usage of the WebSocket Price Feed Service

This script demonstrates how to:
1. Configure the WebSocket connection
2. Handle price updates
3. Manage subscriptions
4. Monitor connection health
"""

import asyncio
import logging
import os
from typing import Dict
from datetime import datetime

from websocket_feed import (
    WebSocketPriceFeed, 
    ConnectionConfig, 
    PriceUpdate, 
    ConnectionState
)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class PriceFeedDemo:
    """Demo class showing WebSocket Price Feed usage"""
    
    def __init__(self, api_key: str):
        # Create connection configuration
        self.config = ConnectionConfig(
            api_key=api_key,
            chain="solana",
            max_tokens_per_connection=50,  # Reduced for demo
            reconnect_delay=2.0,
            max_reconnect_delay=30.0,
            max_reconnect_attempts=5,
            heartbeat_interval=30.0,
            connection_timeout=10.0
        )
        
        # Initialize WebSocket feed
        self.price_feed = WebSocketPriceFeed(self.config)
        
        # Storage for price data
        self.latest_prices: Dict[str, PriceUpdate] = {}
        self.price_history: Dict[str, list] = {}
        
    def setup_handlers(self):
        """Setup event handlers for the price feed"""
        
        # Add price update handler
        self.price_feed.add_price_update_handler(self.handle_price_update)
        
        # Add connection state handler
        self.price_feed.add_connection_handler(self.handle_connection_state)
        
        # Add error handler
        self.price_feed.add_error_handler(self.handle_error)
    
    async def handle_price_update(self, price_update: PriceUpdate):
        """Handle incoming price updates"""
        token = price_update.token_address
        
        # Store latest price
        self.latest_prices[token] = price_update
        
        # Add to history
        if token not in self.price_history:
            self.price_history[token] = []
        
        self.price_history[token].append({
            'timestamp': price_update.timestamp,
            'price': price_update.price,
            'volume_24h': price_update.volume_24h
        })
        
        # Keep only last 100 price points
        if len(self.price_history[token]) > 100:
            self.price_history[token] = self.price_history[token][-100:]
        
        # Log price update
        logger.info(
            f"Price Update - {token[:8]}...{token[-8:]}: "
            f"${price_update.price:.6f} "
            f"(24h vol: ${price_update.volume_24h or 0:,.0f})"
        )
        
        # Calculate simple price change if we have history
        if len(self.price_history[token]) > 1:
            prev_price = self.price_history[token][-2]['price']
            price_change = ((price_update.price - prev_price) / prev_price) * 100
            
            if abs(price_change) > 1.0:  # Log significant price moves
                logger.info(f"Significant price move: {price_change:.2f}%")
    
    def handle_connection_state(self, state: ConnectionState):
        """Handle connection state changes"""
        logger.info(f"Connection state changed to: {state.value}")
        
        if state == ConnectionState.CONNECTED:
            logger.info("✅ WebSocket connected successfully")
        elif state == ConnectionState.DISCONNECTED:
            logger.warning("❌ WebSocket disconnected")
        elif state == ConnectionState.RECONNECTING:
            logger.info("🔄 WebSocket reconnecting...")
        elif state == ConnectionState.FAILED:
            logger.error("💥 WebSocket connection failed permanently")
    
    async def handle_error(self, error: Exception):
        """Handle WebSocket errors"""
        logger.error(f"WebSocket error: {error}")
    
    async def run_demo(self):
        """Run the price feed demo"""
        try:
            logger.info("Starting WebSocket Price Feed Demo...")
            
            # Setup event handlers
            self.setup_handlers()
            
            # Start the price feed
            await self.price_feed.start()
            
            # Wait a moment for connection
            await asyncio.sleep(2)
            
            # Subscribe to some popular Solana tokens
            tokens_to_track = [
                "So11111111111111111111111111111111111111112",  # SOL
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",  # BONK
                "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",   # JUP
            ]
            
            for token in tokens_to_track:
                success = await self.price_feed.subscribe_to_token(token, "1m")
                if success:
                    logger.info(f"✅ Subscribed to {token[:8]}...{token[-8:]}")
                else:
                    logger.error(f"❌ Failed to subscribe to {token[:8]}...{token[-8:]}")
            
            logger.info(f"Tracking {len(tokens_to_track)} tokens...")
            
            # Run for specified duration
            demo_duration = 60  # 1 minute demo
            logger.info(f"Running demo for {demo_duration} seconds...")
            
            # Print stats every 10 seconds
            for i in range(demo_duration // 10):
                await asyncio.sleep(10)
                stats = self.price_feed.get_stats()
                logger.info(
                    f"Stats - Messages: {stats['messages_received']}/{stats['messages_processed']}, "
                    f"Subscriptions: {stats['active_subscriptions']}, "
                    f"State: {stats['connection_state']}"
                )
            
            # Print final summary
            self.print_summary()
            
        except KeyboardInterrupt:
            logger.info("Demo interrupted by user")
        except Exception as e:
            logger.error(f"Demo error: {e}")
        finally:
            # Cleanup
            logger.info("Stopping WebSocket feed...")
            await self.price_feed.stop()
            logger.info("Demo completed")
    
    def print_summary(self):
        """Print summary of collected data"""
        logger.info("\n" + "="*50)
        logger.info("DEMO SUMMARY")
        logger.info("="*50)
        
        for token, price_update in self.latest_prices.items():
            history = self.price_history.get(token, [])
            logger.info(
                f"Token: {token[:8]}...{token[-8:]}\n"
                f"  Latest Price: ${price_update.price:.6f}\n"
                f"  Price Updates: {len(history)}\n"
                f"  24h Volume: ${price_update.volume_24h or 0:,.0f}\n"
            )
        
        stats = self.price_feed.get_stats()
        logger.info(f"Total Messages Received: {stats['messages_received']}")
        logger.info(f"Total Messages Processed: {stats['messages_processed']}")
        logger.info(f"Connection Attempts: {stats['connection_attempts']}")
        logger.info(f"Errors: {stats['errors']}")


async def main():
    """Main function to run the demo"""
    # Get API key from environment variable
    api_key = os.getenv('BIRDEYE_API_KEY')
    
    if not api_key:
        logger.error(
            "Please set BIRDEYE_API_KEY environment variable\n"
            "Example: export BIRDEYE_API_KEY='your-api-key-here'"
        )
        return
    
    # Create and run demo
    demo = PriceFeedDemo(api_key)
    await demo.run_demo()


if __name__ == "__main__":
    # Run the demo
    asyncio.run(main()) 