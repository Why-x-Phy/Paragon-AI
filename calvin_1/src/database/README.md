# Calvin AI Database Infrastructure

Complete production-ready database infrastructure for Calvin AI trading system built on **TimescaleDB + Redis** with Docker orchestration.

## 🏗️ Architecture Overview

```
Calvin AI Database Stack:
├── TimescaleDB (PostgreSQL + time-series)
│   ├── Primary Database (read/write)
│   ├── Read Replica (analytics)
│   └── PgBouncer (connection pooling)
├── Redis (caching + pub/sub)
│   ├── Price caching (5min TTL)
│   ├── Position monitoring
│   └── Real-time events
└── Production Services
    ├── WebSocket → Real-time Storage
    ├── Hourly API → Feature Pipeline
    └── Position Management
```

## 📊 Database Schema

### Core Tables

**`tokens`** - Token registry and metadata
- `token_id`, `address`, `symbol`, `name`, `decimals`
- Pre-loaded with SOL, USDC, BONK, JUP, CALVIN

**`ohlcv`** - Time-series price data (Hypertable)
- `time`, `token_id`, `resolution`, `open`, `high`, `low`, `close`, `volume`
- Automatic compression after 7 days
- 2-year retention policy
- Optimized indexes for time-series queries

**`positions`** - Trading position tracking
- Entry/exit details, P&L tracking, risk management
- Stop-loss and take-profit monitoring
- Model prediction confidence tracking

**`trades`** - Individual trade executions  
- DEX integration details, slippage tracking
- Transaction hashes, processing times
- Fee tracking and performance metrics

**`model_predictions`** - FastDQN model outputs
- Prediction confidence, feature vectors
- Outcome validation and accuracy tracking

**`market_events`** - Future orderbook/transaction data
- Flexible JSON structure for event data
- Whale movement detection, impact scoring

**`system_health`** - System monitoring
- Component health checks, error tracking
- Performance metrics, uptime monitoring

### Advanced Features

- **Continuous Aggregates**: Automatic 1-hour OHLCV from minute data
- **Real-time Views**: Latest prices, open positions, performance summary
- **Triggers**: Auto-update timestamps, P&L calculations
- **Functions**: Position P&L calculation, health monitoring

## 🚀 Quick Start

### 1. Environment Setup

```bash
# Copy environment template
cp .env.example .env.dev

# Configure your environment
nano .env.dev
```

Required environment variables:
- `BIRDEYE_API_KEY` - BirdEye WebSocket access
- `DB_PASSWORD_DEV` - Database password
- `REDIS_PASSWORD_DEV` - Redis password

### 2. Start Development Environment

```bash
# Start all services
docker-compose -f docker/docker-compose.dev.yml up -d

# Check status
docker-compose -f docker/docker-compose.dev.yml ps

# View logs
docker-compose -f docker/docker-compose.dev.yml logs -f
```

### 3. Verify Installation

```bash
# Run health check
docker/scripts/manage-db.sh health

# Check database stats
docker/scripts/manage-db.sh stats

# Access database
docker exec -it calvin-timescaledb-dev psql -U calvin_dev -d calvin_trading_dev
```

### 4. Initialize Data Pipeline

```python
# Python example
import asyncio
from calvin_1.src.database.production_db import get_db_manager
from calvin_1.src.data.websocket_feed import WebSocketPriceFeed
from calvin_1.src.data.realtime_storage import RealtimeDataStorage

async def main():
    # Initialize database
    db_manager = await get_db_manager()
    
    # Setup WebSocket feed
    websocket_feed = WebSocketPriceFeed(
        api_key="your_birdeye_api_key",
        chain="solana"
    )
    
    # Start real-time storage
    realtime_storage = RealtimeDataStorage(websocket_feed, db_manager)
    await realtime_storage.initialize()
    await realtime_storage.start()
    
    # Your trading logic here...
    
if __name__ == "__main__":
    asyncio.run(main())
```

## 🔧 Production Deployment

### Environment Configuration

```bash
# Production environment
cp .env.example .env.prod

# Configure production settings
# - Strong passwords
# - SSL certificates
# - Monitoring endpoints
# - Backup configuration
```

### Docker Compose Production

```bash
# Start production stack
docker-compose -f docker/docker-compose.prod.yml up -d

# With monitoring (optional)
docker-compose -f docker/docker-compose.prod.yml --profile monitoring up -d
```

