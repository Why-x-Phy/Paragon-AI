#!/usr/bin/env python3
"""
Example: Running K-Fold validation on your tokens

This shows how k-fold can help identify if your model improvements are real
or just lucky on specific train/test splits.
"""

from src.model.kfold_trainer import train_with_kfold

# Popular tokens to test
TOKENS = {
    "FARTCOIN": "9mnCisApPx5iB3hLpYckxvnCfaFXnU4rZa9pUaUgpump",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
}

def compare_loss_functions():
    """Compare different loss functions using k-fold validation"""
    
    token = "FARTCOIN"
    address = TOKENS[token]
    
    print(f"\n🔬 Comparing loss functions for {token} using 5-fold validation")
    print("="*70)
    
    # Test different loss functions
    loss_functions = ["anti_collapse", "robust_directional", "variance_encouraging"]
    
    results = {}
    for loss_fn in loss_functions:
        print(f"\n\n🧪 Testing: {loss_fn}")
        print("-"*50)
        
        summary = train_with_kfold(
            symbol=token,
            token_address=address,
            days=30,
            n_splits=5,
            optimization_target=loss_fn
        )
        
        results[loss_fn] = {
            'direction_accuracy': summary['val_direction_accuracy_mean'],
            'accuracy_std': summary['val_direction_accuracy_std'],
            'collapse_rate': summary['predictions_collapsed_rate'],
            'r2_score': summary['r2_score_mean']
        }
    
    # Print comparison
    print("\n\n" + "="*70)
    print("📊 COMPARISON RESULTS")
    print("="*70)
    
    for loss_fn, metrics in results.items():
        print(f"\n{loss_fn}:")
        print(f"  Direction Accuracy: {metrics['direction_accuracy']:.2%} ± {metrics['accuracy_std']:.2%}")
        print(f"  Collapse Rate: {metrics['collapse_rate']:.0%}")
        print(f"  R² Score: {metrics['r2_score']:.4f}")
    
    # Find best
    best_loss = max(results.items(), key=lambda x: x[1]['direction_accuracy'])
    print(f"\n🏆 Best Loss Function: {best_loss[0]} with {best_loss[1]['direction_accuracy']:.2%} accuracy")


def test_single_token():
    """Test k-fold on a single token"""
    
    # You can run this to test any token
    results = train_with_kfold(
        symbol="FARTCOIN",
        token_address=TOKENS["FARTCOIN"],
        days=30,
        n_splits=5,  # Use 5 folds
        optimization_target="anti_collapse"
    )
    
    # Results include:
    # - Mean performance across all folds
    # - Standard deviation (consistency)
    # - Best model saved automatically
    # - Collapse detection rate


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        compare_loss_functions()
    else:
        test_single_token()
        print("\n💡 Tip: Run with 'compare' argument to test different loss functions") 