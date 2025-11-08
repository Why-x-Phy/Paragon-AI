# Calvin AI Trading Platform

An autonomous machine learning trading platform for Solana blockchain, featuring a powerful backend ML system and a modern frontend interface.

## Project Structure

This project is organized into multiple components:

1. **calvin_1**: The core backend AI and ML trading engine
2. **frontend**: The user interface for interacting with the trading platform
3. **smart-contracts** (coming soon): Blockchain smart contracts

## Features

- **Data Collection**: Fetches market data from BirdEye API, blockchain data from Helius API, and social sentiment data from LunarCrush API
- **ML Model Training**: Uses TensorFlow to train LSTM, GRU, or Transformer models for price prediction
- **Technical Analysis**: Calculates technical indicators to enhance prediction accuracy
- **Automated Trading**: Executes trades based on ML predictions and technical signals
- **Performance Tracking**: Records trades and calculates performance metrics
- **Solana Blockchain Integration**: Interacts with the Solana blockchain for executing trades
- **Modern UI**: Clean, responsive interface for monitoring trading activity and performance

## Requirements

- Python 3.11+ (for backend)
- Node.js 18+ (for frontend)
- Solana Wallet
- API Keys:
  - BirdEye API
  - Helius API
  - LunarCrush API

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/calvin-ai.git
cd calvin_ai
```

2. Set up environment variables:
```bash
# Copy the example file and edit with your API keys
cp .env.example .env
```

3. Set up the backend:
```bash
cd calvin_1
python -m venv venv-py311
source venv-py311/bin/activate  # On Windows: venv-py311\Scripts\activate
pip install -r ../requirements.txt
```

4. Set up the frontend (when available):
```bash
cd ../frontend
npm install
```

## Backend Usage (calvin_1)

Navigate to the backend directory first:
```bash
cd calvin_1
```

```

## Run Orderbook LGBM Experiments (z_experimental)

This section shows how to bring up the database stack, seed data, and run the LightGBM snapshot experiment in `calvin_1/z_experimental/orderbook_lgbm`.

### Prerequisites

- Docker Engine and Docker Compose v2 (compose plugin) and Git
- Python 3.11
- Linux or WSL2 on Windows (recommended). On Windows, open Ubuntu (WSL2) and run all shell commands there. The Windows path `D:\calvin_ai` maps to `/mnt/d/calvin_ai`.
- Open local ports:
  - 5433 TimescaleDB (PostgreSQL)
  - 6379 Redis
  - 6432 PgBouncer
  - 8080 Adminer (optional DB UI)

### Environment (.env) quickstart

Create a `.env` at the repo root. The setup script reads this file.

```env
# ---- Database (dev) ----
DB_HOST=localhost
DB_PORT=5433
DB_NAME=calvin_trading_dev
DB_USER=calvin_dev
DB_PASSWORD=calvin_dev_password
DB_PASSWORD_DEV=${DB_PASSWORD}

# ---- Redis (optional override) ----
REDIS_PASSWORD_DEV=calvin_redis_dev_secure_456

# ---- BirdEye ----
# Provide at least one; multiple keys rotate to avoid rate limits
BIRDEYE_API_KEY_1=your_birdeye_key_1
# BIRDEYE_API_KEY_2=...
# BIRDEYE_API_KEY_3=...

# Tokens to seed (comma-separated Solana addresses)
TRACKED_TOKENS=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v  # USDC (example)

# ---- LunarCrush (optional, for social data) ----
LUNARCRUSH_API_KEY=your_lunarcrush_key

# ---- CoinAPI (optional, for orderbook ingestion via API) ----
COINAPI_KEY=your_coinapi_key
```

Tip for CoinAPI ingestion: the `ingest_limitbooks.py --coinapi` mode reads `DATABASE_URL`. For example:

```bash
export DATABASE_URL="postgres://calvin_dev:${DB_PASSWORD}@localhost:5433/calvin_trading_dev"
```

### Start databases and initialize schema

Run from the `docker/` directory (Linux/WSL2 shell):

```bash
cd docker
./scripts/setup.sh setup
./scripts/setup.sh health
```

What this does:
- Starts TimescaleDB, Redis, and PgBouncer via `docker-compose.dev.yml`
- Applies core schema (`docker/db/init/01-init-timescaledb.sql`)
- Applies orderbook and aggregates schema (`docker/scripts/02-limitbook-schema.sql`)
- Seeds tokens from BirdEye if `TRACKED_TOKENS` and `BIRDEYE_API_KEY_*` are set
- Optionally maps LunarCrush IDs if `LUNARCRUSH_API_KEY` is set

Adminer (optional): http://localhost:8080

### Create Python 3.11 venv and install dependencies

From the repo root (Linux/WSL2):

```bash
python3.11 -m venv venv-py311
source venv-py311/bin/activate
pip install -r requirements.txt
```

