import os
import sys
import pandas as pd
import numpy as np
import optuna
from datetime import datetime

# Add project root to sys.path
# Ensure this path is correct relative to where the script is run
# If running from calvin_1/scripts/, project_root should be two levels up.
# If running from project root (calvin_ai/), project_root should be calvin_1
try:
    current_file_path = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_file_path, '..', '..')) # For calvin_1/scripts/
    if not os.path.exists(os.path.join(project_root, 'calvin_1')): # check if we are already in project_root
         project_root = os.path.abspath(os.path.join(current_file_path, '..')) # For calvin_ai/calvin_1/scripts if calvin_1 is not in parent
    
    # If the typical structures are not found, assume we might be running from calvin_ai/
    if not os.path.exists(os.path.join(project_root, 'src')): 
        project_root_alt = os.path.join(project_root, 'calvin_1')
        if os.path.exists(os.path.join(project_root_alt, 'src')):
            project_root = project_root_alt
        else: # Final fallback: assume script is run from calvin_ai
            project_root = os.getcwd()
            if not os.path.exists(os.path.join(project_root, 'calvin_1', 'src')):
                 # If calvin_1/src is still not found, it indicates a potential issue with path detection or execution context.
                 # For now, we will try to proceed by adding the current project_root to sys.path,
                 # but this might lead to import errors if the structure is unexpected.
                 pass


    # Add both project_root and project_root/calvin_1/src to sys.path
    # This covers cases where scripts might be in calvin_1/scripts or calvin_1/src/scripts
    # and ensures modules in src can be imported.
    sys.path.insert(0, project_root)
    src_path = os.path.join(project_root, 'src')
    if os.path.isdir(src_path) and src_path not in sys.path:
        sys.path.insert(0, src_path)
    
    # If running from calvin_ai, ensure calvin_1/src is in path
    calvin_1_src_path = os.path.join(os.getcwd(), 'calvin_1', 'src')
    if os.path.isdir(calvin_1_src_path) and calvin_1_src_path not in sys.path:
        sys.path.insert(0, calvin_1_src_path)

except Exception as e:
    print(f"Error setting up sys.path: {e}")
    # Fallback if path resolution fails, try adding common paths
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))


from src.data.data_processor import DataProcessor
from src.model.ml_model import MLModel
from src.model.profit_functions import simple_backtest_strategy # Assuming this is the correct path
from src.utils.logger import log_manager, log

logger = log

# --- Configuration ---
TOKEN_ADDRESS = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"  # Default to SOL
SYMBOL = "Fartcoin"
RESOLUTION = "1H" # Using 1H as per recent backtests
DAYS_FOR_DATA = 90  # Use a reasonable amount of data for optimization
SEQUENCE_LENGTH = 36 # Should match model training
PREDICTION_HORIZON = 1 # For 1-step ahead predictions as per strategy
MODEL_PATH = "models/Fartcoin_lstm_v1.0.0_20250615.h5"  # Set to a specific model path or leave as None to use latest
N_TRIALS = 500 # Reduced from 3000 since we only have 2 parameters to optimize

# TRADE RANGE OPTIMIZATION: Target a specific range of trades
MIN_TRADES_FOR_VALID_STRATEGY = 5  # Minimum trades required
MAX_TRADES_FOR_VALID_STRATEGY = 90  # Maximum trades desired
OPTIMAL_TRADE_RANGE = (30, 60)  # Ideal range for trade count (min, max)

# Penalty weights for trades outside the optimal range
TRADE_RANGE_PENALTY_WEIGHT = 0.3  # How much to penalize for being outside optimal range

# SIMPLIFIED: Two-parameter optimization for magnitude-based strategy
# - buy_threshold: percentage increase needed to trigger buy (0.5% to 8%)
# - sell_threshold: percentage decrease needed to trigger sell (1% to 10%)

# Single-objective optimization target: Total Return (absolute profit percentage)
# This will find the strategy parameters that maximize total profit

# Global cache for data and predictions to avoid reloading in each trial
DATA_CACHE = {}

def clear_data_cache():
    """Clear the global data cache to force fresh data loading."""
    global DATA_CACHE
    DATA_CACHE.clear()
    logger.info("Data cache cleared - will load fresh data")

