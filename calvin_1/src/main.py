import os
import sys
import time
import argparse
from datetime import datetime

from src.data.data_processor import DataProcessor
from src.models.model_trainer import ModelTrainer
from src.trading.trading_strategy import TradingStrategy
from src.config.config import config
from src.utils.logger import log_manager
from src.database.utils import create_tables, add_token, get_token_by_address

logger = log_manager.get_logger("main")

def setup_database():
    """Initialize the database and tables"""
    logger.info("Setting up database")
    create_tables()
    
    # Add some common tokens if they don't exist
    tokens = [
        {
            "address": "So11111111111111111111111111111111111111112",
            "symbol": "SOL",
            "name": "Wrapped SOL",
            "decimals": 9
        },
        {
            "address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "symbol": "USDC",
            "name": "USD Coin",
            "decimals": 6
        },
        {
            "address": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
            "symbol": "USDT",
            "name": "USDT",
            "decimals": 6
        }
    ]
    
    for token in tokens:
        if not get_token_by_address(token["address"]):
            logger.info(f"Adding token {token['symbol']} to database")
            add_token(
                address=token["address"],
                symbol=token["symbol"],
                name=token["name"],
                decimals=token["decimals"]
            )

def main():
    parser = argparse.ArgumentParser(description='Solana ML Trading Bot')
    parser.add_argument('--train', action='store_true', help='Train the model')
    parser.add_argument('--backtest', action='store_true', help='Run backtest')
    parser.add_argument('--trade', action='store_true', help='Run trading bot')
    parser.add_argument('--token', type=str, default='So11111111111111111111111111111111111111112', help='Token address')
    parser.add_argument('--days', type=int, default=30, help='Days of historical data')
    parser.add_argument('--resolution', type=str, default='15m', help='Data resolution (1m, 5m, 15m, 1h, 4h, 1d)')
    
    args = parser.parse_args()
    
    # Setup database
    setup_database()
    
    # Initialize components
    data_processor = DataProcessor()
    model_trainer = ModelTrainer()
    trading_strategy = TradingStrategy()
    
    # Default token is SOL
    token_address = args.token
    symbol = "SOL"  # Default symbol
    
    # Get token info from database
    token = get_token_by_address(token_address)
    if token:
        symbol = token.symbol
    
    if args.train:
        logger.info(f"Training model for {symbol} ({token_address})")
        
        # Process data
        df = data_processor.process_pipeline(
            token_address=token_address,
            symbol=symbol,
            resolution=args.resolution,
            days=args.days,
            save_data=True
        )
        
        # Train model
        X_train, X_test, y_train, y_test = data_processor.prepare_ml_data(
            df=df,
            target_col='close',
            sequence_length=10,
            prediction_horizon=1
        )
        
        model = model_trainer.train_model(X_train, y_train, X_test, y_test)
        
        # Save the model
        model_filename = f"{symbol}_{args.resolution}_model_{datetime.now().strftime('%Y%m%d')}.h5"
        model_trainer.save_model(model, model_filename)
        
    elif args.backtest:
        logger.info(f"Running backtest for {symbol} ({token_address})")
        
        # Process data
        df = data_processor.process_pipeline(
            token_address=token_address,
            symbol=symbol,
            resolution=args.resolution,
            days=args.days
        )
        
        # Load the latest model
        model = model_trainer.load_latest_model(symbol)
        
        if model:
            # Run backtest
            results = trading_strategy.backtest(
                model=model,
                data=df,
                data_processor=data_processor,
                initial_balance=1000,
                fee_rate=0.001
            )
            
            # Display backtest results
            trading_strategy.display_results(results)
        else:
            logger.error(f"No trained model found for {symbol}")
            
    elif args.trade:
        logger.info(f"Starting trading bot for {symbol} ({token_address})")
        
        # Load the latest model
        model = model_trainer.load_latest_model(symbol)
        
        if model:
            # Start trading
            trading_strategy.run_live_trading(
                model=model,
                token_address=token_address,
                data_processor=data_processor,
                resolution=args.resolution
            )
        else:
            logger.error(f"No trained model found for {symbol}")
    
    else:
        parser.print_help()

if __name__ == "__main__":
    main() 