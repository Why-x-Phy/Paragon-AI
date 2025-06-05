"""
Comprehensive test suite for Calvin AI Portfolio Coordinator

Tests the multi-asset portfolio coordination engine including:
- Configuration loading from environment variables
- Multi-asset signal generation and coordination
- Portfolio-level risk assessment
- Asset allocation calculations
- Performance tracking and monitoring

Usage:
    cd calvin_1
    python test_portfolio_coordinator.py
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List
import numpy as np

# Add the src directory to Python path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.utils.logger import log
from src.inference.portfolio_coordinator import (
    PortfolioCoordinator, PortfolioConfig, AllocationMethod,
    AssetAllocation, PortfolioSignal, get_portfolio_coordinator
)
from src.inference.strategy_engine import TradingSignal, SignalType, SignalStrength

logger = log

class PortfolioCoordinatorTester:
    """Comprehensive test suite for Portfolio Coordinator"""
    
    def __init__(self):
        self.test_results = {}
        self.coordinator = None
        
    async def run_all_tests(self):
        """Run all Portfolio Coordinator tests"""
        logger.info("🎯 Starting Portfolio Coordinator Test Suite")
        logger.info("=" * 70)
        
        try:
            # Test 1: Configuration Loading
            await self._test_configuration_loading()
            
            # Test 2: Portfolio Coordinator Initialization
            await self._test_coordinator_initialization()
            
            # Test 3: Portfolio Signal Generation
            await self._test_portfolio_signal_generation()
            
            # Test 4: Risk Assessment
            await self._test_risk_assessment()
            
            # Test 5: Asset Allocation
            await self._test_asset_allocation()
            
            # Test 6: Signal Filtering
            await self._test_signal_filtering()
            
            # Test 7: Portfolio Status
            await self._test_portfolio_status()
            
            # Test 8: Performance Tracking
            await self._test_performance_tracking()
            
            # Test 9: Integration with Strategy Engine
            await self._test_strategy_engine_integration()
            
            # Test 10: Convenience Functions
            await self._test_convenience_functions()
            
        except Exception as e:
            logger.error(f"❌ Test suite failed with exception: {e}")
            self.test_results['test_suite_error'] = {'success': False, 'error': str(e)}
        
        finally:
            await self._cleanup()
        
        # Print summary
        self._print_test_summary()

    async def _test_configuration_loading(self):
        """Test 1: Configuration Loading from Environment Variables"""
        logger.info("1️⃣  Testing Configuration Loading...")
        
        try:
            # Test default configuration
            default_config = PortfolioConfig()
            
            # Test environment variable loading
            coordinator = PortfolioCoordinator()
            env_config = coordinator.config
            
            # Validate configuration values
            assert env_config.max_portfolio_exposure_pct == 80.0, f"Expected 80.0, got {env_config.max_portfolio_exposure_pct}"
            assert env_config.max_single_asset_exposure_pct == 20.0, f"Expected 20.0, got {env_config.max_single_asset_exposure_pct}"
            assert env_config.min_signal_confidence == 0.70, f"Expected 0.70, got {env_config.min_signal_confidence}"
            assert env_config.allocation_method == AllocationMethod.CONFIDENCE_WEIGHTED, f"Expected CONFIDENCE_WEIGHTED, got {env_config.allocation_method}"
            
            # Test custom configuration
            custom_config = PortfolioConfig(
                max_portfolio_exposure_pct=70.0,
                allocation_method=AllocationMethod.EQUAL_WEIGHT
            )
            custom_coordinator = PortfolioCoordinator(config=custom_config)
            assert custom_coordinator.config.max_portfolio_exposure_pct == 70.0
            assert custom_coordinator.config.allocation_method == AllocationMethod.EQUAL_WEIGHT
            
            self.test_results['configuration_loading'] = {
                'success': True,
                'default_config': 'valid',
                'env_config': 'loaded correctly',
                'custom_config': 'working',
                'risk_limits': 'created successfully'
            }
            
            logger.info("✅ Configuration loading test passed")
            
        except Exception as e:
            logger.error(f"❌ Configuration loading test failed: {e}")
            self.test_results['configuration_loading'] = {'success': False, 'error': str(e)}

    async def _test_coordinator_initialization(self):
        """Test 2: Portfolio Coordinator Initialization"""
        logger.info("2️⃣  Testing Portfolio Coordinator Initialization...")
        
        try:
            # Create and initialize coordinator
            self.coordinator = PortfolioCoordinator()
            await self.coordinator.initialize()
            
            # Validate initialization
            assert self.coordinator.db_manager is not None, "Database manager not initialized"
            assert self.coordinator.strategy_engine is not None, "Strategy engine not initialized"
            assert self.coordinator.model_registry is not None, "Model registry not initialized"
            assert len(self.coordinator.tracked_symbols) > 0, "No tracked symbols loaded"
            
            # Test tracked symbols loading
            logger.info(f"   ✅ Loaded {len(self.coordinator.tracked_symbols)} tracked symbols")
            logger.info(f"   - Symbols: {', '.join(self.coordinator.tracked_symbols[:5])}{'...' if len(self.coordinator.tracked_symbols) > 5 else ''}")
            
            self.test_results['coordinator_initialization'] = {
                'success': True,
                'db_manager': 'initialized',
                'strategy_engine': 'initialized',
                'model_registry': 'initialized',
                'tracked_symbols_count': len(self.coordinator.tracked_symbols),
                'tracked_symbols': self.coordinator.tracked_symbols[:10]  # First 10 for brevity
            }
            
            logger.info("✅ Portfolio Coordinator initialization test passed")
            
        except Exception as e:
            logger.error(f"❌ Portfolio Coordinator initialization test failed: {e}")
            self.test_results['coordinator_initialization'] = {'success': False, 'error': str(e)}

    async def _test_portfolio_signal_generation(self):
        """Test 3: Portfolio Signal Generation"""
        logger.info("3️⃣  Testing Portfolio Signal Generation...")
        
        try:
            if not self.coordinator:
                raise Exception("Coordinator not initialized")
            
            # Test portfolio signal generation
            start_time = datetime.now()
            portfolio_signal = await self.coordinator.generate_portfolio_signals()
            processing_time = (datetime.now() - start_time).total_seconds()
            
            # Validate portfolio signal
            if portfolio_signal:
                assert isinstance(portfolio_signal, PortfolioSignal), "Invalid portfolio signal type"
                assert portfolio_signal.timestamp is not None, "Missing timestamp"
                assert portfolio_signal.portfolio_value > 0, "Invalid portfolio value"
                assert isinstance(portfolio_signal.buy_signals, list), "Buy signals not a list"
                assert isinstance(portfolio_signal.sell_signals, list), "Sell signals not a list"
                assert isinstance(portfolio_signal.asset_allocations, dict), "Asset allocations not a dict"
                
                signal_count = len(portfolio_signal.buy_signals) + len(portfolio_signal.sell_signals)
                
                self.test_results['portfolio_signal_generation'] = {
                    'success': True,
                    'processing_time_ms': processing_time * 1000,
                    'portfolio_value': portfolio_signal.portfolio_value,
                    'current_exposure_pct': portfolio_signal.current_exposure_pct,
                    'buy_signals_count': len(portfolio_signal.buy_signals),
                    'sell_signals_count': len(portfolio_signal.sell_signals),
                    'total_signals': signal_count,
                    'asset_allocations_count': len(portfolio_signal.asset_allocations),
                    'execution_priority': portfolio_signal.execution_priority,
                    'portfolio_risk_score': portfolio_signal.portfolio_risk_score
                }
                
                logger.info(f"   ✅ Portfolio signal generated in {processing_time * 1000:.1f}ms")
                logger.info(f"   - Portfolio value: ${portfolio_signal.portfolio_value:,.2f}")
                logger.info(f"   - Signals: {len(portfolio_signal.buy_signals)} BUY, {len(portfolio_signal.sell_signals)} SELL")
                logger.info(f"   - Asset allocations: {len(portfolio_signal.asset_allocations)}")
                logger.info(f"   - Risk score: {portfolio_signal.portfolio_risk_score:.3f}")
                
            else:
                logger.warning("   ⚠️  No portfolio signal generated (this may be expected if no models available)")
                self.test_results['portfolio_signal_generation'] = {
                    'success': True,
                    'note': 'No signals generated - may be expected in test environment'
                }
            
            logger.info("✅ Portfolio signal generation test passed")
            
        except Exception as e:
            logger.error(f"❌ Portfolio signal generation test failed: {e}")
            self.test_results['portfolio_signal_generation'] = {'success': False, 'error': str(e)}

    async def _test_risk_assessment(self):
        """Test 4: Risk Assessment Functionality"""
        logger.info("4️⃣  Testing Risk Assessment...")
        
        try:
            if not self.coordinator:
                raise Exception("Coordinator not initialized")
            
            # Create mock signals for testing
            mock_signals = self._create_mock_signals()
            
            # Test portfolio state retrieval
            portfolio_state = await self.coordinator._get_portfolio_state()
            assert portfolio_state is not None, "Failed to get portfolio state"
            assert 'portfolio_value' in portfolio_state, "Missing portfolio_value in state"
            assert 'cash_balance' in portfolio_state, "Missing cash_balance in state"
            assert 'exposure_pct' in portfolio_state, "Missing exposure_pct in state"
            
            # Test risk assessment
            risk_assessment = await self.coordinator._assess_portfolio_risk(mock_signals, portfolio_state)
            assert 'portfolio_risk' in risk_assessment, "Missing portfolio_risk"
            assert 'concentration_risk' in risk_assessment, "Missing concentration_risk"
            assert 'correlation_risk' in risk_assessment, "Missing correlation_risk"
            
            # Validate risk scores are in valid range (0-1)
            for risk_type, score in risk_assessment.items():
                assert 0.0 <= score <= 1.0, f"Risk score {risk_type} out of range: {score}"
            
            self.test_results['risk_assessment'] = {
                'success': True,
                'portfolio_state': portfolio_state,
                'risk_assessment': risk_assessment,
                'mock_signals_count': len(mock_signals)
            }
            
            logger.info(f"   ✅ Risk assessment completed")
            logger.info(f"   - Portfolio risk: {risk_assessment['portfolio_risk']:.3f}")
            logger.info(f"   - Concentration risk: {risk_assessment['concentration_risk']:.3f}")
            logger.info(f"   - Correlation risk: {risk_assessment['correlation_risk']:.3f}")
            
            logger.info("✅ Risk assessment test passed")
            
        except Exception as e:
            logger.error(f"❌ Risk assessment test failed: {e}")
            self.test_results['risk_assessment'] = {'success': False, 'error': str(e)}

    async def _test_asset_allocation(self):
        """Test 5: Asset Allocation Calculations"""
        logger.info("5️⃣  Testing Asset Allocation...")
        
        try:
            if not self.coordinator:
                raise Exception("Coordinator not initialized")
            
            # Create mock signals and portfolio state
            mock_signals = self._create_mock_signals()
            portfolio_state = await self.coordinator._get_portfolio_state()
            risk_assessment = await self.coordinator._assess_portfolio_risk(mock_signals, portfolio_state)
            
            # Test allocation weight calculations
            buy_signals = [s for s in mock_signals if s.signal_type == SignalType.BUY]
            
            # Test different allocation methods
            allocation_methods = [
                AllocationMethod.EQUAL_WEIGHT,
                AllocationMethod.CONFIDENCE_WEIGHTED,
                AllocationMethod.SIGNAL_STRENGTH
            ]
            
            allocation_results = {}
            
            for method in allocation_methods:
                original_method = self.coordinator.config.allocation_method
                self.coordinator.config.allocation_method = method
                
                weights = self.coordinator._calculate_allocation_weights(buy_signals, risk_assessment)
                
                # Validate weights
                assert len(weights) == len(buy_signals), f"Weight count mismatch for {method.value}"
                assert abs(sum(weights) - 1.0) < 0.001, f"Weights don't sum to 1.0 for {method.value}: {sum(weights)}"
                assert all(w >= 0 for w in weights), f"Negative weights found for {method.value}"
                
                allocation_results[method.value] = {
                    'weights': weights,
                    'sum': sum(weights),
                    'valid': True
                }
                
                # Restore original method
                self.coordinator.config.allocation_method = original_method
            
            # Test full asset allocation calculation
            asset_allocations = await self.coordinator._calculate_asset_allocations(
                mock_signals, portfolio_state, risk_assessment
            )
            
            # Validate allocations
            for symbol, allocation in asset_allocations.items():
                assert isinstance(allocation, AssetAllocation), f"Invalid allocation type for {symbol}"
                assert allocation.symbol == symbol, f"Symbol mismatch for {symbol}"
                assert allocation.position_value_usdc >= 0, f"Negative position value for {symbol}"
                assert allocation.target_exposure_pct >= 0, f"Negative exposure for {symbol}"
            
            self.test_results['asset_allocation'] = {
                'success': True,
                'allocation_methods_tested': len(allocation_methods),
                'allocation_results': allocation_results,
                'asset_allocations_count': len(asset_allocations),
                'mock_signals_used': len(mock_signals)
            }
            
            logger.info(f"   ✅ Asset allocation completed")
            logger.info(f"   - Allocation methods tested: {len(allocation_methods)}")
            logger.info(f"   - Asset allocations calculated: {len(asset_allocations)}")
            
            logger.info("✅ Asset allocation test passed")
            
        except Exception as e:
            logger.error(f"❌ Asset allocation test failed: {e}")
            self.test_results['asset_allocation'] = {'success': False, 'error': str(e)}

    async def _test_signal_filtering(self):
        """Test 6: Signal Filtering Logic"""
        logger.info("6️⃣  Testing Signal Filtering...")
        
        try:
            if not self.coordinator:
                raise Exception("Coordinator not initialized")
            
            # Create signals with different confidence levels and ages
            test_signals = []
            
            # High confidence signal (should pass)
            high_conf_signal = TradingSignal(
                symbol="TEST1",
                signal_type=SignalType.BUY,
                strength=SignalStrength.STRONG,
                confidence=0.85,
                predicted_price=100.0,
                current_price=95.0,
                predicted_change_pct=0.05,
                timestamp=datetime.now(),
                buy_threshold=0.02,
                sell_threshold=0.03,
                confidence_threshold=0.70,
                model_version="test",
                processing_time_ms=100.0,
                raw_prediction=0.05
            )
            test_signals.append(high_conf_signal)
            
            # Low confidence signal (should be filtered)
            low_conf_signal = TradingSignal(
                symbol="TEST2",
                signal_type=SignalType.SELL,
                strength=SignalStrength.WEAK,
                confidence=0.50,  # Below threshold
                predicted_price=90.0,
                current_price=95.0,
                predicted_change_pct=-0.05,
                timestamp=datetime.now(),
                buy_threshold=0.02,
                sell_threshold=0.03,
                confidence_threshold=0.70,
                model_version="test",
                processing_time_ms=100.0,
                raw_prediction=-0.05
            )
            test_signals.append(low_conf_signal)
            
            # Old signal (should be filtered)
            old_signal = TradingSignal(
                symbol="TEST3",
                signal_type=SignalType.BUY,
                strength=SignalStrength.MODERATE,
                confidence=0.80,
                predicted_price=105.0,
                current_price=100.0,
                predicted_change_pct=0.05,
                timestamp=datetime.now() - timedelta(minutes=30),  # Too old
                buy_threshold=0.02,
                sell_threshold=0.03,
                confidence_threshold=0.70,
                model_version="test",
                processing_time_ms=100.0,
                raw_prediction=0.05
            )
            test_signals.append(old_signal)
            
            # Test signal filtering
            filtered_signals = self.coordinator._filter_signals(test_signals)
            
            # Should only have the high confidence signal
            assert len(filtered_signals) == 1, f"Expected 1 filtered signal, got {len(filtered_signals)}"
            assert filtered_signals[0].symbol == "TEST1", "Wrong signal passed filter"
            assert filtered_signals[0].confidence >= self.coordinator.config.min_signal_confidence
            
            self.test_results['signal_filtering'] = {
                'success': True,
                'input_signals': len(test_signals),
                'filtered_signals': len(filtered_signals),
                'high_confidence_passed': filtered_signals[0].symbol == "TEST1",
                'low_confidence_filtered': True,
                'old_signal_filtered': True
            }
            
            logger.info(f"   ✅ Signal filtering completed")
            logger.info(f"   - Input signals: {len(test_signals)}")
            logger.info(f"   - Filtered signals: {len(filtered_signals)}")
            logger.info(f"   - Confidence threshold: {self.coordinator.config.min_signal_confidence:.2f}")
            
            logger.info("✅ Signal filtering test passed")
            
        except Exception as e:
            logger.error(f"❌ Signal filtering test failed: {e}")
            self.test_results['signal_filtering'] = {'success': False, 'error': str(e)}

    async def _test_portfolio_status(self):
        """Test 7: Portfolio Status Reporting"""
        logger.info("7️⃣  Testing Portfolio Status...")
        
        try:
            if not self.coordinator:
                raise Exception("Coordinator not initialized")
            
            # Get portfolio status
            status = await self.coordinator.get_portfolio_status()
            
            # Validate status structure
            required_fields = [
                'timestamp', 'portfolio_value', 'cash_balance', 'exposure_pct',
                'position_count', 'tracked_symbols', 'allocation_method'
            ]
            
            for field in required_fields:
                assert field in status, f"Missing required field: {field}"
            
            # Validate data types and values
            assert isinstance(status['portfolio_value'], (int, float)), "Invalid portfolio_value type"
            assert isinstance(status['cash_balance'], (int, float)), "Invalid cash_balance type"
            assert isinstance(status['exposure_pct'], (int, float)), "Invalid exposure_pct type"
            assert isinstance(status['tracked_symbols'], int), "Invalid tracked_symbols type"
            assert status['portfolio_value'] > 0, "Portfolio value should be positive"
            assert 0 <= status['exposure_pct'] <= 100, "Exposure percentage out of range"
            
            self.test_results['portfolio_status'] = {
                'success': True,
                'status_fields': list(status.keys()),
                'portfolio_value': status['portfolio_value'],
                'tracked_symbols': status['tracked_symbols'],
                'allocation_method': status['allocation_method']
            }
            
            logger.info(f"   ✅ Portfolio status retrieved")
            logger.info(f"   - Portfolio value: ${status['portfolio_value']:,.2f}")
            logger.info(f"   - Exposure: {status['exposure_pct']:.1f}%")
            logger.info(f"   - Tracked symbols: {status['tracked_symbols']}")
            
            logger.info("✅ Portfolio status test passed")
            
        except Exception as e:
            logger.error(f"❌ Portfolio status test failed: {e}")
            self.test_results['portfolio_status'] = {'success': False, 'error': str(e)}

    async def _test_performance_tracking(self):
        """Test 8: Performance Tracking"""
        logger.info("8️⃣  Testing Performance Tracking...")
        
        try:
            if not self.coordinator:
                raise Exception("Coordinator not initialized")
            
            # Create mock portfolio signals for tracking
            mock_portfolio_signal = PortfolioSignal(
                timestamp=datetime.now(),
                total_cash_available=80000.0,
                portfolio_value=100000.0,
                current_exposure_pct=20.0,
                buy_signals=[],
                sell_signals=[],
                asset_allocations={},
                cash_allocation_pct=80.0,
                portfolio_risk_score=0.3,
                correlation_risk=0.2,
                concentration_risk=0.4,
                execution_priority=3
            )
            
            # Test performance tracking update
            initial_history_length = len(self.coordinator.portfolio_history)
            self.coordinator._update_performance_tracking(mock_portfolio_signal)
            final_history_length = len(self.coordinator.portfolio_history)
            
            # Validate history was updated
            assert final_history_length == initial_history_length + 1, "Portfolio history not updated"
            
            # Test history management (should keep reasonable size)
            # Add many signals to test history trimming
            for i in range(1005):  # Add more than max_history (1000)
                test_signal = PortfolioSignal(
                    timestamp=datetime.now() - timedelta(minutes=i),
                    total_cash_available=80000.0,
                    portfolio_value=100000.0,
                    current_exposure_pct=20.0,
                    buy_signals=[],
                    sell_signals=[],
                    asset_allocations={},
                    cash_allocation_pct=80.0,
                    portfolio_risk_score=0.3 + i * 0.001,
                    correlation_risk=0.2,
                    concentration_risk=0.4,
                    execution_priority=3
                )
                self.coordinator._update_performance_tracking(test_signal)
            
            # History should be capped at 1000
            assert len(self.coordinator.portfolio_history) <= 1000, f"History too long: {len(self.coordinator.portfolio_history)}"
            
            self.test_results['performance_tracking'] = {
                'success': True,
                'history_updated': True,
                'final_history_length': len(self.coordinator.portfolio_history),
                'history_management': 'working'
            }
            
            logger.info(f"   ✅ Performance tracking working")
            logger.info(f"   - History length: {len(self.coordinator.portfolio_history)}")
            
            logger.info("✅ Performance tracking test passed")
            
        except Exception as e:
            logger.error(f"❌ Performance tracking test failed: {e}")
            self.test_results['performance_tracking'] = {'success': False, 'error': str(e)}

    async def _test_strategy_engine_integration(self):
        """Test 9: Integration with Strategy Engine"""
        logger.info("9️⃣  Testing Strategy Engine Integration...")
        
        try:
            if not self.coordinator:
                raise Exception("Coordinator not initialized")
            
            # Test strategy engine accessibility
            assert self.coordinator.strategy_engine is not None, "Strategy engine not available"
            
            # Test individual signal generation (if models available)
            symbols_to_test = self.coordinator.tracked_symbols[:3]  # Test first 3 symbols
            
            signal_results = []
            for symbol in symbols_to_test:
                try:
                    signal = await self.coordinator.strategy_engine.generate_signal(symbol)
                    signal_results.append({
                        'symbol': symbol,
                        'signal_generated': signal is not None,
                        'signal_type': signal.signal_type.value if signal else None,
                        'confidence': signal.confidence if signal else None
                    })
                except Exception as e:
                    signal_results.append({
                        'symbol': symbol,
                        'signal_generated': False,
                        'error': str(e)
                    })
            
            self.test_results['strategy_engine_integration'] = {
                'success': True,
                'strategy_engine_available': True,
                'symbols_tested': len(symbols_to_test),
                'signal_results': signal_results
            }
            
            logger.info(f"   ✅ Strategy engine integration working")
            logger.info(f"   - Symbols tested: {len(symbols_to_test)}")
            logger.info(f"   - Signal generation attempts: {len(signal_results)}")
            
            logger.info("✅ Strategy engine integration test passed")
            
        except Exception as e:
            logger.error(f"❌ Strategy engine integration test failed: {e}")
            self.test_results['strategy_engine_integration'] = {'success': False, 'error': str(e)}

    async def _test_convenience_functions(self):
        """Test 10: Convenience Functions"""
        logger.info("🔟 Testing Convenience Functions...")
        
        try:
            # Test get_portfolio_coordinator convenience function
            coordinator_instance = await get_portfolio_coordinator()
            assert coordinator_instance is not None, "get_portfolio_coordinator returned None"
            
            # Test that it returns the same instance (singleton pattern)
            coordinator_instance2 = await get_portfolio_coordinator()
            assert coordinator_instance is coordinator_instance2, "Singleton pattern not working"
            
            # Test convenience functions (import them directly to test the module-level functions)
            from src.inference.portfolio_coordinator import generate_portfolio_signals, get_portfolio_status
            
            # Test generate_portfolio_signals convenience function
            portfolio_signal = await generate_portfolio_signals()
            # Note: This may return None if no models are available, which is acceptable
            
            # Test get_portfolio_status convenience function
            status = await get_portfolio_status()
            assert isinstance(status, dict), "get_portfolio_status should return a dict"
            
            self.test_results['convenience_functions'] = {
                'success': True,
                'get_portfolio_coordinator': 'working',
                'singleton_pattern': 'working',
                'generate_portfolio_signals': 'working',
                'get_portfolio_status': 'working'
            }
            
            logger.info(f"   ✅ Convenience functions working")
            
            logger.info("✅ Convenience functions test passed")
            
        except Exception as e:
            logger.error(f"❌ Convenience functions test failed: {e}")
            self.test_results['convenience_functions'] = {'success': False, 'error': str(e)}

    def _create_mock_signals(self) -> List[TradingSignal]:
        """Create mock trading signals for testing"""
        signals = []
        
        # Create a few different types of signals
        signal_configs = [
            {
                'symbol': 'BONK',
                'signal_type': SignalType.BUY,
                'strength': SignalStrength.STRONG,
                'confidence': 0.85,
                'predicted_change_pct': 0.05
            },
            {
                'symbol': 'JUP',
                'signal_type': SignalType.BUY,
                'strength': SignalStrength.MODERATE,
                'confidence': 0.75,
                'predicted_change_pct': 0.03
            },
            {
                'symbol': 'SOL',
                'signal_type': SignalType.SELL,
                'strength': SignalStrength.WEAK,
                'confidence': 0.72,
                'predicted_change_pct': -0.04
            }
        ]
        
        for config in signal_configs:
            current_price = 100.0
            predicted_price = current_price * (1 + config['predicted_change_pct'])
            
            signal = TradingSignal(
                symbol=config['symbol'],
                signal_type=config['signal_type'],
                strength=config['strength'],
                confidence=config['confidence'],
                predicted_price=predicted_price,
                current_price=current_price,
                predicted_change_pct=config['predicted_change_pct'],
                timestamp=datetime.now(),
                buy_threshold=0.02,
                sell_threshold=0.03,
                confidence_threshold=0.70,
                model_version="test_v1",
                processing_time_ms=150.0,
                raw_prediction=config['predicted_change_pct']
            )
            signals.append(signal)
        
        return signals

    async def _cleanup(self):
        """Clean up test resources"""
        try:
            if self.coordinator:
                await self.coordinator.close()
            logger.info("🧹 Test cleanup completed")
        except Exception as e:
            logger.error(f"❌ Test cleanup failed: {e}")

    def _print_test_summary(self):
        """Print comprehensive test summary"""
        logger.info("=" * 70)
        logger.info("📊 PORTFOLIO COORDINATOR TEST SUMMARY")
        logger.info("=" * 70)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result.get('success', False))
        
        logger.info(f"📈 Overall Results: {passed_tests}/{total_tests} tests passed")
        logger.info("")
        
        for test_name, result in self.test_results.items():
            status = "✅ PASS" if result.get('success', False) else "❌ FAIL"
            logger.info(f"{status} {test_name.replace('_', ' ').title()}")
            
            if not result.get('success', False) and 'error' in result:
                logger.info(f"      Error: {result['error']}")
            elif result.get('success', False):
                # Print key metrics for successful tests
                for key, value in result.items():
                    if key not in ['success', 'error'] and not key.endswith('_count'):
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            if key.endswith('_ms'):
                                logger.info(f"      {key}: {value:.1f}ms")
                            elif key.endswith('_pct'):
                                logger.info(f"      {key}: {value:.1f}%")
                            elif 'value' in key.lower():
                                logger.info(f"      {key}: ${value:,.2f}")
        
        logger.info("")
        
        if passed_tests == total_tests:
            logger.info("🎉 ALL TESTS PASSED! Portfolio Coordinator is ready for Phase 2.3 completion.")
        else:
            logger.info(f"⚠️  {total_tests - passed_tests} test(s) failed. Please review and fix issues.")
        
        logger.info("=" * 70)

# Main execution
async def main():
    """Run the Portfolio Coordinator test suite"""
    tester = PortfolioCoordinatorTester()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main()) 