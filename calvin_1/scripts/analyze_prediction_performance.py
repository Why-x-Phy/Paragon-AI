#!/usr/bin/env python3
"""
Prediction Performance Analysis & Threshold Optimization

Analyzes model predictions vs actual price movements to:
1. Identify optimal buy/sell thresholds
2. Calculate opportunity cost of missed trades
3. Suggest data-driven threshold adjustments
4. Compare different threshold strategies
"""

import os
import sys
import asyncio
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import argparse
from pathlib import Path

# Add current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Load environment variables
from dotenv import load_dotenv
project_root = Path(__file__).resolve().parent.parent.parent
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

sys.path.append(str(Path(__file__).parent.parent))
from src.database.production_db import get_db_manager
from src.utils.logger import log as logger

class PredictionAnalyzer:
    """Analyzes prediction performance and optimizes thresholds"""
    
    def __init__(self, db_manager=None):
        self.db_manager = db_manager
        self.predictions_df = None
        self.analysis_results = {}
        
    async def load_prediction_data(self, days_back: int = 7, symbol: Optional[str] = None) -> pd.DataFrame:
        """Load prediction and outcome data from database"""
        try:
            query = """
                WITH price_outcomes AS (
                    SELECT 
                        mp.prediction_id,
                        mp.prediction_time,
                        tk.symbol,
                        mp.prediction_action,
                        mp.confidence_score,
                        mp.predicted_price_change as predicted_change_pct,
                        mp.model_version,
                        
                        -- Get actual price change using OHLCV data
                        -- Price at prediction time
                        o1.close as price_at_prediction,
                        
                        -- Price 1 hour later (our prediction horizon)
                        o2.close as price_1h_later,
                        
                        -- Calculate actual return
                        CASE 
                            WHEN o1.close > 0 AND o2.close > 0 
                            THEN ((o2.close - o1.close) / o1.close) * 100
                            ELSE NULL 
                        END as actual_change_pct,
                        
                        -- Check if trade was executed
                        CASE 
                            WHEN t.trade_id IS NOT NULL THEN t.execution_status
                            ELSE 'no_trade'
                        END as execution_status,
                        
                        -- Trade details if executed
                        t.value_usdc,
                        t.actual_output_amount,
                        t.price as trade_price
                        
                    FROM model_predictions mp
                    JOIN tokens tk ON mp.token_id = tk.token_id
                    
                    -- Get price at prediction time (closest OHLCV record)
                    LEFT JOIN LATERAL (
                        SELECT close, time
                        FROM ohlcv 
                        WHERE token_id = mp.token_id 
                          AND time <= mp.prediction_time
                          AND resolution = '1H'
                        ORDER BY time DESC 
                        LIMIT 1
                    ) o1 ON true
                    
                    -- Get price 1 hour after prediction
                    LEFT JOIN LATERAL (
                        SELECT close, time
                        FROM ohlcv 
                        WHERE token_id = mp.token_id 
                          AND time >= mp.prediction_time + INTERVAL '50 minutes'
                          AND time <= mp.prediction_time + INTERVAL '70 minutes'
                          AND resolution = '1H'
                        ORDER BY ABS(EXTRACT(EPOCH FROM (time - (mp.prediction_time + INTERVAL '1 hour'))))
                        LIMIT 1
                    ) o2 ON true
                    
                    -- Check for executed trades
                    LEFT JOIN trades t ON (
                        t.token_id = mp.token_id 
                        AND t.cycle_timestamp BETWEEN mp.prediction_time - INTERVAL '10 minutes' 
                                                    AND mp.prediction_time + INTERVAL '10 minutes'
                        AND ((mp.prediction_action = 'buy' AND t.trade_type = 'buy') 
                             OR (mp.prediction_action = 'sell' AND t.trade_type = 'sell'))
                    )
                    
                    WHERE mp.prediction_time >= NOW() - INTERVAL '%s days'
                      AND mp.prediction_action IN ('buy', 'sell', 'hold')
                      %s
                )
                SELECT *
                FROM price_outcomes
                WHERE actual_change_pct IS NOT NULL
                ORDER BY prediction_time DESC
            """
            
            # Add symbol filter if specified
            symbol_filter = f"AND tk.symbol = '{symbol}'" if symbol else ""
            final_query = query % (days_back, symbol_filter)
            
            async with self.db_manager.pg_pool.acquire() as conn:
                rows = await conn.fetch(final_query)
            
            if not rows:
                logger.warning("No prediction data found")
                return pd.DataFrame()
            
            # Convert to DataFrame
            df = pd.DataFrame([dict(row) for row in rows])
            df['prediction_time'] = pd.to_datetime(df['prediction_time'])
            
            # Calculate prediction accuracy
            df['direction_correct'] = (
                ((df['predicted_change_pct'] > 0) & (df['actual_change_pct'] > 0)) |
                ((df['predicted_change_pct'] < 0) & (df['actual_change_pct'] < 0))
            )
            
            # Calculate magnitude accuracy
            df['magnitude_error'] = abs(df['predicted_change_pct'] - df['actual_change_pct'])
            
            # Determine if trade would have been profitable
            df['would_be_profitable'] = (
                ((df['prediction_action'] == 'buy') & (df['actual_change_pct'] > 0)) |
                ((df['prediction_action'] == 'sell') & (df['actual_change_pct'] < 0))
            )
            
            # Calculate potential profit/loss
            df['potential_return'] = np.where(
                df['prediction_action'] == 'buy',
                df['actual_change_pct'],
                -df['actual_change_pct']  # For sells, profit when price goes down
            )
            
            self.predictions_df = df
            logger.info(f"Loaded {len(df)} predictions for analysis")
            return df
            
        except Exception as e:
            logger.error(f"Failed to load prediction data: {e}")
            return pd.DataFrame()
    
    def analyze_threshold_performance(self, threshold_range: Tuple[float, float] = (0.002, 0.05)) -> Dict:
        """Analyze performance across different threshold values"""
        if self.predictions_df is None or len(self.predictions_df) == 0:
            return {}
        
        df = self.predictions_df.copy()
        
        # Test different threshold values
        thresholds = np.arange(threshold_range[0], threshold_range[1], 0.001)
        results = []
        
        for threshold in thresholds:
            # Simulate trades with this threshold
            trades = df[abs(df['predicted_change_pct']) >= threshold * 100].copy()
            
            if len(trades) == 0:
                continue
            
            # Calculate metrics
            total_trades = len(trades)
            profitable_trades = len(trades[trades['would_be_profitable']])
            win_rate = profitable_trades / total_trades if total_trades > 0 else 0
            
            # Calculate total return
            total_return = trades['potential_return'].sum()
            avg_return = trades['potential_return'].mean()
            
            # Calculate opportunity cost (missed profitable trades)
            missed_trades = df[
                (abs(df['predicted_change_pct']) < threshold * 100) & 
                (df['would_be_profitable']) &
                (abs(df['actual_change_pct']) >= 0.5)  # Only count significant moves
            ]
            missed_profit = missed_trades['potential_return'].sum() if len(missed_trades) > 0 else 0
            
            results.append({
                'threshold': threshold,
                'total_trades': total_trades,
                'win_rate': win_rate,
                'total_return': total_return,
                'avg_return': avg_return,
                'missed_trades': len(missed_trades),
                'missed_profit': missed_profit,
                'net_return': total_return - abs(missed_profit) * 0.5  # Penalty for missed opportunities
            })
        
        results_df = pd.DataFrame(results)
        
        # Find optimal threshold
        if len(results_df) > 0:
            optimal_idx = results_df['net_return'].idxmax()
            optimal_threshold = results_df.loc[optimal_idx, 'threshold']
            
            self.analysis_results['threshold_analysis'] = {
                'results_df': results_df,
                'optimal_threshold': optimal_threshold,
                'optimal_metrics': results_df.loc[optimal_idx].to_dict()
            }
        
        return self.analysis_results.get('threshold_analysis', {})
    
    def analyze_current_adaptive_strategy(self) -> Dict:
        """Analyze how current adaptive strategy is performing"""
        if self.predictions_df is None:
            return {}
        
        df = self.predictions_df.copy()
        
        # Group by symbol and time periods
        analysis = {}
        
        for symbol in df['symbol'].unique():
            symbol_df = df[df['symbol'] == symbol].copy()
            
            # Calculate current performance
            executed_trades = symbol_df[symbol_df['execution_status'] == 'confirmed']
            missed_opportunities = symbol_df[
                (symbol_df['execution_status'] == 'no_trade') & 
                (symbol_df['would_be_profitable']) &
                (abs(symbol_df['actual_change_pct']) >= 1.0)  # Significant moves
            ]
            
            analysis[symbol] = {
                'total_predictions': len(symbol_df),
                'executed_trades': len(executed_trades),
                'execution_rate': len(executed_trades) / len(symbol_df) if len(symbol_df) > 0 else 0,
                'missed_opportunities': len(missed_opportunities),
                'missed_profit': missed_opportunities['potential_return'].sum() if len(missed_opportunities) > 0 else 0,
                'avg_predicted_magnitude': abs(symbol_df['predicted_change_pct']).mean(),
                'avg_actual_magnitude': abs(symbol_df['actual_change_pct']).mean(),
                'direction_accuracy': symbol_df['direction_correct'].mean(),
                'executed_win_rate': executed_trades['would_be_profitable'].mean() if len(executed_trades) > 0 else 0
            }
        
        self.analysis_results['adaptive_analysis'] = analysis
        return analysis
    
    def analyze_hold_predictions(self) -> Dict:
        """Analyze 'hold' predictions to identify missed opportunities"""
        if self.predictions_df is None:
            return {}
        
        df = self.predictions_df.copy()
        hold_df = df[df['prediction_action'] == 'hold'].copy()
        
        if len(hold_df) == 0:
            return {}
        
        # Categorize hold predictions by what actually happened
        analysis = {
            'total_holds': len(hold_df),
            'holds_with_significant_moves': 0,
            'missed_buy_opportunities': 0,
            'missed_sell_opportunities': 0,
            'correctly_held': 0,
            'avg_predicted_magnitude': abs(hold_df['predicted_change_pct']).mean(),
            'avg_actual_magnitude': abs(hold_df['actual_change_pct']).mean(),
        }
        
        # Define significant move threshold (e.g., >1% actual price change)
        significant_threshold = 1.0
        
        for _, row in hold_df.iterrows():
            actual_change = row['actual_change_pct']
            predicted_change = row['predicted_change_pct']
            
            if abs(actual_change) >= significant_threshold:
                analysis['holds_with_significant_moves'] += 1
                
                # Check if we missed a buy opportunity
                if actual_change > 0 and predicted_change > 0:
                    analysis['missed_buy_opportunities'] += 1
                
                # Check if we missed a sell opportunity  
                elif actual_change < 0 and predicted_change < 0:
                    analysis['missed_sell_opportunities'] += 1
            else:
                # Small move, holding was probably correct
                analysis['correctly_held'] += 1
        
        # Calculate potential missed profit
        missed_buys = hold_df[
            (hold_df['actual_change_pct'] > significant_threshold) & 
            (hold_df['predicted_change_pct'] > 0)
        ]
        missed_sells = hold_df[
            (hold_df['actual_change_pct'] < -significant_threshold) & 
            (hold_df['predicted_change_pct'] < 0)
        ]
        
        analysis['missed_buy_profit'] = missed_buys['actual_change_pct'].sum()
        analysis['missed_sell_profit'] = abs(missed_sells['actual_change_pct']).sum()
        analysis['total_missed_profit'] = analysis['missed_buy_profit'] + analysis['missed_sell_profit']
        
        # Breakdown by predicted magnitude ranges
        magnitude_ranges = [
            (0, 0.5, 'Very Low'),
            (0.5, 1.0, 'Low'), 
            (1.0, 2.0, 'Medium'),
            (2.0, 5.0, 'High'),
            (5.0, float('inf'), 'Very High')
        ]
        
        analysis['magnitude_breakdown'] = {}
        for min_mag, max_mag, label in magnitude_ranges:
            range_df = hold_df[
                (abs(hold_df['predicted_change_pct']) >= min_mag) & 
                (abs(hold_df['predicted_change_pct']) < max_mag)
            ]
            
            if len(range_df) > 0:
                profitable_in_range = range_df[
                    ((range_df['predicted_change_pct'] > 0) & (range_df['actual_change_pct'] > significant_threshold)) |
                    ((range_df['predicted_change_pct'] < 0) & (range_df['actual_change_pct'] < -significant_threshold))
                ]
                
                analysis['magnitude_breakdown'][label] = {
                    'total': len(range_df),
                    'missed_opportunities': len(profitable_in_range),
                    'missed_profit': profitable_in_range['actual_change_pct'].abs().sum() if len(profitable_in_range) > 0 else 0,
                    'avg_predicted_mag': abs(range_df['predicted_change_pct']).mean(),
                    'avg_actual_mag': abs(range_df['actual_change_pct']).mean()
                }
        
        self.analysis_results['hold_analysis'] = analysis
        return analysis
    
    def suggest_threshold_adjustments(self) -> Dict:
        """Suggest threshold adjustments based on analysis"""
        suggestions = {}
        
        if 'threshold_analysis' in self.analysis_results:
            optimal = self.analysis_results['threshold_analysis']['optimal_threshold']
            suggestions['optimal_buy_threshold'] = optimal
            suggestions['optimal_sell_threshold'] = optimal * 1.2  # Slightly higher for sells
        
        if 'adaptive_analysis' in self.analysis_results:
            for symbol, metrics in self.analysis_results['adaptive_analysis'].items():
                if metrics['missed_opportunities'] > metrics['executed_trades']:
                    suggestions[f'{symbol}_recommendation'] = 'LOWER_THRESHOLDS'
                    suggestions[f'{symbol}_reason'] = f"Missing {metrics['missed_opportunities']} opportunities vs {metrics['executed_trades']} trades"
                elif metrics['executed_win_rate'] < 0.4:
                    suggestions[f'{symbol}_recommendation'] = 'RAISE_THRESHOLDS'
                    suggestions[f'{symbol}_reason'] = f"Low win rate: {metrics['executed_win_rate']:.2%}"
                else:
                    suggestions[f'{symbol}_recommendation'] = 'MAINTAIN'
        
        self.analysis_results['suggestions'] = suggestions
        return suggestions
    
    def plot_analysis(self, output_dir: str = "plots/prediction_analysis"):
        """Create visualization plots"""
        os.makedirs(output_dir, exist_ok=True)
        
        if self.predictions_df is None or len(self.predictions_df) == 0:
            logger.warning("No data to plot")
            return
        
        df = self.predictions_df
        
        # 1. Threshold Performance Plot
        if 'threshold_analysis' in self.analysis_results:
            results_df = self.analysis_results['threshold_analysis']['results_df']
            
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
            
            # Win rate vs threshold
            ax1.plot(results_df['threshold'] * 100, results_df['win_rate'] * 100)
            ax1.set_xlabel('Threshold (%)')
            ax1.set_ylabel('Win Rate (%)')
            ax1.set_title('Win Rate vs Threshold')
            ax1.grid(True)
            
            # Total return vs threshold
            ax2.plot(results_df['threshold'] * 100, results_df['total_return'])
            ax2.set_xlabel('Threshold (%)')
            ax2.set_ylabel('Total Return (%)')
            ax2.set_title('Total Return vs Threshold')
            ax2.grid(True)
            
            # Number of trades vs threshold
            ax3.plot(results_df['threshold'] * 100, results_df['total_trades'])
            ax3.set_xlabel('Threshold (%)')
            ax3.set_ylabel('Number of Trades')
            ax3.set_title('Trade Frequency vs Threshold')
            ax3.grid(True)
            
            # Net return (including opportunity cost)
            ax4.plot(results_df['threshold'] * 100, results_df['net_return'])
            ax4.set_xlabel('Threshold (%)')
            ax4.set_ylabel('Net Return (%)')
            ax4.set_title('Net Return vs Threshold (with Opportunity Cost)')
            ax4.grid(True)
            
            # Mark optimal threshold
            optimal_threshold = self.analysis_results['threshold_analysis']['optimal_threshold']
            for ax in [ax1, ax2, ax3, ax4]:
                ax.axvline(optimal_threshold * 100, color='red', linestyle='--', alpha=0.7, label=f'Optimal: {optimal_threshold*100:.1f}%')
                ax.legend()
            
            plt.tight_layout()
            plt.savefig(f"{output_dir}/threshold_optimization.png", dpi=300, bbox_inches='tight')
            plt.close()
        
        # 2. Prediction vs Actual Scatter Plot
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
        
        # All predictions
        ax1.scatter(df['predicted_change_pct'], df['actual_change_pct'], 
                   c=df['would_be_profitable'], alpha=0.6, cmap='RdYlGn')
        ax1.plot([-5, 5], [-5, 5], 'k--', alpha=0.5)
        ax1.set_xlabel('Predicted Change (%)')
        ax1.set_ylabel('Actual Change (%)')
        ax1.set_title('Predicted vs Actual Price Changes')
        ax1.grid(True)
        
        # Only executed trades
        executed = df[df['execution_status'] == 'confirmed']
        if len(executed) > 0:
            ax2.scatter(executed['predicted_change_pct'], executed['actual_change_pct'], 
                       c=executed['would_be_profitable'], alpha=0.8, cmap='RdYlGn')
            ax2.plot([-5, 5], [-5, 5], 'k--', alpha=0.5)
            ax2.set_xlabel('Predicted Change (%)')
            ax2.set_ylabel('Actual Change (%)')
            ax2.set_title('Executed Trades: Predicted vs Actual')
            ax2.grid(True)
        
        plt.tight_layout()
        plt.savefig(f"{output_dir}/prediction_accuracy.png", dpi=300, bbox_inches='tight')
        plt.close()
        
        # 3. Opportunity Cost Analysis
        missed = df[(df['execution_status'] == 'no_trade') & (df['would_be_profitable'])]
        
        if len(missed) > 0:
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
            
            # Missed opportunities by magnitude
            ax1.hist(abs(missed['predicted_change_pct']), bins=20, alpha=0.7, label='Missed Opportunities')
            ax1.hist(abs(executed['predicted_change_pct']), bins=20, alpha=0.7, label='Executed Trades')
            ax1.set_xlabel('Predicted Magnitude (%)')
            ax1.set_ylabel('Count')
            ax1.set_title('Missed vs Executed by Prediction Magnitude')
            ax1.legend()
            ax1.grid(True)
            
            # Missed profit over time
            missed_daily = missed.groupby(missed['prediction_time'].dt.date)['potential_return'].sum()
            ax2.plot(missed_daily.index, missed_daily.values, marker='o')
            ax2.set_xlabel('Date')
            ax2.set_ylabel('Missed Profit (%)')
            ax2.set_title('Daily Missed Profit Opportunities')
            ax2.tick_params(axis='x', rotation=45)
            ax2.grid(True)
            
            plt.tight_layout()
            plt.savefig(f"{output_dir}/opportunity_cost.png", dpi=300, bbox_inches='tight')
            plt.close()
        
        logger.info(f"Analysis plots saved to {output_dir}/")

