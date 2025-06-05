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
- CUDA-compatible GPU (RTX 4070 Super recommended for ML training)
- Solana Wallet
- API Keys:
  - BirdEye API
  - Helius API
  - LunarCrush API

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/calvin-ai.git
cd calvin-ai
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

### Creating a Wallet

If you don't have a Solana wallet, you can create one:

```bash
python main.py create-wallet --save-path wallet.json
```

**IMPORTANT**: Store your wallet information securely and never share your private key!

### Getting Token Information

To get information about a token:

```bash
python main.py token-info --token-address <TOKEN_ADDRESS>
```

### Training the ML Model

To train the model with historical data:

```bash
python main.py train --token-address <TOKEN_ADDRESS> --symbol SOL --days 30 --model-type lstm --plot
```

Parameters:
- `--token-address`: Address of the token to train on (required)
- `--symbol`: Symbol of the token (default: SOL)
- `--days`: Number of days of historical data to use (default: 30)
- `--model-type`: Type of ML model to use (lstm, gru, transformer) (default: lstm)
- `--epochs`: Number of training epochs (default: 100)
- `--batch-size`: Training batch size (default: 32)
- `--plot`: Plot training results

### Testing the ML Model

To test the trained model against historical data:

```bash
python main.py test --token-address <TOKEN_ADDRESS> --model-path models/lstm_20230101_120000.h5 --plot
```

Parameters:
- `--token-address`: Address of the token to test on (required)
- `--symbol`: Symbol of the token (default: SOL)
- `--model-path`: Path to the model to test (if not provided, uses the latest model)
- `--days`: Number of days of historical data to use (default: 10)
- `--plot`: Plot test results

### Running the Trading Bot

To run the trading bot:

```bash
python main.py run --token-address <TOKEN_ADDRESS> --symbol SOL --interval 15
```

Parameters:
- `--token-address`: Address of the token to trade (required)
- `--symbol`: Symbol of the token (default: SOL)
- `--model-path`: Path to the ML model to use (if not provided, uses the latest model)
- `--interval`: Trading interval in minutes (default: from config)

### Data Lake Setup (Optional)

The backend supports migrating trading data from SQLite into an Apache Iceberg data lake for analytics:

```bash
# From project root
export DB_USE_SQLITE=true
make bootstrap-lake
```

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
