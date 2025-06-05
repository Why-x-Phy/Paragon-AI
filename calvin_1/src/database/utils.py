import os
import sys
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy.exc import IntegrityError
from typing import List, Dict, Optional, Union, Any

from .db import init_db, get_session, Token, OHLCV, Feature, TradeRecord, ModelPrediction, ModelEvaluation
from src.utils.logger import log_manager

# Initialize logger
logger = log_manager.get_logger("database_utils")

def create_tables():
    """Initialize database tables if they don't exist"""
    engine = init_db()
    logger.info("Database tables created or already exist")
    return engine

def add_token(address: str, symbol: str, name: Optional[str] = None, decimals: Optional[int] = None):
    """Add a new token to the database"""
    session = get_session()
    try:
        # Check if token already exists
        existing = session.query(Token).filter(Token.address == address).first()
        if existing:
            logger.info(f"Token {symbol} ({address}) already exists")
            return existing
        
        # Create new token
        token = Token(
            address=address,
            symbol=symbol,
            name=name,
            decimals=decimals
        )
        session.add(token)
        session.commit()
        logger.info(f"Added token {symbol} ({address})")
        return token
    except Exception as e:
        session.rollback()
        logger.error(f"Error adding token: {e}")
        return None
    finally:
        session.close()

def add_ohlcv_data(token_id: int, data: Union[pd.DataFrame, List[Dict]], resolution: str = '15m'):
    """
    Add OHLCV data to the database
    
    Args:
        token_id: Token ID from the database
        data: DataFrame or list of dicts with OHLCV data
        resolution: Time resolution (1m, 5m, 15m, 1h, 4h, 1d)
        
    Returns:
        Dictionary with 'added' and 'skipped' counts
    """
    session = get_session()
    try:
        added = 0
        skipped = 0
        
        # Convert dataframe to records
        if hasattr(data, 'to_dict'):
            # Rename columns if they use the short names
            rename_map = {
                'o': 'open',
                'h': 'high',
                'l': 'low',
                'c': 'close',
                'v': 'volume',
                'unixTime': 'timestamp'
            }
            
            # Only rename columns that exist and need renaming
            cols_to_rename = {k: v for k, v in rename_map.items() if k in data.columns and v not in data.columns}
            if cols_to_rename:
                data = data.rename(columns=cols_to_rename)
                
            records = data.to_dict('records')
        else:
            records = data
        
        # Create a set of existing timestamps to check for duplicates
        # This is much faster than relying on database constraints for each record
        existing_timestamps = set()
        # Use case-insensitive matching on resolution
        lower_resolution = resolution.lower()
        timestamp_query = session.query(OHLCV.timestamp).filter(
            OHLCV.token_id == token_id,
            (OHLCV.resolution == resolution) | (OHLCV.resolution == lower_resolution)
        )
        for row in timestamp_query:
            existing_timestamps.add(row[0])
        
        # Prepare ohlcv objects for bulk insert
        ohlcv_objects = []
        processed_timestamps = set()  # Track timestamps within current batch
        
        for item in records:
            # Convert timestamp to datetime if needed
            timestamp = item.get('timestamp')
            if isinstance(timestamp, (int, float)):
                timestamp = datetime.fromtimestamp(timestamp)
            
            # Skip if this timestamp already exists in DB or within current batch
            if timestamp in existing_timestamps or timestamp in processed_timestamps:
                skipped += 1
                continue
                
            # Add timestamp to processed set to avoid duplicates within the batch
            processed_timestamps.add(timestamp)
                
            # Create OHLCV record
            ohlcv = OHLCV(
                token_id=token_id,
                timestamp=timestamp,
                resolution=resolution,
                open=item.get('open') or item.get('o', 0),
                high=item.get('high') or item.get('h', 0),
                low=item.get('low') or item.get('l', 0),
                close=item.get('close') or item.get('c', 0),
                volume=item.get('volume') or item.get('v', 0)
            )
            
            ohlcv_objects.append(ohlcv)
            added += 1
        
        # Bulk insert all records at once
        if ohlcv_objects:
            try:
                session.bulk_save_objects(ohlcv_objects)
                session.commit()
            except IntegrityError as e:
                # If bulk insert fails, roll back and insert one by one
                session.rollback()
                logger.warning(f"Bulk insert failed, trying individual inserts: {e}")
                
                added = 0
                skipped = 0
                
                for ohlcv in ohlcv_objects:
                    try:
                        session.add(ohlcv)
                        session.commit()
                        added += 1
                    except IntegrityError:
                        session.rollback()
                        skipped += 1
                    except Exception as err:
                        session.rollback()
                        logger.error(f"Error in individual insert: {err}")
            
        logger.info(f"Added {added} OHLCV records, skipped {skipped} duplicates")
        return {'added': added, 'skipped': skipped}
    except Exception as e:
        session.rollback()
        logger.error(f"Error adding OHLCV data: {e}")
        return {'added': 0, 'skipped': 0}
    finally:
        session.close()