def load_data_and_predictions():
    """Loads data and gets model predictions, caching the result."""
    if 'data' in DATA_CACHE:
        logger.info("Using cached data and predictions.")
        return DATA_CACHE['data']

    logger.info(f"Loading data for {SYMBOL} ({TOKEN_ADDRESS}), {DAYS_FOR_DATA} days, {RESOLUTION} resolution")
    data_processor = DataProcessor()
    
    # Use the EXACT same data processing as main.py
    df = data_processor.process_pipeline(
        TOKEN_ADDRESS,
        SYMBOL,
        RESOLUTION,
        DAYS_FOR_DATA,
        save_data=False,
        include_sentiment=True
    )

    if df.empty:
        logger.error("No data available for optimization.")
        raise ValueError("No data for optimization")

    logger.info(f"Data loaded. Shape: {df.shape}")

    # Load ML model - use exact same approach as main.py
    ml_model = MLModel()
    model_to_load = MODEL_PATH if MODEL_PATH else ml_model.get_latest_model_path()
    if not model_to_load:
        logger.error("No model found for predictions.")
        raise ValueError("No model found")
    
    logger.info(f"Loading model: {model_to_load}")
    ml_model.load(model_to_load)

    # Use EXACT same data preparation as main.py test_model()
    _, X_test, _, y_test = data_processor.prepare_ml_data(
        df.copy(),
        target_col='close',
        sequence_length=SEQUENCE_LENGTH,
        prediction_horizon=PREDICTION_HORIZON,
        test_size=0.99,  # Same as main.py
        include_feature_names=False
    )
    
    if X_test.shape[0] == 0:
        logger.error("No data samples generated for model prediction after prepare_ml_data.")
        raise ValueError("No data samples for prediction.")

    logger.info(f"Making predictions with model on {X_test.shape[0]} samples.")
    y_pred = ml_model.predict(X_test)
    
    # Use EXACT same inverse transform approach as main.py
    y_pred_orig = data_processor.inverse_transform_predictions(y_pred, data_processor.prices_at_sequence_end_test)
    
    # Get actual prices using the SAME approach as main.py
    original_indices = df.index[-(len(y_test)+PREDICTION_HORIZON-1):-(PREDICTION_HORIZON-1)] if PREDICTION_HORIZON > 1 else df.index[-len(y_test):]
    base_prices_for_y_test = df.loc[original_indices, 'close'].values
    target_pct_changes = data_processor.price_scaler.inverse_transform(y_test.reshape(-1, 1)).flatten()
    y_true_orig = base_prices_for_y_test * (1 + target_pct_changes)

    # CRITICAL FIX: Slice dataframe to match prediction length
    ohlcv_df_aligned = df.iloc[-len(y_pred_orig):].copy()

    logger.info(f"Aligned data for backtest: Prices shape {y_true_orig.shape}, Predictions shape {y_pred_orig.shape}, OHLCV_DF shape {ohlcv_df_aligned.shape}")

    DATA_CACHE['data'] = (ohlcv_df_aligned, y_true_orig.copy(), y_pred_orig.copy())
    return DATA_CACHE['data']


def objective(trial: optuna.Trial) -> float:
    """Objective function for Optuna to optimize. Returns total_return adjusted for trade count optimization."""
    try:
        ohlcv_df, prices, predictions = load_data_and_predictions()
    except ValueError as e:
        logger.error(f"Failed to load data/predictions for trial: {e}")
        return -100.0 # Penalize heavily if data loading fails

    # SIMPLIFIED: Only optimize buy and sell thresholds for magnitude-based strategy
    buy_threshold = trial.suggest_float("buy_threshold", 0.005, 0.08)  # 0.5% to 8%
    sell_threshold = trial.suggest_float("sell_threshold", 0.01, 0.10)   # 1% to 10%
    
    # Run the simplified backtest strategy
    try:
        results = simple_backtest_strategy(
            prices=prices,
            predictions=predictions,
            ohlcv_df=ohlcv_df.copy(), # Pass a copy to be safe
            include_detailed_trades=False, # We only need summary metrics
            verbosity=0,
            resolution=RESOLUTION,
            buy_threshold=buy_threshold,    # Buy when predicted increase >= this %
            sell_threshold=sell_threshold   # Sell when predicted decrease >= this %
        )
    except Exception as e:
        logger.error(f"Backtest failed for trial {trial.number} with params {trial.params}: {e}", exc_info=True)
        return -100.0 # Penalize heavily

    total_return = results.get('Total Return', -100.0) # Default to very low if not found
    total_trades = results.get('Total Trades', 0)

    # Check minimum and maximum trades requirements
    if total_trades < MIN_TRADES_FOR_VALID_STRATEGY:
        logger.info(f"Trial {trial.number} pruned due to insufficient trades ({total_trades}). Return: {total_return if total_return is not None else 'N/A'}")
        return -50.0 # Penalize for insufficient trades
    
    if total_trades > MAX_TRADES_FOR_VALID_STRATEGY:
        logger.info(f"Trial {trial.number} pruned due to excessive trades ({total_trades}). Return: {total_return if total_return is not None else 'N/A'}")
        return -30.0 # Penalize for too many trades (less severe than too few)

    # Handle invalid metrics
    if total_return is None or np.isnan(total_return) or np.isinf(total_return):
        total_return = -100.0

    if total_return == -100.0:
        logger.warning(f"Trial {trial.number} resulted in invalid metrics. Return: {total_return}, Trades: {total_trades}. Params: {trial.params}")

    # TRADE RANGE OPTIMIZATION: Apply bonus/penalty based on trade count
    trade_adjustment = 0.0
    optimal_min, optimal_max = OPTIMAL_TRADE_RANGE
    
    if optimal_min <= total_trades <= optimal_max:
        # Bonus for being in optimal range
        trade_adjustment = 2.0  # Small bonus for optimal trade count
        logger.info(f"Trial {trial.number}: OPTIMAL RANGE - Buy={buy_threshold:.3f}, Sell={sell_threshold:.3f}, Total Return={total_return:.2f}%, Trades={total_trades} ✓")
    else:
        # Penalty for being outside optimal range
        if total_trades < optimal_min:
            # Too few trades - penalty proportional to how far below optimal
            distance_penalty = (optimal_min - total_trades) * TRADE_RANGE_PENALTY_WEIGHT
            trade_adjustment = -distance_penalty
        else:
            # Too many trades - penalty proportional to how far above optimal
            distance_penalty = (total_trades - optimal_max) * TRADE_RANGE_PENALTY_WEIGHT
            trade_adjustment = -distance_penalty
        
        logger.info(f"Trial {trial.number}: Buy={buy_threshold:.3f}, Sell={sell_threshold:.3f}, Total Return={total_return:.2f}%, Trades={total_trades}, Adjustment={trade_adjustment:.2f}")

    # Return adjusted score (total return + trade range adjustment)
    adjusted_score = total_return + trade_adjustment
    return adjusted_score