### Ingest OHLCV data (BirdEye)

You can ingest for one token or all active tokens. Requires at least one `BIRDEYE_API_KEY_*` in `.env`.

All tokens (recommended to start small, e.g., 30 days):

```bash
python calvin_1/src/scripts/fetch_historical_data.py \
  --all-tokens \
  --resolution 1H \
  --days 30 \
  --max-workers 5
```

Single token by address:

```bash
python calvin_1/src/scripts/fetch_historical_data.py \
  --token-address <SOLANA_TOKEN_ADDRESS> \
  --resolution 1H \
  --days 30
```

### (Optional) Ingest social data (LunarCrush)

All tokens with available mappings:

```bash
python calvin_1/src/scripts/fetch_social_data.py --days 90
```

Single symbol:

```bash
python calvin_1/src/scripts/fetch_social_data.py --symbol BONK --days 90
```

If you haven’t mapped LunarCrush IDs, you can run:

```bash
cd docker
./scripts/setup.sh lunarcrush
```

### Populate orderbook tables (choose one path)

A) CoinAPI API → DB (no local files; good for targeted symbols/dates)

```bash
export DATABASE_URL="postgres://calvin_dev:${DB_PASSWORD}@localhost:5433/calvin_trading_dev"
export COINAPI_KEY=your_coinapi_key

python calvin_1/src/scripts/ingest_limitbooks.py \
  --coinapi \
  --symbol-id BINANCE_SPOT_BTC_USDT \
  --start-date 2024-07-01 \
  --end-date 2024-07-03
```

Optional CSV preview (first N rows):

```bash
python calvin_1/src/scripts/ingest_limitbooks.py \
  --coinapi \
  --symbol-id BINANCE_SPOT_BTC_USDT \
  --start-date 2024-07-01 \
  --end-date 2024-07-01 \
  --csv-out /tmp/preview.csv --csv-max-rows 10000
```

B) Flat files (CoinAPI S3) → local → DB (good for larger backfills)

1) Download flat files (requires `aws` CLI):

```bash
python calvin_1/src/scripts/download_limitbooks.py \
  --start 2024-07-01 \
  --end 2024-07-02 \
  --exchange BINANCE \
  --symbols BTC-USDT \
  --out-dir calvin_1/limitbooks
```

2) Ingest locally downloaded files:

```bash
python calvin_1/src/scripts/ingest_limitbooks.py \
  --dir calvin_1/limitbooks \
  --psql-url "postgres://calvin_dev:${DB_PASSWORD}@localhost:5433/calvin_trading_dev"
```

After large backfills, refresh continuous aggregates:

```bash
python docker/scripts/refresh_lbu_1m.py
```

### Run the LGBM snapshot experiment

The experiment reads per-snapshot L1..L20 from `orderbook_levels` and uses TimescaleDB at `localhost:5433` (see `calvin_1/z_experimental/orderbook_lgbm/config.py`).

Example (train one day, BTC):

```bash
python calvin_1/z_experimental/orderbook_lgbm/scripts/train_one_day_snapshot.py \
  --symbol BTC \
  --date 2024-07-01 \
  --limit_rows 200000 \
  --horizon_sec 1
```

### Troubleshooting

- Connection refused:
  - Ensure containers are up: `cd docker && ./scripts/setup.sh health`
  - Ensure ports 5433/6379/6432/8080 are free
- DB credentials mismatch:
  - Update `.env` and re-run `./scripts/setup.sh setup`
  - For CoinAPI mode, ensure `DATABASE_URL` is exported
- No or few rows in training:
  - Verify `orderbook_levels` populated (use Adminer at http://localhost:8080)
  - If needed, run `python docker/scripts/refresh_lbu_1m.py`
- Windows shell errors:
  - Use WSL2 Ubuntu and run commands in `/mnt/d/calvin_ai`

## Frontend Usage (When Available)

```bash
# From project root
cd frontend
npm run dev
```

## Architecture

### Backend (`calvin_1/`)

- `src/data/`: Data collection and processing modules
- `src/model/`: Machine learning model implementation
- `src/trading/`: Trading functionality and wallet
- `src/config/`: Configuration management
- `src/utils/`: Utilities and helpers

### Frontend (`frontend/`)

- `src/components/`: UI components
- (Additional frontend structure will be detailed as development progresses)

## Risk Warning

**IMPORTANT**: Trading cryptocurrencies involves significant risk and can result in the loss of your invested capital. This platform is provided for educational purposes only and should not be used for actual trading without thorough testing and understanding of the risks involved.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgements

- [Solana](https://solana.com/)
- [BirdEye](https://birdeye.so/)
- [Helius](https://helius.xyz/)
- [LunarCrush](https://lunarcrush.com/)
- [TensorFlow](https://www.tensorflow.org/)
