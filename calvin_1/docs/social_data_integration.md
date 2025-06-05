# Social Data Integration Guide

## Overview

The Calvin AI trading system includes integration with LunarCrush API to collect and analyze social media metrics for cryptocurrencies. This social data can provide valuable insights about market sentiment, social volume, and attention that may influence price movements.

## Features

- Fetch social metrics from LunarCrush API
- Store historical social data in the database
- Update token metadata with social information
- Scheduled data collection to maintain up-to-date information
- Advanced social feature engineering for ML models

## Database Schema

Social data is stored in the `social_metrics` table with the following structure:

| Field                | Type      | Description                                       |
|----------------------|-----------|---------------------------------------------------|
| id                   | Integer   | Primary key                                       |
| token_id             | Integer   | Foreign key to tokens table                       |
| timestamp            | DateTime  | Timestamp of the data point                       |
| resolution           | String    | Time resolution of data ('1h', '1d', etc.)        |
| contributors_active  | Integer   | Number of unique social accounts with interactions|
| contributors_created | Integer   | Number of unique accounts creating posts          |
| interactions         | Integer   | All measurable social interactions                |
| posts_active         | Integer   | Number of posts with interactions                 |
| posts_created        | Integer   | Number of new posts created                       |
| sentiment            | Float     | Percentage of positive sentiment (0-100)          |
| spam                 | Integer   | Number of spam posts detected                     |
| alt_rank             | Integer   | LunarCrush ranking                                |
| circulating_supply   | Float     | Circulating token supply                          |
| close_price          | Float     | Closing price at the timestamp                    |
| galaxy_score         | Integer   | LunarCrush proprietary score                      |
| market_cap           | Float     | Market capitalization in USD                      |
| market_dominance     | Float     | Percent of total market cap                       |
| volume_24h           | Float     | Trading volume in USD for past 24h                |
| social_dominance     | Float     | Percent of total social volume                    |

## Usage Guide

### Fetching Social Data for a Specific Token

To fetch social data for a specific token, run:

```bash
python -m src.scripts.fetch_social_data --symbol FART --days 30 --interval 1w
```

### Fetching Large Amounts of Historical Data

For months of historical data, use the chunking capabilities:

```bash
python -m src.scripts.fetch_social_data --symbol FART --days 180 --batch-size 100 --log-level DEBUG
```

Options:
- `--days`: Number of days of data to fetch (can be up to 365 or more)
- `--batch-size`: Number of database records to process in each batch (higher values for faster processing)
- `--log-level`: Set to DEBUG for detailed progress on large fetches

### Scheduling Automatic Updates

To run the fetcher on a schedule (e.g., every 60 minutes):

```bash
python -m src.scripts.fetch_social_data --schedule 60
```

### Command Line Arguments

| Argument         | Short | Default | Description                                       |
|------------------|-------|---------|---------------------------------------------------|
| --symbol         | -s    | None    | Token symbol to fetch data for                    |
| --interval       | -i    | 1w      | Data resolution interval                          |
| --days           | -d    | 30      | Number of days of history to fetch                |
| --batch-size     | -b    | 100     | Number of records to process in each database batch |
| --schedule       | -t    | 0       | Minutes between scheduled runs (0 = run once)     |
| --log-level      | -l    | INFO    | Log level for output                              |

## LunarCrush API

The integration uses [LunarCrush's API](https://lunarcrush.com/developers/docs) to fetch social metrics. To use this feature, you need to:

1. Obtain an API key from LunarCrush
2. Set the API key in your `.env` file:

```
LUNARCRUSH_API_KEY=your_api_key_here
```

## Social Feature Engineering

The system now includes advanced social feature engineering to create predictive features from raw social data:

### Derived Social Features

For each social metric, the system calculates:

- Moving averages (3-day and 7-day)
- Rate of change (1-day and 3-day)
- Acceleration (change in the rate of change)
- Z-scores (statistical outlier detection)

### Combined Features

The system also creates combinations of different social metrics:

- Sentiment-weighted volume
- Dominance-weighted sentiment
- Galaxy score correlation with price

### Using Social Features in Price Prediction

To use these social features in your prediction model:

```python
from src.data.data_processor import DataProcessor

# Initialize the data processor
dp = DataProcessor()

# Process data with social features included
df = dp.process_pipeline(
    token_address="9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
    symbol="FART",
    days=30,
    include_sentiment=True  # This flag enables social feature engineering
)

# Prepare data for ML model with social features
X_train, X_test, y_train, y_test, feature_names = dp.prepare_ml_data(
    df=df,
    sequence_length=10,
    prediction_horizon=1,
    include_feature_names=True
)

# Display social features included in the model
social_features = [name for name in feature_names if any(ind in name for ind in 
                  ['sentiment', 'social', 'galaxy', 'contributors', 'posts', 
                   'interactions', 'spam', 'dominance'])]
print(f"Social features used in the model: {social_features}")
```

## Example Social Feature Analysis

You can analyze the most important social features for price prediction:

```python
import matplotlib.pyplot as plt
import numpy as np
from sklearn.ensemble import RandomForestRegressor

# Reshape sequential data for feature importance analysis
X_flat = X_train.reshape(X_train.shape[0], -1)

# Train a model to get feature importances
model = RandomForestRegressor(n_estimators=100)
model.fit(X_flat, y_train)

# Calculate feature importance for each sequence step
importances = []
for i in range(X_train.shape[1]):  # For each time step
    for j, name in enumerate(feature_names):
        importances.append((f"{name} (t-{X_train.shape[1]-i-1})", model.feature_importances_[i*len(feature_names) + j]))

# Sort by importance
importances.sort(key=lambda x: x[1], reverse=True)

# Plot top 20 features
top_n = 20
plt.figure(figsize=(12, 8))
features, scores = zip(*importances[:top_n])
plt.barh(range(top_n), scores, align='center')
plt.yticks(range(top_n), features)
plt.xlabel('Feature Importance')
plt.title(f'Top {top_n} Features by Importance')
plt.tight_layout()
plt.savefig('social_feature_importance.png')
```

## Future Improvements

- Add more social platforms as data sources
- Implement advanced sentiment analysis
- Create visualizations for social metrics
- Develop trading strategies based on social signals
- Add word embedding features from social text data 