def get_trial_results(trial_params: dict) -> dict:
    """Get backtest results for a specific set of trial parameters."""
    try:
        ohlcv_df, prices, predictions = load_data_and_predictions()
        
        # SIMPLIFIED: Only use buy_threshold and sell_threshold
        results = simple_backtest_strategy(
            prices=prices,
            predictions=predictions,
            ohlcv_df=ohlcv_df.copy(),
            include_detailed_trades=False,
            verbosity=0,
            resolution=RESOLUTION,
            buy_threshold=trial_params.get("buy_threshold", 0.02),
            sell_threshold=trial_params.get("sell_threshold", 0.03)
        )
        return results
    except Exception as e:
        logger.error(f"Failed to get trial results: {e}")
        return {}

def safe_format_percent(value, default='N/A'):
    """Safely format percentage values, handling 'N/A' strings"""
    if value == 'N/A' or value is None:
        return default
    try:
        return f"{float(value):.2f}%"
    except (ValueError, TypeError):
        return default

def safe_format_currency(value, default='N/A'):
    """Safely format currency values, handling 'N/A' strings"""
    if value == 'N/A' or value is None:
        return default
    try:
        return f"${float(value):.2f}"
    except (ValueError, TypeError):
        return default

def main():
    """Main function to run the optimization."""
    logger.info("Starting strategy optimization...")
    
    # Clear any cached data to ensure fresh data loading
    clear_data_cache()
    
    # Ensure log directory exists
    log_dir = os.path.join(project_root, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # Pre-load data and predictions to cache them
    try:
        logger.info("Pre-loading data and predictions...")
        load_data_and_predictions()
        logger.info("Data and predictions pre-loaded and cached.")
    except Exception as e:
        logger.error(f"Failed to pre-load data: {e}", exc_info=True)
        return

    # --- Optuna Study ---
    study_name = f"simple_strategy_opt_{SYMBOL}_{RESOLUTION}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    storage_path = f"sqlite:///{log_dir}/{study_name}.db" # Store study results in a DB
    
    # Sampler for more efficient search (e.g., TPE)
    sampler = optuna.samplers.TPESampler(seed=42) # Tree-structured Parzen Estimator
    pruner = optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=0, interval_steps=1)

    study = optuna.create_study(
        study_name=study_name,
        direction="maximize",    # Single-objective: maximize Total Return
        storage=storage_path,    # Persist study
        sampler=sampler,
        pruner=pruner,
        load_if_exists=True      # Resume if study already exists
    )

    try:
        study.optimize(objective, n_trials=N_TRIALS, timeout=7200) # Set a timeout (e.g., 2 hours)
    except KeyboardInterrupt:
        logger.info("Optimization interrupted by user.")
    except Exception as e:
        logger.error(f"An error occurred during optimization: {e}", exc_info=True)


    logger.info(f"Optimization finished. Number of trials: {len(study.trials)}")
    
    if not study.trials:
        logger.warning("No trials were completed. Cannot show best parameters.")
        return

    # --- Single-Objective Results ---
    # In single-objective optimization, there is one "best" trial
    best_trial = study.best_trial
    logger.info(f"Found the best trial:")
    
    # Get complete results for the best trial
    best_results = get_trial_results(best_trial.params)
    total_trades = best_results.get('Total Trades', 'N/A')
    win_rate = best_results.get('Win Rate', 'N/A')
    max_drawdown = best_results.get('Max Drawdown', 'N/A')
    final_value = best_results.get('Final Portfolio Value', 'N/A')
    sharpe_ratio = best_results.get('Sharpe Ratio', 'N/A')
    
    # Calculate trade range performance
    optimal_min, optimal_max = OPTIMAL_TRADE_RANGE
    trade_range_status = "OPTIMAL" if optimal_min <= total_trades <= optimal_max else "OUTSIDE RANGE"
    
    logger.info(f"  Best Trial (Trade Range Optimized):")
    logger.info(f"    Adjusted Score: {best_trial.value:.2f}% (includes trade range bonus/penalty)")
    logger.info(f"    Total Return: {best_results.get('Total Return', 'N/A'):.2f}%")
    logger.info(f"    Trade Count: {total_trades} ({trade_range_status}) - Target: {optimal_min}-{optimal_max}")
    logger.info(f"    Sharpe Ratio: {sharpe_ratio:.2f}" if sharpe_ratio != 'N/A' else "    Sharpe Ratio: N/A")
    logger.info(f"    Win Rate: {safe_format_percent(win_rate)}")
    logger.info(f"    Max Drawdown: {safe_format_percent(max_drawdown)}")
    logger.info(f"    Final Portfolio Value: {safe_format_currency(final_value)}")
    logger.info(f"    Parameters: {best_trial.params}")
    
    # Save best results to file
    best_results_file = os.path.join(log_dir, f"{study_name}_best_results.txt")
    with open(best_results_file, 'w') as f:
        f.write("Best Results from Trade Range Optimized Strategy:\n")
        f.write("=" * 80 + "\n\n")
        
        f.write("OPTIMIZATION SETTINGS:\n")
        f.write(f"  Target Trade Range: {optimal_min}-{optimal_max} trades\n")
        f.write(f"  Trade Range Penalty Weight: {TRADE_RANGE_PENALTY_WEIGHT}\n")
        f.write(f"  Min Valid Trades: {MIN_TRADES_FOR_VALID_STRATEGY}\n")
        f.write(f"  Max Valid Trades: {MAX_TRADES_FOR_VALID_STRATEGY}\n\n")
        
        f.write("BEST TRIAL RESULTS:\n")
        f.write(f"  Adjusted Score: {best_trial.value:.2f}% (includes trade range bonus/penalty)\n")
        f.write(f"  Total Return: {best_results.get('Total Return', 'N/A'):.2f}%\n")
        f.write(f"  Trade Count: {total_trades} ({trade_range_status})\n")
        f.write(f"  Sharpe Ratio: {sharpe_ratio:.2f}\n" if sharpe_ratio != 'N/A' else "  Sharpe Ratio: N/A\n")
        f.write(f"  Win Rate: {safe_format_percent(win_rate)}\n")
        f.write(f"  Max Drawdown: {safe_format_percent(max_drawdown)}\n")
        f.write(f"  Final Portfolio Value: {safe_format_currency(final_value)}\n")
        f.write("  Parameters:\n")
        for key, value in best_trial.params.items():
            f.write(f"    {key}: {value}\n")
    
    logger.info(f"Best results saved to {best_results_file}")

    # You can also plot optimization history, parameter importance, etc.
    try:
        # Optimization history
        fig_history = optuna.visualization.plot_optimization_history(study)
        fig_history.write_image(os.path.join(log_dir, f"{study_name}_history.png"))
        
        # Parameter importance
        fig_importance = optuna.visualization.plot_param_importances(study)
        fig_importance.write_image(os.path.join(log_dir, f"{study_name}_importance.png"))
        
        # Parallel coordinates plot
        fig_parallel = optuna.visualization.plot_parallel_coordinate(study)
        fig_parallel.write_image(os.path.join(log_dir, f"{study_name}_parallel_coords.png"))
        
        logger.info(f"Single-objective optimization plots saved in {log_dir}")
        logger.info("Generated plots:")
        logger.info("  - Optimization history")
        logger.info("  - Parameter importance")
        logger.info("  - Parallel coordinates plot")
        
    except Exception as e:
        logger.warning(f"Could not generate Optuna plots: {e}. You might need to install plotly and kaleido.")
        logger.warning("Try: pip install plotly kaleido")


if __name__ == "__main__":
    main() 