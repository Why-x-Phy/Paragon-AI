#!/usr/bin/env python3
"""
Visualize the symmetry improvement in the loss function
"""

import numpy as np
import matplotlib.pyplot as plt
import tensorflow as tf

def old_large_move_component(y_true, y_pred):
    """Old loss - only penalizes missing large DOWN moves"""
    # Large downward moves only
    large_down_moves = tf.cast(y_true < -0.03, tf.float32)
    correct_down_preds = large_down_moves * tf.cast(y_pred < 0, tf.float32)
    has_large_downs = tf.reduce_sum(large_down_moves)
    down_move_accuracy = tf.cond(
        has_large_downs > 0,
        lambda: tf.reduce_sum(correct_down_preds) / has_large_downs,
        lambda: tf.constant(1.0, dtype=tf.float32)
    )
    return 1.0 - down_move_accuracy

def new_large_move_component(y_true, y_pred):
    """New loss - penalizes missing large moves in BOTH directions"""
    # Large downward moves
    large_down_moves = tf.cast(y_true < -0.03, tf.float32)
    correct_down_preds = large_down_moves * tf.cast(y_pred < 0, tf.float32)
    has_large_downs = tf.reduce_sum(large_down_moves)
    down_move_accuracy = tf.cond(
        has_large_downs > 0,
        lambda: tf.reduce_sum(correct_down_preds) / has_large_downs,
        lambda: tf.constant(1.0, dtype=tf.float32)
    )
    
    # Large upward moves
    large_up_moves = tf.cast(y_true > 0.03, tf.float32)
    correct_up_preds = large_up_moves * tf.cast(y_pred > 0, tf.float32)
    has_large_ups = tf.reduce_sum(large_up_moves)
    up_move_accuracy = tf.cond(
        has_large_ups > 0,
        lambda: tf.reduce_sum(correct_up_preds) / has_large_ups,
        lambda: tf.constant(1.0, dtype=tf.float32)
    )
    
    return 1.0 - (down_move_accuracy + up_move_accuracy) / 2.0

def visualize_loss_symmetry():
    """Visualize how the loss function treats different scenarios"""
    
    # Test scenarios
    scenarios = [
        # (true_change, pred_change, description)
        (-0.05, -0.04, "Large DOWN: Correct"),
        (-0.05, 0.01, "Large DOWN: Missed"),
        (0.05, 0.04, "Large UP: Correct"),
        (0.05, -0.01, "Large UP: Missed"),
        (0.01, 0.01, "Small move: Correct"),
        (0.01, -0.01, "Small move: Wrong"),
    ]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Calculate losses for each scenario
    old_losses = []
    new_losses = []
    labels = []
    
    for true_val, pred_val, desc in scenarios:
        y_true = tf.constant([true_val], dtype=tf.float32)
        y_pred = tf.constant([pred_val], dtype=tf.float32)
        
        old_loss = old_large_move_component(y_true, y_pred).numpy()
        new_loss = new_large_move_component(y_true, y_pred).numpy()
        
        old_losses.append(old_loss)
        new_losses.append(new_loss)
        labels.append(desc)
    
    # Plot comparison
    x = np.arange(len(scenarios))
    width = 0.35
    
    bars1 = ax1.bar(x - width/2, old_losses, width, label='Old Loss', color='red', alpha=0.7)
    bars2 = ax1.bar(x + width/2, new_losses, width, label='New Loss', color='green', alpha=0.7)
    
    ax1.set_xlabel('Scenario')
    ax1.set_ylabel('Loss Value')
    ax1.set_title('Loss Function Comparison: Large Move Penalties')
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=45, ha='right')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Add value labels on bars
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax1.annotate(f'{height:.2f}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),  # 3 points vertical offset
                        textcoords="offset points",
                        ha='center', va='bottom',
                        fontsize=8)
    
    # Create heatmap showing loss surface
    true_range = np.linspace(-0.1, 0.1, 50)
    pred_range = np.linspace(-0.1, 0.1, 50)
    
    loss_surface = np.zeros((len(true_range), len(pred_range)))
    
    for i, true_val in enumerate(true_range):
        for j, pred_val in enumerate(pred_range):
            y_true = tf.constant([true_val], dtype=tf.float32)
            y_pred = tf.constant([pred_val], dtype=tf.float32)
            loss_surface[i, j] = new_large_move_component(y_true, y_pred).numpy()
    
    im = ax2.imshow(loss_surface, extent=[-0.1, 0.1, -0.1, 0.1], 
                    origin='lower', cmap='RdYlGn_r', aspect='auto')
    ax2.set_xlabel('Predicted Change')
    ax2.set_ylabel('True Change')
    ax2.set_title('New Loss Function Heat Map\n(Red = High Loss, Green = Low Loss)')
    
    # Add contour lines
    CS = ax2.contour(pred_range, true_range, loss_surface, levels=5, colors='black', alpha=0.3)
    ax2.clabel(CS, inline=True, fontsize=8)
    
    # Add diagonal line (perfect predictions)
    ax2.plot([-0.1, 0.1], [-0.1, 0.1], 'b--', alpha=0.5, label='Perfect Predictions')
    
    # Mark the ±3% thresholds
    ax2.axhline(y=0.03, color='orange', linestyle=':', alpha=0.7, label='±3% Threshold')
    ax2.axhline(y=-0.03, color='orange', linestyle=':', alpha=0.7)
    ax2.axvline(x=0.03, color='orange', linestyle=':', alpha=0.7)
    ax2.axvline(x=-0.03, color='orange', linestyle=':', alpha=0.7)
    
    ax2.legend(loc='upper right', fontsize=8)
    plt.colorbar(im, ax=ax2)
    
    plt.tight_layout()
    plt.savefig('calvin_1/plots/loss_symmetry_comparison.png', dpi=150, bbox_inches='tight')
    plt.show()
    
    # Print analysis
    print("\n📊 Loss Function Analysis")
    print("=" * 60)
    print("\n🔴 Old Loss Function Issues:")
    print("  - Only penalized missing large DOWN moves")
    print("  - Ignored large UP moves completely")
    print("  - Created asymmetric learning signal")
    
    print("\n🟢 New Loss Function Improvements:")
    print("  - Equally penalizes missing large moves in BOTH directions")
    print("  - Symmetric treatment of opportunities and risks")
    print("  - Balanced learning signal for the model")
    
    print("\n📈 Impact on Trading:")
    print("  - Model will learn to catch +5% rallies as well as -5% drops")
    print("  - More balanced predictions (less negative bias)")
    print("  - Better overall trading performance")


if __name__ == "__main__":
    # Create plots directory if it doesn't exist
    import os
    os.makedirs('calvin_1/plots', exist_ok=True)
    
    visualize_loss_symmetry() 