### Security Considerations

1. **Database Security**
   - Strong passwords (>20 characters)
   - Connection encryption in production
   - Regular security updates

2. **Network Security**
   - Firewall rules for database ports
   - VPN/private network access
   - Rate limiting on API endpoints

3. **Data Protection**
   - Daily automated backups
   - Encryption at rest
   - GDPR/compliance considerations

## 📋 Database Management

### Backup & Restore

```bash
# Create backup
docker/scripts/manage-db.sh backup

# Restore from backup
docker/scripts/manage-db.sh restore /opt/calvin/backups/calvin_dev_20231201_120000.sql.gz

# List backups
ls -la /opt/calvin/backups/
```

### Health Monitoring

```bash
# System health check
docker/scripts/manage-db.sh health

# Database statistics
docker/scripts/manage-db.sh stats

# Initialize/verify setup
docker/scripts/manage-db.sh init
```

### Performance Optimization

**TimescaleDB Optimizations:**
- Automatic time-based partitioning (daily chunks)
- Compression for data older than 7 days
- Optimized indexes for time-series queries
- Connection pooling via PgBouncer

**Redis Optimizations:**
- LRU eviction policy for memory management
- Persistent storage with AOF + RDB
- Pipeline operations for batch updates
- TTL-based cache expiration

## 📡 Real-Time Data Pipeline

### WebSocket Integration

```python
# Configure WebSocket subscriptions
from calvin_1.src.data.websocket_feed import WebSocketPriceFeed, SubscriptionConfig

websocket_feed = WebSocketPriceFeed(api_key="your_key", chain="solana")

# Subscribe to price updates
config = SubscriptionConfig(
    subscription_type="SUBSCRIBE_PRICE",
    addresses=["So11111111111111111111111111111111111111112"]  # SOL
)
await websocket_feed.subscribe(config)
```

### Data Flow Architecture

```
BirdEye WebSocket → RealtimeDataStorage → TimescaleDB
                 ↘ Redis Cache ↗
                 ↘ Position Triggers ↗
```

**Real-time Processing:**
1. **Tick Ingestion**: WebSocket price updates queued
2. **Batch Processing**: Ticks processed in 100-item batches  
3. **Candle Aggregation**: 1-minute OHLCV generation
4. **Position Monitoring**: Stop-loss/take-profit triggers
5. **Caching**: Latest prices cached in Redis (5min TTL)

### Position Management

```python
# Monitor position triggers
from calvin_1.src.data.realtime_storage import PositionTrigger

async def handle_trigger(trigger: PositionTrigger, current_price: float):
    print(f"Position {trigger.position_id} {trigger.trigger_type} at {current_price}")
    # Execute trade logic here

realtime_storage.add_trigger_callback(handle_trigger)
```

## 🔍 Monitoring & Observability

### Built-in Monitoring

- **Health Checks**: Automated component health monitoring
- **Performance Metrics**: Database sizes, query performance
- **Error Tracking**: Comprehensive error logging and alerting
- **Resource Usage**: Memory, CPU, storage monitoring

### Optional Monitoring Stack

```bash
# Start with Grafana + Prometheus
docker-compose -f docker/docker-compose.prod.yml --profile monitoring up -d

# Access dashboards
open http://localhost:3000  # Grafana
open http://localhost:9090  # Prometheus
```

### Custom Metrics

```python
# Application metrics
stats = realtime_storage.get_statistics()
print(f"Ticks processed: {stats['ticks_processed']}")
print(f"Candles created: {stats['candles_created']}")
print(f"Triggers fired: {stats['triggers_fired']}")

# Database metrics  
db_stats = await db_manager.get_database_stats()
print(f"Table sizes: {db_stats['table_sizes']}")
print(f"Redis memory: {db_stats['redis']['used_memory']}")
```

## 🧪 Testing & Development

### Unit Tests

```bash
# Run database tests
cd calvin_1/src/database
python -m pytest test_production_db.py -v

# Run WebSocket tests  
cd calvin_1/src/data
python -m pytest test_websocket_feed.py -v
```

### Development Tools

