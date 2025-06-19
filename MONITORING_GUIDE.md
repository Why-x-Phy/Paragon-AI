# Calvin AI Monitoring Guide
## Grafana + Prometheus Setup and Usage

This guide explains how to use Grafana and Prometheus to monitor your Calvin AI trading system.

## 🚀 Quick Start

### 1. Start Monitoring Stack
```bash
# Start production database + monitoring
cd docker
docker-compose -f docker-compose.prod.yml --env-file .env.prod --profile monitoring up -d
```

### 2. Access the Tools
- **Grafana**: http://localhost:3000
  - Username: `admin` 
  - Password: `${GRAFANA_PASSWORD}` (from your .env.prod file)
- **Prometheus**: http://localhost:9090

---

## 📊 What Each Tool Does

### **Prometheus** - Metrics Collection
- **Purpose**: Collects and stores time-series metrics
- **Data Sources**: Database performance, Redis stats, Calvin AI app metrics
- **Use Cases**: Query raw metrics, set up alerts, data source for Grafana

### **Grafana** - Visualization & Dashboards  
- **Purpose**: Creates beautiful dashboards and charts
- **Data Sources**: Prometheus metrics + direct TimescaleDB queries
- **Use Cases**: Trading performance dashboards, system health monitoring, alerts

---

## 🎯 Key Metrics to Monitor

### **1. Trading Performance Metrics**
```sql
-- In Grafana, query TimescaleDB directly:
SELECT 
  time_bucket('1 hour', timestamp) as time,
  symbol,
  avg(confidence) as avg_confidence,
  count(*) as signals_count,
  sum(case when success then 1 else 0 end)::float / count(*) as win_rate
FROM portfolio_signals 
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY time, symbol
ORDER BY time DESC;
```

### **2. Database Performance**
- **Connection Pool**: PgBouncer active/waiting connections
- **Query Performance**: Slow query counts, average response time
- **Storage**: Disk usage, TimescaleDB chunk compression

### **3. System Health**
- **Memory Usage**: Python process memory, Redis memory
- **CPU Usage**: Inference processing load
- **Network**: WebSocket connection stability

---

## 📈 Essential Dashboards

### **Dashboard 1: Calvin AI Trading Overview**

**Create New Dashboard** → **Add Panel** → **Use these queries:**

```promql
# Portfolio Value Over Time (from TimescaleDB)
SELECT 
  time_bucket('15 minutes', timestamp) as time,
  avg(portfolio_value_usdc) as value
FROM portfolio_cycles 
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY time
ORDER BY time;

# Signals Generated Per Hour (from TimescaleDB)
SELECT 
  time_bucket('1 hour', timestamp) as time,
  count(*) as signals
FROM portfolio_signals 
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY time
ORDER BY time;

# Win Rate by Token (from TimescaleDB)
SELECT 
  symbol,
  count(*) as total_signals,
  avg(confidence) as avg_confidence,
  sum(case when success then 1 else 0 end)::float / count(*) as win_rate
FROM portfolio_signals 
WHERE timestamp > NOW() - INTERVAL '24 hours'
  AND success IS NOT NULL
GROUP BY symbol
ORDER BY win_rate DESC;
```

### **Dashboard 2: System Performance**

```promql
# Database Connections (if postgres_exporter enabled)
pg_stat_database_numbackends{datname="calvin_trading"}

# Redis Memory Usage (if redis_exporter enabled)  
redis_memory_used_bytes / redis_memory_max_bytes * 100

# Calvin AI Process Health (when app metrics implemented)
calvin_inference_duration_seconds
calvin_trade_execution_duration_seconds
calvin_websocket_connections_active
```

---

## 🚨 Setting Up Alerts

### **1. In Grafana - Create Alert Rules**

**Alerting** → **Alert Rules** → **New Rule**

**Critical Trading Alerts:**
```promql
# Low Win Rate Alert
(
  sum(rate(calvin_signals_success_total[1h])) / 
  sum(rate(calvin_signals_total[1h]))
) < 0.4

# High Inference Latency Alert  
calvin_inference_duration_seconds > 10

# Database Connection Issues
pg_up != 1

# Redis Down Alert
redis_up != 1
```

### **2. Notification Channels**
- **Discord/Slack**: Get alerts in your trading channel
- **Email**: Critical system failures
- **PagerDuty**: Production incidents

---

## 🔧 Advanced Configuration

### **Add More Exporters (Optional)**