def get_ohlcv_data(
    token_id: int, 
    resolution: str = '15m', 
    start_date: Optional[datetime] = None, 
    end_date: Optional[datetime] = None, 
    limit: int = 1000
) -> List[OHLCV]:
    """
    Get OHLCV data from the database
    
    Args:
        token_id: Token ID from the database
        resolution: Time resolution (1m, 5m, 15m, 1h, 4h, 1d)
        start_date: Start timestamp (defaults to 30 days ago)
        end_date: End timestamp (defaults to now)
        limit: Maximum number of records to return
    """
    session = get_session()
    try:
        # Use SQL LOWER function to do case-insensitive matching on resolution
        lower_resolution = resolution.lower()
        query = session.query(OHLCV).filter(
            OHLCV.token_id == token_id,
            (OHLCV.resolution == resolution) | (OHLCV.resolution == lower_resolution)
        )
        
        if start_date:
            query = query.filter(OHLCV.timestamp >= start_date)
        else:
            query = query.filter(OHLCV.timestamp >= datetime.now() - timedelta(days=30))
            
        if end_date:
            query = query.filter(OHLCV.timestamp <= end_date)
            
        query = query.order_by(OHLCV.timestamp).limit(limit)
        
        return query.all()
    finally:
        session.close()

def ohlcv_to_dataframe(ohlcv_records: List[OHLCV]) -> pd.DataFrame:
    """Convert OHLCV records to a pandas DataFrame"""
    data = []
    for record in ohlcv_records:
        data.append({
            'timestamp': record.timestamp,
            'open': record.open,
            'high': record.high,
            'low': record.low,
            'close': record.close,
            'volume': record.volume
        })
    
    df = pd.DataFrame(data)
    if not df.empty:
        df.set_index('timestamp', inplace=True)
    
    return df

def add_feature(ohlcv_id: int, feature_data: Dict):
    """Add a feature record for an OHLCV entry"""
    session = get_session()
    try:
        # Check if feature already exists
        existing = session.query(Feature).filter(Feature.ohlcv_id == ohlcv_id).first()
        if existing:
            # Update existing feature
            for key, value in feature_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            session.commit()
            return existing
        
        # Create new feature record
        feature = Feature(ohlcv_id=ohlcv_id, **feature_data)
        session.add(feature)
        session.commit()
        return feature
    except Exception as e:
        session.rollback()
        logger.error(f"Error adding feature: {e}")
        return None
    finally:
        session.close()

def record_trade(
    token_id: int, 
    action: str, 
    price: float, 
    amount: float, 
    position: str,
    amount_usd: Optional[float] = None,
    fee: Optional[float] = None,
    reason: Optional[str] = None,
    tx_signature: Optional[str] = None,
    success: bool = True
):
    """Record a trade in the database"""
    session = get_session()
    try:
        trade = TradeRecord(
            token_id=token_id,
            timestamp=datetime.now(),
            action=action,
            price=price,
            amount=amount,
            amount_usd=amount_usd,
            fee=fee,
            position=position,
            reason=reason,
            tx_signature=tx_signature,
            success=success
        )
        session.add(trade)
        session.commit()
        return trade
    except Exception as e:
        session.rollback()
        logger.error(f"Error recording trade: {e}")
        return None
    finally:
        session.close()

