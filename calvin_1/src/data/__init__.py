"""
Calvin AI Data Module

Real-time data streaming and processing components for Calvin AI trading system.
"""

from .websocket_feed import (
    BirdEyeWebSocketFeed,
    ConnectionConfig,
    PriceUpdate,
    PriceSubscription,
    ConnectionState,
    SubscriptionType
)

__all__ = [
    'BirdEyeWebSocketFeed',
    'ConnectionConfig', 
    'PriceUpdate',
    'PriceSubscription',
    'ConnectionState',
    'SubscriptionType'
]

__version__ = '1.0.0'
__author__ = 'Calvin AI Team'

# This file makes data a proper Python package 