```yaml
# Add to docker-compose.prod.yml for more metrics:

postgres_exporter:
  image: prometheuscommunity/postgres-exporter
  environment:
    DATA_SOURCE_NAME: "postgresql://calvin_prod:${DB_PASSWORD_PROD}@timescaledb:5432/calvin_trading?sslmode=disable"
  ports:
    - "9187:9187"
  networks:
    - calvin-prod-network

redis_exporter:
  image: oliver006/redis_exporter
  environment:
    REDIS_ADDR: "redis://redis:6379"
    REDIS_PASSWORD: "${REDIS_PASSWORD_PROD}"
  ports:
    - "9121:9121"
  networks:
    - calvin-prod-network

node_exporter:
  image: prom/node-exporter
  ports:
    - "9100:9100"
  volumes:
    - /proc:/host/proc:ro
    - /sys:/host/sys:ro
    - /:/rootfs:ro
  command:
    - '--path.procfs=/host/proc'
    - '--path.rootfs=/rootfs'
    - '--path.sysfs=/host/sys'
    - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
```

---

## 📊 Sample Grafana Panels

### **Trading Performance Panel**
- **Visualization**: Time series
- **Query**: Portfolio value over time
- **Y-Axis**: USD value
- **Alerts**: Portfolio drawdown > 10%

### **Signal Success Rate Panel**  
- **Visualization**: Stat panel
- **Query**: Win rate calculation  
- **Thresholds**: Green >60%, Yellow 40-60%, Red <40%

### **Database Health Panel**
- **Visualization**: Gauge
- **Query**: Connection pool utilization
- **Max Value**: 100%
- **Alerts**: >90% utilization

---

## 🎯 Pro Tips

### **1. Custom Metrics in Calvin AI**
```python
# Add to your Calvin AI code:
from prometheus_client import Counter, Histogram, Gauge

# Trading metrics
SIGNALS_TOTAL = Counter('calvin_signals_total', 'Total signals generated', ['symbol', 'signal_type'])
SIGNALS_SUCCESS = Counter('calvin_signals_success_total', 'Successful signals', ['symbol'])
INFERENCE_DURATION = Histogram('calvin_inference_duration_seconds', 'Inference time')
PORTFOLIO_VALUE = Gauge('calvin_portfolio_value_usdc', 'Current portfolio value')

# In your trading code:
SIGNALS_TOTAL.labels(symbol=symbol, signal_type='BUY').inc()
INFERENCE_DURATION.observe(inference_time)
PORTFOLIO_VALUE.set(current_portfolio_value)
```

### **2. Dashboard Best Practices**
- **Time Range**: Default to 24h, allow 7d/30d selection
- **Refresh**: Auto-refresh every 30 seconds for live data
- **Annotations**: Mark important events (model updates, parameter changes)
- **Variables**: Create symbol dropdown for per-token analysis

### **3. Alert Management**
- **Severity Levels**: Critical (immediate), Warning (review needed), Info (FYI)
- **Notification Rules**: Different channels for different severities
- **Silence Rules**: Quiet known issues during maintenance

---

## 🚨 Troubleshooting

### **Grafana Issues**
```bash
# Check logs
docker logs calvin-grafana-prod

# Reset admin password
docker exec -it calvin-grafana-prod grafana-cli admin reset-admin-password newpassword

# Backup dashboards
docker exec -it calvin-grafana-prod grafana-cli admin export-dashboard
```

### **Prometheus Issues**
```bash
# Check config
docker exec -it calvin-prometheus-prod promtool check config /etc/prometheus/prometheus.yml

# Check targets
# Visit: http://localhost:9090/targets

# Query metrics manually
# Visit: http://localhost:9090/graph
```

### **Database Connection Issues**
```bash
# Test TimescaleDB connection
docker exec -it calvin-timescaledb-prod psql -U calvin_prod -d calvin_trading -c "SELECT now();"

# Check Grafana datasource
# Grafana → Configuration → Data Sources → Calvin-TimescaleDB → Test
```

---

## 📚 Useful Queries

### **Trading Analysis Queries**
```sql
-- Best performing tokens (last 24h)
SELECT 
  symbol,
  count(*) as signals,
  avg(confidence) as avg_confidence,
  stddev(predicted_change_pct) as volatility_prediction
FROM portfolio_signals 
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY symbol
ORDER BY avg_confidence DESC;

-- Hourly trading activity
SELECT 
  date_trunc('hour', timestamp) as hour,
  count(*) as total_signals,
  count(*) FILTER (WHERE signal_type = 'BUY') as buy_signals,
  count(*) FILTER (WHERE signal_type = 'SELL') as sell_signals
FROM portfolio_signals 
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY hour
ORDER BY hour DESC;

-- Portfolio performance by day
SELECT 
  date_trunc('day', timestamp) as day,
  first(portfolio_value_usdc, timestamp) as start_value,
  last(portfolio_value_usdc, timestamp) as end_value,
  (last(portfolio_value_usdc, timestamp) - first(portfolio_value_usdc, timestamp)) as daily_pnl
FROM portfolio_cycles 
WHERE timestamp > NOW() - INTERVAL '30 days'
GROUP BY day
ORDER BY day DESC;
```

This monitoring setup gives you **complete visibility** into your Calvin AI trading system! 🎯 