def record_prediction(
    token_id: int,
    predicted_price: float,
    actual_price: Optional[float] = None,
    horizon: int = 1,
    model_version: Optional[str] = None,
    confidence: Optional[float] = None
):
    """Record a model prediction in the database"""
    session = get_session()
    try:
        prediction = ModelPrediction(
            token_id=token_id,
            timestamp=datetime.now(),
            predicted_price=predicted_price,
            actual_price=actual_price,
            horizon=horizon,
            model_version=model_version,
            confidence=confidence
        )
        session.add(prediction)
        session.commit()
        return prediction
    except Exception as e:
        session.rollback()
        logger.error(f"Error recording prediction: {e}")
        return None
    finally:
        session.close()

def get_token_by_address(address: str) -> Optional[Token]:
    """Get a token by its address"""
    session = get_session()
    try:
        return session.query(Token).filter(Token.address == address).first()
    finally:
        session.close()

def get_token_by_symbol(symbol: str) -> Optional[Token]:
    """Get a token by its symbol"""
    session = get_session()
    try:
        return session.query(Token).filter(Token.symbol == symbol).first()
    finally:
        session.close()

def update_prediction_actual_price(prediction_id: int, actual_price: float):
    """Update a prediction with the actual price once known"""
    session = get_session()
    try:
        prediction = session.query(ModelPrediction).get(prediction_id)
        if prediction:
            prediction.actual_price = actual_price
            prediction.error = abs(prediction.predicted_price - actual_price)
            session.commit()
            return prediction
        return None
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating prediction: {e}")
        return None
    finally:
        session.close()

def get_trade_history(token_id: Optional[int] = None, limit: int = 100) -> List[TradeRecord]:
    """Get trading history for a token or all tokens"""
    session = get_session()
    try:
        query = session.query(TradeRecord)
        if token_id:
            query = query.filter(TradeRecord.token_id == token_id)
        
        return query.order_by(TradeRecord.timestamp.desc()).limit(limit).all()
    finally:
        session.close()

def get_model_performance(token_id: int, model_version: Optional[str] = None, horizon: Optional[int] = None) -> Dict:
    """Get model performance metrics"""
    session = get_session()
    try:
        query = session.query(ModelPrediction).filter(
            ModelPrediction.token_id == token_id,
            ModelPrediction.actual_price != None
        )
        
        if model_version:
            query = query.filter(ModelPrediction.model_version == model_version)
        
        if horizon:
            query = query.filter(ModelPrediction.horizon == horizon)
        
        predictions = query.all()
        
        if not predictions:
            return {
                'count': 0,
                'mae': 0,
                'mape': 0,
                'correct_direction': 0,
                'accuracy': 0
            }
        
        # Calculate metrics
        total_error = 0
        total_percentage_error = 0
        correct_direction = 0
        
        for pred in predictions:
            total_error += abs(pred.predicted_price - pred.actual_price)
            total_percentage_error += abs(pred.predicted_price - pred.actual_price) / pred.actual_price * 100
            
            # Check if prediction was in the correct direction
            # This requires prev price which we don't have in this simple implementation
            # In a real system, you'd use the previous price or compare with a baseline
        
        mae = total_error / len(predictions)
        mape = total_percentage_error / len(predictions)
        
        return {
            'count': len(predictions),
            'mae': mae,
            'mape': mape,
            'correct_direction': correct_direction,
            'accuracy': 0  # Would be calculated with direction prediction
        }
    finally:
        session.close()

def get_token_details_by_address(address: str) -> Dict[str, Any]:
    """
    Get token details by address, returning simple values instead of ORM object
    
    Args:
        address: Token address
        
    Returns:
        Dict with token details, or None if not found
    """
    session = get_session()
    try:
        token = session.query(Token).filter(Token.address == address).first()
        if not token:
            return None
        
        # Extract the values we need before closing the session
        return {
            'token_id': token.token_id,
            'symbol': token.symbol,
            'name': token.name,
            'decimals': token.decimals,
            'address': token.address
        }
    finally:
        session.close()

