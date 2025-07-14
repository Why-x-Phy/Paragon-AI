#!/usr/bin/env python3
"""
Train the Ultimate Model

This script runs the complete ultimate training system to produce 
the best possible models, regardless of training time.
"""

import os
import sys
from pathlib import Path

# Add current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Load environment variables
from dotenv import load_dotenv
project_root = Path(__file__).resolve().parent.parent
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from src.model.ultimate_training_system import UltimateTrainingSystem

# Popular tokens
TOKENS = {
    "FARTCOIN": "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "MNDE": "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey",
    "$WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    "MEW": "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5",
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    "ORCA": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",
    "RENDER": "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof",
    "RAY": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
}

def train_ultimate_model(symbol: str, token_address: str, days: int = 60):
    """
    Train the ultimate model for a token
    
    Args:
        symbol: Token symbol
        token_address: Token contract address
        days: Days of historical data to use
    """
    print(f"\n{'='*80}")
    print(f"🚀 ULTIMATE MODEL TRAINING - {symbol}")
    print(f"{'='*80}")
    print(f"\n⚠️  WARNING: This will take significant time but produce the best possible model")
    print(f"💪 No shortcuts, no compromises - maximum performance only\n")
    
    # Initialize training system
    trainer = UltimateTrainingSystem()
    
    # Run ultimate training
    results = trainer.train_ultimate_model(
        token_address=token_address,
        symbol=symbol,
        days=days,
        test_days=7  # Reserve last week for testing
    )
    
    # Print summary
    print(f"\n{'='*80}")
    print(f"📊 TRAINING COMPLETE - SUMMARY")
    print(f"{'='*80}")
    print(f"\n🏆 Best Model: {results['best_model']}")
    print(f"📈 Best Direction Accuracy: {results['summary']['best_direction_accuracy']:.4f}")
    print(f"💰 Best Sharpe Ratio: {results['summary']['best_sharpe_ratio']:.4f}")
    print(f"🤖 Models Trained: {results['summary']['models_trained']}")
    print(f"🤝 Used Ensemble: {results['summary']['used_ensemble']}")
    
    return results


def train_multiple_tokens(tokens: list = None):
    """Train ultimate models for multiple tokens"""
    
    if tokens is None:
        # Default to top performers
        tokens = ["FARTCOIN", "BONK", "JUP"]
    
    all_results = {}
    
    for symbol in tokens:
        if symbol not in TOKENS:
            print(f"\n⚠️  Unknown token: {symbol}")
            continue
            
        try:
            results = train_ultimate_model(
                symbol=symbol,
                token_address=TOKENS[symbol],
                days=60
            )
            all_results[symbol] = results
            
        except Exception as e:
            print(f"\n❌ Error training {symbol}: {e}")
            continue
    
    # Print comparison
    print(f"\n{'='*80}")
    print(f"📊 MULTI-TOKEN COMPARISON")
    print(f"{'='*80}")
    
    for symbol, results in all_results.items():
        print(f"\n{symbol}:")
        print(f"  Direction Accuracy: {results['summary']['best_direction_accuracy']:.4f}")
        print(f"  Sharpe Ratio: {results['summary']['best_sharpe_ratio']:.4f}")
    
    # Find overall best
    if all_results:
        best_token = max(all_results.items(), 
                        key=lambda x: x[1]['summary']['best_direction_accuracy'])
        print(f"\n🏆 Overall Best: {best_token[0]} with {best_token[1]['summary']['best_direction_accuracy']:.4f} accuracy")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Train the ultimate model')
    parser.add_argument('--token', type=str, help='Single token symbol to train')
    parser.add_argument('--all', action='store_true', help='Train all popular tokens')
    parser.add_argument('--days', type=int, default=60, help='Days of historical data')
    
    args = parser.parse_args()
    
    if args.token:
        if args.token in TOKENS:
            train_ultimate_model(
                symbol=args.token,
                token_address=TOKENS[args.token],
                days=args.days
            )
        else:
            print(f"❌ Unknown token: {args.token}")
            print(f"Available tokens: {list(TOKENS.keys())}")
    
    elif args.all:
        train_multiple_tokens(list(TOKENS.keys()))
    
    else:
        # Default: train top 3
        print("💡 Training top 3 tokens. Use --token SYMBOL or --all for other options")
        train_multiple_tokens(["FARTCOIN", "BONK", "JUP"]) 