```bash
# Access development database
docker exec -it calvin-timescaledb-dev psql -U calvin_dev -d calvin_trading_dev

# Redis CLI
docker exec -it calvin-redis-dev redis-cli

# Database admin interface (optional)
docker-compose -f docker/docker-compose.dev.yml --profile admin up -d
open http://localhost:8080  # Adminer
```

### Sample Data Generation

```python
# Generate test OHLCV data
from calvin_1.src.database.production_db import OHLCVData
from datetime import datetime, timedelta

# Create sample data
sample_data = [
    OHLCVData(
        time=datetime.utcnow() - timedelta(minutes=i),
        token_id=1,  # SOL
        resolution="1m",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000.0,
        data_source="test"
    )
    for i in range(60)  # 1 hour of minute data
]

# Insert test data
await db_manager.insert_ohlcv_data(sample_data)
```

## 🔄 Migration & Scaling

### Horizontal Scaling

**Read Replicas**: Production setup includes read replica for analytics
**Sharding**: TimescaleDB supports automatic partitioning
**Load Balancing**: PgBouncer handles connection distribution

### Vertical Scaling

```yaml
# Increase resources in docker-compose.yml
deploy:
  resources:
    limits:
      memory: 8G      # Increase memory
      cpus: '4.0'     # Increase CPU cores
```

### Data Migration

```bash
# Migrate from existing SQLite (if applicable)
docker/scripts/manage-db.sh migrate-sqlite path/to/old.db

# Export/import between environments
docker/scripts/manage-db.sh backup
# Transfer backup file
docker/scripts/manage-db.sh restore backup_file.sql.gz
```

## 🛠️ Troubleshooting

### Common Issues

**Connection Timeouts**:
```bash
# Check container status
docker-compose ps

# Check logs
docker-compose logs timescaledb
docker-compose logs redis
```

**Memory Issues**:
```bash
# Check memory usage
docker stats

# Adjust Redis memory limit
# Edit docker/redis/redis-dev.conf
maxmemory 512mb
```

**Performance Issues**:
```sql
-- Check slow queries
SELECT query, mean_time, calls 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;

-- Check table sizes
SELECT schemaname, tablename, 
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables 
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### Performance Tuning

**Database Optimization**:
- Adjust `shared_buffers` based on available RAM
- Increase `work_mem` for complex queries
- Configure `maintenance_work_mem` for maintenance operations

**Redis Optimization**:
- Set appropriate `maxmemory` policy
- Use pipelining for batch operations
- Monitor memory fragmentation

## 📚 API Reference

### Database Manager

```python
from calvin_1.src.database.production_db import get_db_manager

db_manager = await get_db_manager()

# Token operations
token = await db_manager.add_token("address", "SYMBOL", "Name")
token_info = db_manager.get_token_by_address("address")

# OHLCV operations
await db_manager.insert_ohlcv_data([ohlcv_data])
candles = await db_manager.get_ohlcv_data(token_id, "1m", start_time)
price = await db_manager.get_latest_price(token_id)

# Position operations
position_id = await db_manager.create_position(position_data)
await db_manager.update_position(position_id, {"status": "closed"})
positions = await db_manager.get_open_positions()

# Trade operations
trade_id = await db_manager.record_trade(trade_data)

# Health monitoring
await db_manager.record_health_check("component", "healthy")
stats = await db_manager.get_database_stats()
```

### Real-time Storage

```python
from calvin_1.src.data.realtime_storage import RealtimeDataStorage

realtime_storage = RealtimeDataStorage(websocket_feed, db_manager)

# Initialize and start
await realtime_storage.initialize()
await realtime_storage.start()

# Monitor triggers
realtime_storage.add_trigger_callback(callback_function)
await realtime_storage.refresh_position_triggers()

# Statistics
stats = realtime_storage.get_statistics()
health = await realtime_storage.health_check()

# Stop gracefully
await realtime_storage.stop()
```

## 🎯 What's Next

**Phase 1.2B**: Hourly Inference Pipeline
- BirdEye REST API integration
- Cron job framework
- Feature engineering (pending `dataprocessor.py` recovery)

**Phase 1.3**: Position Management System  
- Stop-loss/take-profit execution
- Risk monitoring and alerts
- P&L calculation and tracking

**Phase 2**: Model Serving Infrastructure
- FastDQN model loading and inference
- Ensemble coordination system
- Real-time prediction pipeline

---

**Built with ❤️ for Calvin AI Trading System** 