def save_model_evaluation(
    token_id: int, 
    model_version: str,
    metrics: Dict,
    optimization_target: str = "profit"
):
    """
    Save model evaluation metrics to the database
    
    Args:
        token_id: Token ID from the database
        model_version: Model version or name
        metrics: Dictionary of evaluation metrics
        optimization_target: Model optimization target (profit, direction, combined, mse)
        
    Returns:
        The created ModelEvaluation record
    """
    session = get_session()
    try:
        # Create evaluation record
        evaluation = ModelEvaluation(
            token_id=token_id,
            model_version=model_version,
            optimization_target=optimization_target,
            
            # Standard ML metrics
            mse=metrics.get('mse', 0),
            rmse=metrics.get('rmse', 0),
            mae=metrics.get('mae', 0),
            r2=metrics.get('r2', 0),
            direction_accuracy=metrics.get('direction_accuracy', 0),
            
            # Profit-oriented metrics
            total_return=metrics.get('total_return', 0),
            buy_hold_return=metrics.get('buy_hold_return', 0),
            win_rate=metrics.get('win_rate', 0),
            sharpe_ratio=metrics.get('sharpe_ratio', 0),
            max_drawdown=metrics.get('max_drawdown', 0),
            total_trades=metrics.get('total_trades', 0)
        )
        
        session.add(evaluation)
        session.commit()
        logger.info(f"Saved model evaluation for {model_version} with total_return: {metrics.get('total_return', 0):.2%}")
        return evaluation
    except Exception as e:
        session.rollback()
        logger.error(f"Error saving model evaluation: {e}")
        return None
    finally:
        session.close()

def get_model_evaluations(
    token_id: Optional[int] = None, 
    model_version: Optional[str] = None,
    optimization_target: Optional[str] = None,
    limit: int = 10
) -> List[Dict]:
    """
    Get model evaluation records
    
    Args:
        token_id: Optional token ID to filter by
        model_version: Optional model version to filter by
        optimization_target: Optional optimization target to filter by
        limit: Maximum number of records to return
        
    Returns:
        List of model evaluation records as dictionaries
    """
    session = get_session()
    try:
        query = session.query(ModelEvaluation)
        
        # Apply filters if provided
        if token_id is not None:
            query = query.filter(ModelEvaluation.token_id == token_id)
        
        if model_version is not None:
            query = query.filter(ModelEvaluation.model_version == model_version)
            
        if optimization_target is not None:
            query = query.filter(ModelEvaluation.optimization_target == optimization_target)
        
        # Get most recent evaluations
        query = query.order_by(ModelEvaluation.timestamp.desc()).limit(limit)
        
        evaluations = query.all()
        
        # Convert to dictionaries for easier use
        result = []
        for eval in evaluations:
            result.append({
                'evaluation_id': eval.evaluation_id,
                'model_version': eval.model_version,
                'token_id': eval.token_id,
                'token_symbol': eval.token.symbol if eval.token else "Unknown",
                'timestamp': eval.timestamp.isoformat(),
                'optimization_target': eval.optimization_target,
                
                # Standard ML metrics
                'mse': eval.mse,
                'rmse': eval.rmse,
                'mae': eval.mae,
                'r2': eval.r2,
                'direction_accuracy': eval.direction_accuracy,
                
                # Profit-oriented metrics
                'total_return': eval.total_return,
                'buy_hold_return': eval.buy_hold_return,
                'win_rate': eval.win_rate,
                'sharpe_ratio': eval.sharpe_ratio,
                'max_drawdown': eval.max_drawdown,
                'total_trades': eval.total_trades
            })
        
        return result
    except Exception as e:
        logger.error(f"Error getting model evaluations: {e}")
        return []
    finally:
        session.close()

def get_all_active_tokens() -> List[Dict[str, Any]]:
    """
    Get all active tokens from the database
    
    Returns:
        List of dictionaries with token details
    """
    session = get_session()
    try:
        tokens = session.query(Token).filter(Token.is_active == True).all()
        
        # Convert ORM objects to dictionaries
        return [
            {
                'token_id': token.token_id,
                'symbol': token.symbol,
                'name': token.name,
                'decimals': token.decimals,
                'address': token.address
            }
            for token in tokens
        ]
    finally:
        session.close() 