async def main():
    parser = argparse.ArgumentParser(description='Analyze prediction performance and optimize thresholds')
    parser.add_argument('--days', type=int, default=7, help='Days of data to analyze')
    parser.add_argument('--symbol', type=str, help='Specific symbol to analyze (optional)')
    parser.add_argument('--plot', action='store_true', help='Generate plots')
    parser.add_argument('--output-dir', type=str, default='plots/prediction_analysis', help='Output directory for plots')
    
    args = parser.parse_args()
    
    try:
        # Initialize database connection
        db_manager = await get_db_manager()
        
        # Create analyzer
        analyzer = PredictionAnalyzer(db_manager)
        
        print("📊 Loading prediction data...")
        df = await analyzer.load_prediction_data(days_back=args.days, symbol=args.symbol)
        
        if len(df) == 0:
            print("❌ No prediction data found")
            return
        
        print(f"✅ Loaded {len(df)} predictions")
        print(f"📈 Symbols: {df['symbol'].unique()}")
        print(f"📅 Date range: {df['prediction_time'].min()} to {df['prediction_time'].max()}")
        print()
        
        # Analyze threshold performance
        print("🔍 Analyzing threshold performance...")
        threshold_analysis = analyzer.analyze_threshold_performance()
        
        if threshold_analysis:
            optimal = threshold_analysis['optimal_metrics']
            print(f"📊 Optimal Threshold Analysis:")
            print(f"   Optimal Threshold: {optimal['threshold']*100:.2f}%")
            print(f"   Win Rate: {optimal['win_rate']*100:.1f}%")
            print(f"   Total Return: {optimal['total_return']:.2f}%")
            print(f"   Trades: {optimal['total_trades']}")
            print(f"   Missed Opportunities: {optimal['missed_trades']}")
            print()
        
        # Analyze current adaptive strategy
        print("🤖 Analyzing current adaptive strategy...")
        adaptive_analysis = analyzer.analyze_current_adaptive_strategy()
        
        for symbol, metrics in adaptive_analysis.items():
            print(f"📈 {symbol}:")
            print(f"   Execution Rate: {metrics['execution_rate']*100:.1f}%")
            print(f"   Missed Opportunities: {metrics['missed_opportunities']}")
            print(f"   Missed Profit: {metrics['missed_profit']:.2f}%")
            print(f"   Direction Accuracy: {metrics['direction_accuracy']*100:.1f}%")
            print(f"   Executed Win Rate: {metrics['executed_win_rate']*100:.1f}%")
            print()
        
        # Analyze hold predictions
        print("🧐 Analyzing hold predictions...")
        hold_analysis = analyzer.analyze_hold_predictions()
        if hold_analysis:
            print(f"📊 Hold Prediction Analysis:")
            print(f"   Total Holds: {hold_analysis['total_holds']}")
            print(f"   Holds with Significant Moves: {hold_analysis['holds_with_significant_moves']}")
            print(f"   Missed Buy Opportunities: {hold_analysis['missed_buy_opportunities']}")
            print(f"   Missed Sell Opportunities: {hold_analysis['missed_sell_opportunities']}")
            print(f"   Correctly Held: {hold_analysis['correctly_held']}")
            print(f"   Total Missed Profit: {hold_analysis['total_missed_profit']:.2f}%")
            print()
            for label, details in hold_analysis['magnitude_breakdown'].items():
                print(f"   {label}:")
                print(f"     Total: {details['total']}")
                print(f"     Missed Opportunities: {details['missed_opportunities']}")
                print(f"     Missed Profit: {details['missed_profit']:.2f}%")
                print(f"     Avg Predicted Mag: {details['avg_predicted_mag']:.2f}%")
                print(f"     Avg Actual Mag: {details['avg_actual_mag']:.2f}%")
            print()

        # Get suggestions
        print("💡 Threshold Adjustment Suggestions:")
        suggestions = analyzer.suggest_threshold_adjustments()
        
        for key, value in suggestions.items():
            if key.endswith('_recommendation'):
                symbol = key.replace('_recommendation', '')
                reason = suggestions.get(f'{symbol}_reason', '')
                print(f"   {symbol}: {value} - {reason}")
            elif not key.endswith('_reason'):
                print(f"   {key}: {value}")
        
        # Generate plots if requested
        if args.plot:
            print(f"📊 Generating analysis plots...")
            analyzer.plot_analysis(args.output_dir)
            print(f"✅ Plots saved to {args.output_dir}/")
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 