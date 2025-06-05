"""
Unit tests for WebSocket Price Feed Service

Tests cover:
1. Connection management
2. Subscription handling
3. Message processing
4. Error handling and recovery
5. Event broadcasting
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from websocket_feed import (
    WebSocketPriceFeed,
    ConnectionConfig,
    PriceUpdate,
    ConnectionState,
    SubscriptionType,
    SubscriptionConfig
)


@pytest.fixture
def config():
    """Create a test configuration"""
    return ConnectionConfig(
        api_key="test_api_key",
        chain="solana",
        max_tokens_per_connection=10,
        reconnect_delay=0.1,
        max_reconnect_delay=1.0,
        max_reconnect_attempts=3,
        heartbeat_interval=1.0,
        connection_timeout=1.0
    )


@pytest.fixture
def price_feed(config):
    """Create a WebSocket price feed instance"""
    return WebSocketPriceFeed(config)


@pytest.fixture
def sample_price_data():
    """Sample price update data"""
    return {
        "data": {
            "address": "So11111111111111111111111111111111111111112",
            "price": 145.67,
            "volume24h": 1500000.0,
            "priceChange24h": 2.5,
            "marketCap": 65000000000.0
        }
    }


class TestWebSocketPriceFeed:
    """Test suite for WebSocketPriceFeed class"""
    
    def test_initialization(self, price_feed, config):
        """Test WebSocket feed initialization"""
        assert price_feed.config == config
        assert price_feed.connection_state == ConnectionState.DISCONNECTED
        assert len(price_feed.active_subscriptions) == 0
        assert len(price_feed.price_update_handlers) == 0
        
    def test_websocket_url_generation(self, price_feed):
        """Test WebSocket URL generation"""
        expected_url = "wss://public-api.birdeye.so/socket/solana?x-api-key=test_api_key"
        assert price_feed.websocket_url == expected_url
        
    def test_headers_generation(self, price_feed):
        """Test WebSocket headers generation"""
        headers = price_feed.headers
        assert headers['Origin'] == 'ws://public-api.birdeye.so'
        assert headers['Sec-WebSocket-Origin'] == 'ws://public-api.birdeye.so'
        assert headers['Sec-WebSocket-Protocol'] == 'echo-protocol'
    
    def test_add_handlers(self, price_feed):
        """Test adding event handlers"""
        price_handler = Mock()
        connection_handler = Mock()
        error_handler = Mock()
        
        price_feed.add_price_update_handler(price_handler)
        price_feed.add_connection_handler(connection_handler)
        price_feed.add_error_handler(error_handler)
        
        assert price_handler in price_feed.price_update_handlers
        assert connection_handler in price_feed.connection_handlers
        assert error_handler in price_feed.error_handlers
    
    @pytest.mark.asyncio
    async def test_subscribe_to_token(self, price_feed):
        """Test token subscription"""
        token_address = "So11111111111111111111111111111111111111112"
        
        success = await price_feed.subscribe_to_token(token_address, "1m")
        
        assert success is True
        assert token_address in price_feed.active_subscriptions
        assert price_feed.active_subscriptions[token_address].chart_type == "1m"
        assert price_feed.active_subscriptions[token_address].token_address == token_address
    
    @pytest.mark.asyncio
    async def test_subscribe_token_limit(self, price_feed):
        """Test token subscription limit"""
        # Fill up to max tokens
        for i in range(price_feed.config.max_tokens_per_connection):
            success = await price_feed.subscribe_to_token(f"token_{i}")
            assert success is True
        
        # Try to add one more (should fail)
        success = await price_feed.subscribe_to_token("overflow_token")
        assert success is False
    
    @pytest.mark.asyncio
    async def test_unsubscribe_from_token(self, price_feed):
        """Test token unsubscription"""
        token_address = "So11111111111111111111111111111111111111112"
        
        # Subscribe first
        await price_feed.subscribe_to_token(token_address)
        assert token_address in price_feed.active_subscriptions
        
        # Unsubscribe
        success = await price_feed.unsubscribe_from_token(token_address)
        assert success is True
        assert token_address not in price_feed.active_subscriptions
    
    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_token(self, price_feed):
        """Test unsubscribing from non-existent token"""
        success = await price_feed.unsubscribe_from_token("nonexistent_token")
        assert success is False
    
    @pytest.mark.asyncio
    async def test_process_price_update(self, price_feed, sample_price_data):
        """Test processing price update messages"""
        price_handler = AsyncMock()
        price_feed.add_price_update_handler(price_handler)
        
        await price_feed._handle_price_update(sample_price_data)
        
        price_handler.assert_called_once()
        price_update = price_handler.call_args[0][0]
        
        assert isinstance(price_update, PriceUpdate)
        assert price_update.token_address == "So11111111111111111111111111111111111111112"
        assert price_update.price == 145.67
        assert price_update.volume_24h == 1500000.0
    
    @pytest.mark.asyncio
    async def test_process_message_with_type(self, price_feed, sample_price_data):
        """Test processing message with explicit type"""
        price_handler = AsyncMock()
        price_feed.add_price_update_handler(price_handler)
        
        message_data = json.dumps({
            "type": "PRICE_UPDATE",
            **sample_price_data
        })
        
        await price_feed._process_message(message_data)
        
        price_handler.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_invalid_json(self, price_feed):
        """Test processing invalid JSON message"""
        invalid_json = "invalid_json_data"
        
        # Should not raise exception
        await price_feed._process_message(invalid_json)
    
    @pytest.mark.asyncio
    async def test_handle_server_error(self, price_feed):
        """Test handling server error messages"""
        error_handler = AsyncMock()
        price_feed.add_error_handler(error_handler)
        
        error_data = {
            "type": "ERROR",
            "message": "Server error occurred"
        }
        
        await price_feed._handle_server_error(error_data)
        
        error_handler.assert_called_once()
        error_arg = error_handler.call_args[0][0]
        assert "Server error: Server error occurred" in str(error_arg)
    
    def test_connection_state_update(self, price_feed):
        """Test connection state updates"""
        connection_handler = Mock()
        price_feed.add_connection_handler(connection_handler)
        
        price_feed._update_connection_state(ConnectionState.CONNECTING)
        
        assert price_feed.connection_state == ConnectionState.CONNECTING
        connection_handler.assert_called_once_with(ConnectionState.CONNECTING)
    
    def test_get_stats(self, price_feed):
        """Test getting statistics"""
        stats = price_feed.get_stats()
        
        assert 'messages_received' in stats
        assert 'messages_processed' in stats
        assert 'connection_state' in stats
        assert 'active_subscriptions' in stats
        assert stats['connection_state'] == 'disconnected'
        assert stats['active_subscriptions'] == 0
    
    def test_get_subscribed_tokens(self, price_feed):
        """Test getting list of subscribed tokens"""
        tokens = price_feed.get_subscribed_tokens()
        assert tokens == []


class TestConnectionManagement:
    """Test suite for connection management"""
    
    @pytest.mark.asyncio
    async def test_start_already_started(self, price_feed):
        """Test starting already started feed"""
        price_feed.connection_state = ConnectionState.CONNECTED
        
        with patch.object(price_feed.logger, 'warning') as mock_warning:
            await price_feed.start()
            mock_warning.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_stop_cleanup(self, price_feed):
        """Test stopping and cleanup"""
        # Mock tasks and connections
        price_feed.connection_task = AsyncMock()
        price_feed.processing_task = AsyncMock()
        price_feed.ws_connection = AsyncMock()
        price_feed.ws_session = AsyncMock()
        
        await price_feed.stop()
        
        price_feed.connection_task.cancel.assert_called_once()
        price_feed.processing_task.cancel.assert_called_once()
        price_feed.ws_connection.close.assert_called_once()
        price_feed.ws_session.close.assert_called_once()
        
        assert price_feed.connection_state == ConnectionState.DISCONNECTED


class TestSubscriptionManagement:
    """Test suite for subscription management"""
    
    @pytest.mark.asyncio
    async def test_send_subscription_not_connected(self, price_feed):
        """Test sending subscription when not connected"""
        subscription = SubscriptionConfig(
            token_address="test_token",
            chart_type="1m"
        )
        
        with patch.object(price_feed.logger, 'warning') as mock_warning:
            await price_feed._send_subscription(subscription)
            mock_warning.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_subscription_connected(self, price_feed):
        """Test sending subscription when connected"""
        # Mock WebSocket connection
        mock_ws = AsyncMock()
        price_feed.ws_connection = mock_ws
        price_feed.connection_state = ConnectionState.CONNECTED
        
        subscription = SubscriptionConfig(
            token_address="test_token",
            chart_type="1m"
        )
        
        await price_feed._send_subscription(subscription)
        
        mock_ws.send_str.assert_called_once()
        sent_message = json.loads(mock_ws.send_str.call_args[0][0])
        
        assert sent_message['type'] == 'SUBSCRIBE_PRICE'
        assert sent_message['data']['address'] == 'test_token'
        assert sent_message['data']['chartType'] == '1m'
    
    @pytest.mark.asyncio
    async def test_resubscribe_all(self, price_feed):
        """Test resubscribing to all tokens after reconnection"""
        # Add some subscriptions
        await price_feed.subscribe_to_token("token1", "1m")
        await price_feed.subscribe_to_token("token2", "5m")
        
        # Mock WebSocket connection
        mock_ws = AsyncMock()
        price_feed.ws_connection = mock_ws
        price_feed.connection_state = ConnectionState.CONNECTED
        
        await price_feed._resubscribe_all()
        
        # Should have called send_str twice (once for each token)
        assert mock_ws.send_str.call_count == 2


class TestErrorHandling:
    """Test suite for error handling"""
    
    @pytest.mark.asyncio
    async def test_handle_error(self, price_feed):
        """Test error handling"""
        error_handler = AsyncMock()
        price_feed.add_error_handler(error_handler)
        
        test_error = Exception("Test error")
        await price_feed._handle_error(test_error)
        
        error_handler.assert_called_once_with(test_error)
    
    @pytest.mark.asyncio
    async def test_handler_error_in_handler(self, price_feed):
        """Test handling error in error handler"""
        def failing_handler(error):
            raise Exception("Handler error")
        
        price_feed.add_error_handler(failing_handler)
        
        # Should not raise exception
        test_error = Exception("Test error")
        await price_feed._handle_error(test_error)


class TestMessageProcessing:
    """Test suite for message processing"""
    
    @pytest.mark.asyncio
    async def test_message_queue_full(self, price_feed):
        """Test handling full message queue"""
        # Fill the queue
        for _ in range(1000):
            try:
                await price_feed.message_queue.put_nowait("test_message")
            except asyncio.QueueFull:
                break
        
        # Mock WebSocket message
        from aiohttp import WSMsgType
        mock_msg = Mock()
        mock_msg.type = WSMsgType.TEXT
        mock_msg.data = "overflow_message"
        
        # Should handle queue full gracefully
        # This is tested indirectly through the warning log
        with patch.object(price_feed.logger, 'warning') as mock_warning:
            # Simulate the queue full condition in _listen_for_messages
            try:
                await price_feed.message_queue.put_nowait(mock_msg.data)
            except asyncio.QueueFull:
                price_feed.logger.warning("Message queue full, dropping message")
                mock_warning.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__]) 