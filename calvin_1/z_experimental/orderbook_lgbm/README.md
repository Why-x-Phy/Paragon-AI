# Orderbook LightGBM Trading Model

A minimal LightGBM-based crypto trading model that predicts next-candle price movements using orderbook microstructure features.

## 🎯 Overview

This system builds and trains a LightGBM regression model to predict the next candle's percentage price change using orderbook-derived features. The model focuses on minimal, interpretable features derived from top-of-book data.

### Key Features
- **Minimal Feature Set**: Starts with 5-12 core orderbook features (mid price, spread, imbalance, etc.)
- **Time-Ordered Training**: Strict time-based train/validation splits to prevent data leakage
- **Database Integration**: Reads from existing TimescaleDB database with orderbook and candle data
- **End-to-End Pipeline**: CLI scripts for data preparation, training, and evaluation

## 📊 Data Sources

The system uses data from the Calvin AI trading database:

- **Candles**: `ohlcv` table with 1-minute OHLCV data
- **Orderbook**: `tob_1s` materialized view for top-of-book data (best bid/ask every second)
- **Microstructure**: `lbu_1m` materialized view for detailed orderbook metrics per minute

## 🚀 Quick Start

### Prerequisites

1. **Database**: Running TimescaleDB with orderbook and candle data
2. **Environment**: Python environment with required packages
3. **Data**: Historical orderbook and price data in the database

### Installation

```bash
# Navigate to the orderbook_lgbm directory
cd calvin_1/z_experimental/orderbook_lgbm/

# Install dependencies (add to your requirements.txt if needed)
pip install lightgbm pandas numpy scikit-learn python-dotenv psycopg2-binary
```

### Environment Setup

Ensure your `.env` file contains database connection settings:

```env
# Database connection
DB_HOST=localhost
DB_PORT=5433
DB_NAME=calvin_trading_dev
DB_USER=calvin_dev
DB_PASSWORD=calvin_dev_password

# Or for Docker environments
DATABASE_URL=postgresql://calvin_dev:calvin_dev_password@localhost:5433/calvin_trading_dev
```

## 📈 Usage

### Step 1: Build Features

Extract features and target from raw database data:

```bash
python -m orderbook_lgbm.scripts.build_features \
    --symbol SOL \
    --timeframe 1m \
    --start 2024-01-01 \
    --end 2024-12-01 \
    --levels 1
```

**Parameters:**
- `--symbol`: Token symbol (e.g., SOL, BTC, ETH)
- `--timeframe`: Candle timeframe (1m, 5m, 1h)
- `--start/--end`: Date range (ISO format)
- `--levels`: Orderbook levels (1 for basic, 5 for extended)

**Output:**
- `data_cache/features.parquet`: Feature matrix
- `data_cache/target.parquet`: Target variable (next candle % change)
- `data_cache/features_metadata.json`: Dataset metadata

### Step 2: Train Model

Train LightGBM model with time-based split:

```bash
python -m orderbook_lgbm.scripts.train_lgbm \
    --features-path data_cache/features.parquet \
    --target-path data_cache/target.parquet \
    --train-ratio 0.8 \
    --learning-rate 0.05 \
    --num-leaves 64 \
    --early-stopping-rounds 100
```

**Key Parameters:**
- `--train-ratio`: Fraction of data for training (default: 0.8)
- `--learning-rate`: Boosting learning rate (default: 0.05)
- `--num-leaves`: Maximum leaves per tree (default: 64)
- `--early-stopping-rounds`: Stop if no improvement (default: 100)

**Output:**
- `models/lgbm_model.txt`: Trained LightGBM model
- `models/meta.json`: Model metadata and parameters
- `models/feature_importance.csv`: Feature importance rankings

### Step 3: Evaluate Model

Evaluate trained model on test data:

```bash
python -m orderbook_lgbm.scripts.evaluate \
    --features-path data_cache/features.parquet \
    --target-path data_cache/target.parquet \
    --model-path models/lgbm_model.txt
```

**Output:**
- `data_cache/predictions.csv`: Predictions vs actual values
- `data_cache/evaluation_summary.json`: Comprehensive metrics
- `data_cache/error_analysis.json`: Error distribution analysis
- `data_cache/hourly_performance.csv`: Performance by hour of day

## 📊 Features

### Core Features (Level 1 Orderbook)

| Feature | Description | Calculation |
|---------|-------------|-------------|
| `mid_price` | Orderbook midpoint | `(best_bid + best_ask) / 2` |
| `spread` | Bid-ask spread | `best_ask - best_bid` |
| `rel_spread` | Relative spread | `spread / mid_price` |
| `depth_imbalance` | Buy/sell depth imbalance | `(bid_size - ask_size) / (bid_size + ask_size + ε)` |

### Extended Features (Optional)

| Feature | Description | Source |
|---------|-------------|--------|
| `mid_ret_1` | 1-period mid price return | `mid_price.pct_change()` |
| `lb_imbalance` | Microstructure imbalance | `lbu_1m` table |
| `lb_spread_bps` | Spread in basis points | `lbu_1m` table |
| `lb_buy_vol` | Buy-side volume | `lbu_1m` table |
| `lb_sell_vol` | Sell-side volume | `lbu_1m` table |

## 🎯 Target Variable

**Next Candle Return**: Percentage price change of the next candle

```
y_t = (close_{t+1} - close_t) / close_t
```

- **Horizon**: One-step ahead (next candle)
- **Alignment**: Features at time t predict return from t to t+1
- **No Leakage**: Strict time-ordered alignment prevents future data leakage

## 📈 Model Architecture

