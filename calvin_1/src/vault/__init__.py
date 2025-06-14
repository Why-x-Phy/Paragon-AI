"""
Calvin AI Vault Integration Module

Phase 3.2 implementation for vault trading integration:
- VaultTradeExecutor: Executes portfolio signals through vault smart contracts
- VaultClient: Interface to Calvin vault smart contracts (to be implemented)
- JupiterV6Client: Jupiter API integration for swap data (to be implemented)
- EmergencyMonitor: WebSocket-based emergency stop loss monitoring (to be implemented)
"""

# Import order optimized for graceful degradation
try:
    from .trade_executor import VaultTradeExecutor
    __all__ = ['VaultTradeExecutor']
except ImportError as e:
    # Allow graceful degradation if dependencies are missing
    __all__ = []
    import logging
    logging.getLogger(__name__).warning(f"Vault module components not available: {e}") 