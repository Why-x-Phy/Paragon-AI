"""
Calvin Vault Integration Module

This module provides the necessary clients and executors for the Calvin AI system
to interact with the on-chain vault smart contracts and integrated protocols like Jupiter.

It includes:
- VaultClient: Interface to Calvin vault smart contracts for deposits, withdrawals, and state queries.
- JupiterV6Client: Jupiter API integration for fetching swap quotes and creating transaction data.
- EmergencyStopLossMonitor: WebSocket-based monitoring for emergency risk management.
- VaultTradeExecutor: Orchestrates trading signals into vault-executed transactions.
- TradeVerifier: Verifies and records trade outcomes against on-chain data.
"""

from .vault_client import VaultClient
from .jupiter_client import JupiterV6Client
from .emergency_monitor import EmergencyStopLossMonitor
from .trade_executor import VaultTradeExecutor
from .trade_verifier import TradeVerificationService

__all__ = [
    "VaultClient",
    "JupiterV6Client",
    "EmergencyStopLossMonitor",
    "VaultTradeExecutor",
    "TradeVerificationService",
]

# Import order optimized for graceful degradation
try:
    from .trade_executor import VaultTradeExecutor
except ImportError as e:
    # Allow graceful degradation if dependencies are missing
    import logging
    logging.getLogger(__name__).warning(f"Vault module components not available: {e}") 