### LightGBM Regressor
- **Objective**: `regression`
- **Metric**: `rmse` (with early stopping)
- **Conservative Defaults**: Suitable for financial time series

### Time-Based Cross Validation
- **Split**: Time-ordered train/validation (no shuffling)
- **Ratio**: Configurable train ratio (default: 80/20)
- **Prevention**: No future data leakage in validation

## 🔍 Evaluation Metrics

### Regression Metrics
- **RMSE**: Root Mean Squared Error
- **MAE**: Mean Absolute Error
- **R²**: Coefficient of determination
- **MAPE**: Mean Absolute Percentage Error

### Trading-Specific Metrics
- **Directional Accuracy**: % correct sign predictions
- **Prediction Sharpness**: Signal strength consistency
- **Error Distribution**: Quantile analysis of prediction errors

### Analysis Outputs
- **Predictions CSV**: Full predictions vs actuals with timestamps
- **Hourly Performance**: Model performance by hour of day
- **Error Analysis**: Detailed error distribution statistics
- **Feature Importance**: Gain-based feature rankings

## 🗂️ Project Structure

```
orderbook_lgbm/
├── README.md                 # This file
├── config.py                 # Database and model configuration
├── data_loader.py            # Database query and data loading
├── features.py               # Feature engineering and target creation
├── trainer.py                # LightGBM training with time-based splits
├── eval.py                   # Model evaluation and metrics
├── utils.py                  # Helper functions for time/data handling
├── scripts/
│   ├── build_features.py     # CLI: Extract features from database
│   ├── train_lgbm.py         # CLI: Train LightGBM model
│   └── evaluate.py           # CLI: Evaluate trained model
├── models/                   # Saved model artifacts
├── data_cache/               # Cached features and predictions
└── __pycache__/             # Python bytecode (ignored)
```

## 🔧 Configuration

### Database Schema Mapping

The system adapts to your database schema. Key mappings in `config.py`:

```python
# Table/column names (adapt to your schema)
candles_table = 'ohlcv'
tokens_table = 'tokens'
tob_table = 'tob_1s'          # Top-of-book every second
lbu_table = 'lbu_1m'          # Orderbook microstructure per minute

# Column mappings
time_col_candles = 'time'
token_id_col = 'token_id'
symbol_col = 'symbol'
close_col = 'close'
best_bid_col = 'best_bid'
best_ask_col = 'best_ask'
```

### Model Hyperparameters

Default LightGBM parameters (conservative financial settings):

```python
model_config = {
    'learning_rate': 0.05,
    'num_leaves': 64,
    'feature_fraction': 0.9,
    'bagging_fraction': 0.8,
    'min_data_in_leaf': 50,
    'n_estimators': 2000,
    'early_stopping_rounds': 100
}
```

## 🚨 Important Notes

### Data Leakage Prevention
- **Strict Time Ordering**: All splits maintain chronological order
- **No Future Data**: Features only use data up to prediction time
- **Alignment**: Orderbook snapshots forward-filled to candle times with gap limits

### Database Requirements
- **TimescaleDB**: Hypertables for efficient time-series queries
- **Materialized Views**: `tob_1s` and `lbu_1m` must exist
- **Token Mapping**: `tokens` table with symbol-to-ID mapping

### Performance Considerations
- **Memory**: Large datasets may require chunked processing
- **Query Optimization**: Database indexes on time and symbol columns
- **Caching**: Parquet files cached for repeated experiments

## 🔄 Extending the Model

### Adding Features
1. **Modify `features.py`**: Add new feature calculations
2. **Update `FeatureConfig`**: Add column mappings if needed
3. **Test Alignment**: Ensure no data leakage in feature creation

### Alternative Targets
- **Classification**: Predict direction (up/down) instead of magnitude
- **Multi-horizon**: Predict returns at different timeframes
- **Regime-aware**: Different models for different market conditions

### Cross Validation
- **Time Series Split**: Multiple train/test periods
- **Rolling Window**: Fixed training window with rolling predictions
- **Walk-forward**: Simulate real trading with expanding window

## 🐛 Troubleshooting

### Common Issues

**"No data found"**
- Check database connectivity and table names
- Verify date range contains data
- Ensure symbol exists in tokens table

**"NaN values in features"**
- Check orderbook data availability
- Verify forward-fill gap limits
- Inspect raw data for missing values

**"Poor model performance"**
- Check for data leakage in feature alignment
- Verify time-based splits (no shuffling)
- Try different hyperparameters or feature sets

**"Memory errors"**
- Reduce date range or use chunked processing
- Clear data_cache between runs
- Use smaller batch sizes in data loading

### Debug Mode

Enable verbose logging:
```bash
export LOG_LEVEL=DEBUG
python -m orderbook_lgbm.scripts.build_features --log-level DEBUG [args...]
```

## 📝 Development Roadmap

### Immediate Next Steps
- [ ] Add classification mode (direction-only prediction)
- [ ] Implement TimeSeriesSplit cross-validation
- [ ] Add feature importance plots and SHAP values
- [ ] Create hyperparameter optimization script

### Future Enhancements
- [ ] Multi-asset portfolio training
- [ ] Regime-aware model switching
- [ ] Real-time inference pipeline
- [ ] Backtesting framework integration

## 🤝 Contributing

1. **Fork** the repository
2. **Create** a feature branch
3. **Test** changes with existing CLI scripts
4. **Document** new features in this README
5. **Submit** a pull request

## 📄 License

This project is part of the Calvin AI trading system. See main repository for license information.

---

**Happy Trading!** 📈🤖
