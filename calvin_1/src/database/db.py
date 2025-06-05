import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, UniqueConstraint, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import datetime

Base = declarative_base()

class Token(Base):
    __tablename__ = 'tokens'
    
    token_id = Column(Integer, primary_key=True)
    address = Column(String(64), unique=True, nullable=False)
    symbol = Column(String(20), nullable=False)
    name = Column(String(100))
    decimals = Column(Integer)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Additional metadata fields for token embeddings
    category = Column(String(20))  # defi, meme, gaming, stable, crypto
    has_website = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    social_score = Column(Integer)
    creation_date = Column(DateTime)
    circulating_supply = Column(Float)
    max_supply = Column(Float)
    market_cap = Column(Float)
    description = Column(Text)
    website_url = Column(String(255))
    twitter_handle = Column(String(50))
    discord_url = Column(String(255))
    github_url = Column(String(255))
    lunarcrush_id = Column(String(50))  # LunarCrush internal ID
    
    # Relationships
    ohlcv_data = relationship('OHLCV', back_populates='token')
    social_metrics = relationship('SocialMetrics', back_populates='token')
    
    def __repr__(self):
        return f"<Token(symbol='{self.symbol}', address='{self.address}')>"

class OHLCV(Base):
    __tablename__ = 'ohlcv'
    
    ohlcv_id = Column(Integer, primary_key=True)
    token_id = Column(Integer, ForeignKey('tokens.token_id'))
    timestamp = Column(DateTime, nullable=False)
    resolution = Column(String(10), nullable=False)  # '1m', '5m', '15m', '1h', '4h', '1d'
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    
    # Relationships
    token = relationship('Token', back_populates='ohlcv_data')
    features = relationship('Feature', back_populates='ohlcv')
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('token_id', 'timestamp', 'resolution', name='unique_token_time_res'),
    )
    
    def __repr__(self):
        return f"<OHLCV(token='{self.token.symbol}', timestamp='{self.timestamp}', close='{self.close}')>"

class SocialMetrics(Base):
    __tablename__ = 'social_metrics'
    
    id = Column(Integer, primary_key=True)
    token_id = Column(Integer, ForeignKey('tokens.token_id'))
    timestamp = Column(DateTime, nullable=False)
    resolution = Column(String(10), nullable=False)  # '1h', '1d', etc.
    
    # Social metrics from LunarCrush
    contributors_active = Column(Integer)  # number of unique social accounts with interactions
    contributors_created = Column(Integer)  # number of unique accounts creating posts
    interactions = Column(Integer)  # all measurable social interactions
    posts_active = Column(Integer)  # number of posts with interactions
    posts_created = Column(Integer)  # number of new posts created
    sentiment = Column(Float)  # percentage of positive sentiment (0-100)
    spam = Column(Integer)  # number of spam posts detected
    
    # Market metrics included in social data
    alt_rank = Column(Integer)  # LunarCrush ranking
    circulating_supply = Column(Float)
    close_price = Column(Float)
    galaxy_score = Column(Integer)  # LunarCrush proprietary score
    market_cap = Column(Float)
    market_dominance = Column(Float)  # percent of total market cap
    volume_24h = Column(Float)  # trading volume in USD
    social_dominance = Column(Float)  # percent of total social volume
    
    # Relationships
    token = relationship('Token', back_populates='social_metrics')
    
    # Unique constraint for token+timestamp+resolution
    __table_args__ = (
        UniqueConstraint('token_id', 'timestamp', 'resolution', name='unique_social_time_res'),
    )
    
    def __repr__(self):
        return f"<SocialMetrics(token='{self.token.symbol}', timestamp='{self.timestamp}', sentiment='{self.sentiment}')>"

class Feature(Base):
    __tablename__ = 'features'
    
    feature_id = Column(Integer, primary_key=True)
    ohlcv_id = Column(Integer, ForeignKey('ohlcv.ohlcv_id'))
    ma7 = Column(Float)
    ma20 = Column(Float)
    ma50 = Column(Float)
    ema12 = Column(Float)
    ema26 = Column(Float)
    macd = Column(Float)
    macd_signal = Column(Float)
    macd_hist = Column(Float)
    rsi = Column(Float)
    bb_upper = Column(Float)
    bb_middle = Column(Float)
    bb_lower = Column(Float)
    vol_change_pct = Column(Float)
    price_change_1d = Column(Float)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    ohlcv = relationship('OHLCV', back_populates='features')
    
    def __repr__(self):
        return f"<Feature(ohlcv_id='{self.ohlcv_id}')>"

class TradeRecord(Base):
    __tablename__ = 'trade_records'
    
    trade_id = Column(Integer, primary_key=True)
    token_id = Column(Integer, ForeignKey('tokens.token_id'))
    timestamp = Column(DateTime, nullable=False)
    action = Column(String(10), nullable=False)  # 'buy', 'sell', 'short', 'cover'
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    amount_usd = Column(Float)
    fee = Column(Float)
    position = Column(String(10))  # 'long', 'short', 'neutral'
    reason = Column(String(255))
    tx_signature = Column(String(88))
    success = Column(Boolean, default=True)
    
    # Relationships
    token = relationship('Token')
    
    def __repr__(self):
        return f"<TradeRecord(token='{self.token.symbol}', action='{self.action}', price='{self.price}')>"

class ModelPrediction(Base):
    __tablename__ = 'model_predictions'
    
    prediction_id = Column(Integer, primary_key=True)
    token_id = Column(Integer, ForeignKey('tokens.token_id'))
    timestamp = Column(DateTime, nullable=False)
    predicted_price = Column(Float, nullable=False)
    actual_price = Column(Float)
    horizon = Column(Integer, nullable=False)  # prediction horizon in time intervals
    model_version = Column(String(100))
    confidence = Column(Float)
    error = Column(Float)
    
    # Relationships
    token = relationship('Token')
    
    def __repr__(self):
        return f"<ModelPrediction(token='{self.token.symbol}', predicted_price='{self.predicted_price}')>"

class ModelEvaluation(Base):
    __tablename__ = 'model_evaluations'
    
    evaluation_id = Column(Integer, primary_key=True)
    model_version = Column(String(100), nullable=False)
    token_id = Column(Integer, ForeignKey('tokens.token_id'))
    timestamp = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    optimization_target = Column(String(50))  # profit, direction, combined, mse
    
    # Standard ML metrics
    mse = Column(Float)
    rmse = Column(Float)
    mae = Column(Float)
    r2 = Column(Float)
    direction_accuracy = Column(Float)
    
    # Profit-oriented metrics
    total_return = Column(Float)
    buy_hold_return = Column(Float)
    win_rate = Column(Float)
    sharpe_ratio = Column(Float)
    max_drawdown = Column(Float)
    total_trades = Column(Integer)
    
    # Relationships
    token = relationship('Token')
    
    def __repr__(self):
        return f"<ModelEvaluation(model_version='{self.model_version}', token='{self.token.symbol}', total_return='{self.total_return}')>"

# Function to get token by symbol or address
def get_token_by_symbol(symbol, session):
    """Get token by symbol (case insensitive)"""
    return session.query(Token).filter(Token.symbol.ilike(symbol)).first()

def get_token_by_address(address, session):
    """Get token by address"""
    return session.query(Token).filter(Token.address == address).first()

def get_token_address(symbol, session):
    """Get token address by symbol"""
    token = get_token_by_symbol(symbol, session)
    return token.address if token else None

# Database connection setup
def get_engine(user='tradinguser', password='password', host='localhost', database='tradingbot'):
    # Check if DB_USE_SQLITE environment variable is set
    if os.getenv('DB_USE_SQLITE', 'false').lower() in ('true', '1', 't'):
        # Use SQLite instead of PostgreSQL
        db_dir = os.path.join(os.getcwd(), 'data')
        os.makedirs(db_dir, exist_ok=True)
        sqlite_path = os.path.join(db_dir, 'tradingbot.db')
        return create_engine(f'sqlite:///{sqlite_path}')
    else:
        # Use PostgreSQL (original behavior)
        return create_engine(f'postgresql://{user}:{password}@{host}/{database}')

def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    return engine

def get_session():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()

# Legacy code disabled - tokens are now managed by production_db.py 