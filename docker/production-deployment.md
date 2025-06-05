# Calvin Production Deployment Guide

## Current Development vs Production

### Development (Current)
- Local Docker containers (TimescaleDB, Redis, PgBouncer)
- Single machine deployment
- Good for development and testing

### Production (Required)
- **Cannot use local containers** - need cloud infrastructure
- High availability and scaling requirements
- Professional backup and monitoring

## Production Deployment Options

### Option 1: Cloud-Managed Databases (RECOMMENDED) 🎯

#### **Why Recommended for Calvin**
- **High-frequency trading demands**: 99.9%+ uptime required
- **Time-series workload**: TimescaleDB expertise needed
- **Operational overhead**: Focus on algorithm development, not database administration
- **Compliance**: Professional backup, security, monitoring built-in

#### **AWS RDS PostgreSQL + TimescaleDB Extension (AWS-Only Solution)** ⭐ NEW OPTION
```yaml
# Fully AWS-Integrated Solution
Service: AWS RDS PostgreSQL with TimescaleDB Extension
Plan: db.t3.medium ($50/month) → db.r6g.xlarge ($300-600/month)
TimescaleDB Support: ✅ NATIVE SUPPORT (PostgreSQL 15.7+, 16.3+, 17.1+)
Features:
  - Native TimescaleDB extension (same as TimescaleDB Cloud)
  - AWS RDS automated backups and point-in-time recovery
  - Multi-AZ deployment for high availability
  - Read replicas for scaling
  - AWS VPC integration and security
  - Performance Insights and CloudWatch monitoring
  - Automatic minor version updates

Connection:
DATABASE_URL=postgresql://calvin_prod:password@calvin-prod.abc123.us-east-1.rds.amazonaws.com:5432/calvin_trading

Setup Commands:
# Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

# All existing Calvin schemas work unchanged!
# No migration needed from development TimescaleDB
```

#### **TimescaleDB Cloud** (Primary Database - Alternative)
```yaml
# Recommended Configuration
Service: TimescaleDB Cloud
Plan: Development ($95/month) → Production ($500-2000/month)
Resources: 2-4 vCPU, 8-16GB RAM, 200GB+ storage
Features:
  - Native TimescaleDB with all extensions
  - Automated backups (continuous + point-in-time recovery)
  - Automatic scaling and replication
  - Built-in monitoring and alerting
  - 99.9% SLA

Connection:
DATABASE_URL=postgresql://tsdbadmin:password@service-id.tsdb.cloud.timescale.com:5432/tsdb
```

#### **AWS ElastiCache Redis** (Caching Layer)
```yaml
Service: AWS ElastiCache Redis
Plan: cache.t3.micro ($15/month) → cache.r6g.large ($150/month)
Features:
  - Managed Redis cluster
  - Automatic failover
  - Backup and restore
  - VPC security

Connection:
REDIS_URL=redis://calvin-prod.abc123.cache.amazonaws.com:6379
```

### Option 2: Self-Hosted on Cloud Infrastructure

#### **AWS ECS Fargate Deployment**
```yaml
# Use existing docker-compose.prod.yml
Services:
  - TimescaleDB: ECS Fargate task with EFS storage
  - Redis: ECS Fargate task with EFS storage  
  - PgBouncer: ECS Fargate task
  - Calvin App: ECS Fargate task

Estimated Cost: $200-500/month
Benefits: Full control, existing Docker setup
Drawbacks: Operational overhead, backup management
```

#### **Kubernetes (EKS/GKE) Deployment**
```yaml
# Convert Docker Compose to Kubernetes manifests
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: timescaledb-primary
spec:
  serviceName: timescaledb
  replicas: 1
  template:
    spec:
      containers:
      - name: timescaledb
        image: timescale/timescaledb:latest-pg15
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi" 
            cpu: "2000m"
        volumeMounts:
        - name: timescale-storage
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: timescale-storage
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 100Gi
```

### Option 3: Hybrid Approach (Good Balance)

#### **Managed Database + Self-Hosted Application**
```yaml
Database: TimescaleDB Cloud ($95-500/month)
Cache: AWS ElastiCache Redis ($15-50/month)  
Application: 
  - AWS ECS Fargate for Calvin inference engine
  - AWS Lambda for periodic tasks
  - API Gateway for external integrations

Total Estimated Cost: $150-600/month
Benefits: 
  - Database expertise handled by experts
  - Application deployment flexibility
  - Cost optimization opportunities
```

## 🔥 **NEW: 100% AWS-Only Solution** 🔥

### **Complete AWS Integration (Recommended for AWS Users)**

```yaml
Architecture: Pure AWS Stack
Primary Database: AWS RDS PostgreSQL + TimescaleDB Extension
Cache: AWS ElastiCache Redis
Application: AWS ECS Fargate
Monitoring: CloudWatch + X-Ray
Networking: AWS VPC
Storage: AWS EFS (for logs/backups)
Secrets: AWS Secrets Manager

Monthly Cost: $150-500 (significantly cheaper than TimescaleDB Cloud)

Benefits:
  ✅ Single AWS bill and support
  ✅ Native AWS VPC integration
  ✅ AWS IAM for authentication  
  ✅ CloudWatch for unified monitoring
  ✅ AWS CLI for all management
  ✅ Cost optimization with Reserved Instances
  ✅ Native AWS backup and disaster recovery
```

### **AWS RDS PostgreSQL Configuration (Production-Ready + Cost-Optimized)**

#### **Development/Staging Configuration**
```yaml
# Cost: ~$50-80/month
Instance Class: db.t3.medium
  - vCPUs: 2
  - RAM: 4 GB
  - Network: Up to 5 Gbps
  - Cost: ~$50/month

Engine: PostgreSQL 16.6 (latest with TimescaleDB support)
Storage:
  - Type: gp3 (General Purpose SSD)
  - Size: 100 GB (auto-scaling enabled)
  - IOPS: 3,000 (baseline)
  - Throughput: 125 MiB/s
  - Cost: ~$11/month

Multi-AZ: No (single AZ for cost savings)
Backup:
  - Retention: 7 days
  - Window: 3:00-4:00 AM UTC
  - Point-in-time recovery: Enabled

Monitoring:
  - Performance Insights: Enabled (7 days free)
  - Enhanced Monitoring: 60-second intervals
```

#### **Production Configuration (Recommended)**
```yaml
# Cost: ~$200-300/month
Instance Class: db.r6g.large (memory-optimized for time-series)
  - vCPUs: 2
  - RAM: 16 GB (optimal for time-series workloads)
  - Network: Up to 10 Gbps
  - Cost: ~$200/month

Engine: PostgreSQL 16.6
Storage:
  - Type: gp3 (General Purpose SSD)
  - Size: 200 GB (auto-scaling up to 1000 GB)
  - IOPS: 6,000 (2x baseline for trading workloads)
  - Throughput: 250 MiB/s
  - Cost: ~$25/month

Multi-AZ: Yes (high availability for trading system)
  - Automatic failover
  - Cross-AZ replication
  - Additional cost: ~$200/month for standby

Backup:
  - Retention: 30 days (compliance requirement)
  - Window: 2:00-3:00 AM UTC (low trading activity)
  - Point-in-time recovery: Enabled
  - Snapshot sharing: Enabled
```

#### **High-Performance Production (Scale-Up Option)**
```yaml
# Cost: ~$500-700/month (for high-volume trading)
Instance Class: db.r6g.xlarge
  - vCPUs: 4
  - RAM: 32 GB
  - Network: Up to 10 Gbps
  - Cost: ~$400/month

Storage:
  - Type: io2 (Provisioned IOPS SSD)
  - Size: 500 GB
  - IOPS: 10,000 (guaranteed high performance)
  - Cost: ~$100/month

Read Replicas: 1-2 replicas for read scaling
  - Same instance class as primary
  - Cross-region option available
```

### **Exact AWS CLI Configuration Commands**

#### **Development Environment Setup**
```bash
# 1. Create subnet group for RDS
aws rds create-db-subnet-group \
  --db-subnet-group-name calvin-dev-subnet-group \
  --db-subnet-group-description "Calvin development subnet group" \
  --subnet-ids subnet-12345678 subnet-87654321

# 2. Create security group
aws ec2 create-security-group \
  --group-name calvin-dev-rds-sg \
  --description "Calvin development RDS security group" \
  --vpc-id vpc-12345678

# Allow PostgreSQL access from application subnets
aws ec2 authorize-security-group-ingress \
  --group-id sg-12345678 \
  --protocol tcp \
  --port 5432 \
  --source-group sg-87654321

# 3. Create RDS instance
aws rds create-db-instance \
  --db-instance-identifier calvin-dev-db \
  --db-instance-class db.t3.medium \
  --engine postgres \
  --engine-version 16.6 \
  --master-username calvin_dev \
  --master-user-password "$(aws secretsmanager get-random-password --password-length 20 --exclude-punctuation --output text --query RandomPassword)" \
  --allocated-storage 100 \
  --max-allocated-storage 1000 \
  --storage-type gp3 \
  --iops 3000 \
  --storage-throughput 125 \
  --vpc-security-group-ids sg-12345678 \
  --db-subnet-group-name calvin-dev-subnet-group \
  --backup-retention-period 7 \
  --preferred-backup-window "03:00-04:00" \
  --preferred-maintenance-window "sun:04:00-sun:05:00" \
  --auto-minor-version-upgrade \
  --publicly-accessible false \
  --storage-encrypted \
  --performance-insights-enabled \
  --performance-insights-retention-period 7 \
  --enable-cloudwatch-logs-exports postgresql \
  --deletion-protection false
```

#### **Production Environment Setup**
```bash
# 1. Create production subnet group (Multi-AZ)
aws rds create-db-subnet-group \
  --db-subnet-group-name calvin-prod-subnet-group \
  --db-subnet-group-description "Calvin production subnet group" \
  --subnet-ids subnet-11111111 subnet-22222222 subnet-33333333

# 2. Create production security group
aws ec2 create-security-group \
  --group-name calvin-prod-rds-sg \
  --description "Calvin production RDS security group" \
  --vpc-id vpc-12345678

# 3. Create RDS instance (Production)
aws rds create-db-instance \
  --db-instance-identifier calvin-prod-db \
  --db-instance-class db.r6g.large \
  --engine postgres \
  --engine-version 16.6 \
  --master-username calvin_prod \
  --manage-master-user-password \
  --allocated-storage 200 \
  --max-allocated-storage 1000 \
  --storage-type gp3 \
  --iops 6000 \
  --storage-throughput 250 \
  --vpc-security-group-ids sg-87654321 \
  --db-subnet-group-name calvin-prod-subnet-group \
  --multi-az \
  --backup-retention-period 30 \
  --preferred-backup-window "02:00-03:00" \
  --preferred-maintenance-window "sun:03:00-sun:04:00" \
  --auto-minor-version-upgrade \
  --publicly-accessible false \
  --storage-encrypted \
  --kms-key-id alias/rds-s3-import-export \
  --performance-insights-enabled \
  --performance-insights-retention-period 31 \
  --enable-cloudwatch-logs-exports postgresql \
  --monitoring-interval 60 \
  --monitoring-role-arn arn:aws:iam::123456789012:role/rds-monitoring-role \
  --deletion-protection true \
  --copy-tags-to-snapshot
```

### **PostgreSQL Configuration Parameters**

#### **Custom Parameter Group for Trading Workloads**
```bash
# 1. Create custom parameter group
aws rds create-db-parameter-group \
  --db-parameter-group-name calvin-trading-params \
  --db-parameter-group-family postgres16 \
  --description "Calvin trading optimized parameters"

# 2. Configure parameters for time-series performance
aws rds modify-db-parameter-group \
  --db-parameter-group-name calvin-trading-params \
  --parameters \
    "ParameterName=shared_preload_libraries,ParameterValue=timescaledb,ApplyMethod=pending-reboot" \
    "ParameterName=max_connections,ParameterValue=200,ApplyMethod=immediate" \
    "ParameterName=shared_buffers,ParameterValue={DBInstanceClassMemory/4},ApplyMethod=pending-reboot" \
    "ParameterName=effective_cache_size,ParameterValue={DBInstanceClassMemory*3/4},ApplyMethod=immediate" \
    "ParameterName=random_page_cost,ParameterValue=1.1,ApplyMethod=immediate" \
    "ParameterName=checkpoint_completion_target,ParameterValue=0.9,ApplyMethod=immediate" \
    "ParameterName=wal_buffers,ParameterValue=16MB,ApplyMethod=pending-reboot" \
    "ParameterName=work_mem,ParameterValue=4MB,ApplyMethod=immediate" \
    "ParameterName=maintenance_work_mem,ParameterValue=512MB,ApplyMethod=immediate" \
    "ParameterName=synchronous_commit,ParameterValue=on,ApplyMethod=immediate" \
    "ParameterName=commit_delay,ParameterValue=0,ApplyMethod=immediate" \
    "ParameterName=commit_siblings,ParameterValue=5,ApplyMethod=immediate" \
    "ParameterName=log_statement,ParameterValue=mod,ApplyMethod=immediate" \
    "ParameterName=log_min_duration_statement,ParameterValue=1000,ApplyMethod=immediate"

# 3. Apply parameter group to instance
aws rds modify-db-instance \
  --db-instance-identifier calvin-prod-db \
  --db-parameter-group-name calvin-trading-params \
  --apply-immediately false
```

### **Security and Network Configuration**

#### **VPC and Security Setup**
```bash
# 1. Create dedicated VPC for Calvin (optional)
aws ec2 create-vpc \
  --cidr-block 10.0.0.0/16 \
  --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=calvin-prod-vpc}]'

# 2. Create subnets (Multi-AZ for production)
aws ec2 create-subnet \
  --vpc-id vpc-12345678 \
  --cidr-block 10.0.1.0/24 \
  --availability-zone us-east-1a \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=calvin-db-subnet-1a}]'

aws ec2 create-subnet \
  --vpc-id vpc-12345678 \
  --cidr-block 10.0.2.0/24 \
  --availability-zone us-east-1b \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=calvin-db-subnet-1b}]'

# 3. Security Group Rules (Principle of Least Privilege)
aws ec2 authorize-security-group-ingress \
  --group-id sg-12345678 \
  --protocol tcp \
  --port 5432 \
  --source-group sg-app-tier \
  --group-owner-id 123456789012

# 4. Create secrets for database credentials
aws secretsmanager create-secret \
  --name calvin/prod/database \
  --description "Calvin production database credentials" \
  --secret-string '{"username":"calvin_prod","password":"secure_random_password"}'
```

### **Cost Optimization Settings**

#### **Reserved Instance Recommendations**
```yaml
# 1-Year Term, No Upfront (Balanced)
Development: 
  - Instance: db.t3.medium Reserved = ~$300/year (save 40%)
  - Break-even: 7 months usage

Production:
  - Instance: db.r6g.large Reserved = ~$1,500/year (save 40%)
  - Break-even: 7 months usage

# 3-Year Term, Partial Upfront (Maximum Savings)
Production:
  - Instance: db.r6g.large = ~$2,800 total (save 60%)
  - Monthly: ~$77/month effective cost
```

#### **Auto-Scaling Configuration**
```bash
# Enable storage auto-scaling
aws rds modify-db-instance \
  --db-instance-identifier calvin-prod-db \
  --max-allocated-storage 1000 \
  --apply-immediately false
```

### **Monitoring and Alerting Setup**

#### **CloudWatch Alarms for Trading System**
```bash
# 1. Database CPU utilization
aws cloudwatch put-metric-alarm \
  --alarm-name "Calvin-DB-CPU-High" \
  --alarm-description "Database CPU utilization high" \
  --metric-name CPUUtilization \
  --namespace AWS/RDS \
  --statistic Average \
  --period 300 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2 \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:calvin-alerts \
  --dimensions Name=DBInstanceIdentifier,Value=calvin-prod-db

# 2. Database connection count
aws cloudwatch put-metric-alarm \
  --alarm-name "Calvin-DB-Connections-High" \
  --alarm-description "Database connection count high" \
  --metric-name DatabaseConnections \
  --namespace AWS/RDS \
  --statistic Average \
  --period 300 \
  --threshold 150 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2 \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:calvin-alerts \
  --dimensions Name=DBInstanceIdentifier,Value=calvin-prod-db

# 3. Storage space monitoring
aws cloudwatch put-metric-alarm \
  --alarm-name "Calvin-DB-Storage-Low" \
  --alarm-description "Database free storage space low" \
  --metric-name FreeStorageSpace \
  --namespace AWS/RDS \
  --statistic Average \
  --period 300 \
  --threshold 10737418240 \
  --comparison-operator LessThanThreshold \
  --evaluation-periods 1 \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:calvin-alerts \
  --dimensions Name=DBInstanceIdentifier,Value=calvin-prod-db
```

### **TimescaleDB-Specific Configuration**

#### **Post-Creation Setup Commands**
```sql
-- 1. Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 2. Configure TimescaleDB settings for trading data
SELECT timescaledb_pre_restore();

-- 3. Create hypertables for Calvin's time-series data
SELECT create_hypertable('price_data', 'timestamp', chunk_time_interval => INTERVAL '1 hour');
SELECT create_hypertable('ohlcv_1m', 'timestamp', chunk_time_interval => INTERVAL '1 day');
SELECT create_hypertable('ohlcv_1h', 'timestamp', chunk_time_interval => INTERVAL '7 days');

-- 4. Configure compression (save 90%+ storage)
ALTER TABLE price_data SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'symbol',
  timescaledb.compress_orderby = 'timestamp DESC'
);

-- 5. Enable automatic compression policy
SELECT add_compression_policy('price_data', INTERVAL '7 days');
SELECT add_compression_policy('ohlcv_1m', INTERVAL '30 days');
SELECT add_compression_policy('ohlcv_1h', INTERVAL '90 days');

-- 6. Configure retention policies
SELECT add_retention_policy('price_data', INTERVAL '1 year');
SELECT add_retention_policy('ohlcv_1m', INTERVAL '2 years');

-- 7. Optimize for trading queries
CREATE INDEX CONCURRENTLY idx_price_data_symbol_time 
ON price_data (symbol, timestamp DESC);

-- 8. Configure continuous aggregates for real-time analytics
CREATE MATERIALIZED VIEW ohlcv_5m
WITH (timescaledb.continuous) AS
SELECT 
  time_bucket(INTERVAL '5 minutes', timestamp) AS bucket,
  symbol,
  first(price, timestamp) as open,
  max(price) as high,
  min(price) as low,
  last(price, timestamp) as close,
  avg(price) as vwap,
  sum(volume) as volume
FROM price_data
GROUP BY bucket, symbol;

-- 9. Enable real-time aggregation
SELECT add_continuous_aggregate_policy('ohlcv_5m',
  start_offset => INTERVAL '1 hour',
  end_offset => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute');
```

### **Final Cost Summary (Balanced Production Setup)**

```yaml
Monthly Costs (Production-Ready):
├── RDS db.r6g.large (Multi-AZ): $400
├── Storage (200GB gp3, 6K IOPS): $25  
├── Backup storage (30 days): $15
├── Performance Insights: $0 (included)
├── Data transfer (within AZ): $0
└── Reserved Instance Savings: -$160 (40% off)
──────────────────────────────────────
Total Database Cost: $280/month

Additional AWS Services:
├── ElastiCache Redis (r6g.large): $150
├── ECS Fargate (2 vCPU, 4GB): $60
├── Application Load Balancer: $25
├── CloudWatch/Monitoring: $20
└── Secrets Manager: $5
──────────────────────────────────────
Total Infrastructure: $540/month

With Reserved Instances (1-year): $420/month
With Reserved Instances (3-year): $360/month
```

This configuration provides enterprise-grade reliability and performance while maintaining cost efficiency for Calvin's trading infrastructure.

## Migration Strategy

### Phase 1: Preparation
```bash
# 1. Export development data
docker exec calvin-timescaledb-dev pg_dump -U calvin_dev calvin_trading_dev > backup.sql

# 2. Test connection strings in production_db.py
# Update environment variables for cloud connections

# 3. Create production environment file
cp .env.dev .env.prod
# Update with production database URLs
```

### Phase 2: Database Migration

#### **Option A: AWS RDS + TimescaleDB (AWS-Only)**
```bash
# 1. Create RDS PostgreSQL instance (see AWS setup commands above)
# 2. Enable TimescaleDB extension
psql -h your-rds-endpoint -U calvin_prod -c "CREATE EXTENSION timescaledb;"

# 3. Import schema and data
psql -h your-rds-endpoint -U calvin_prod -d calvin_trading < backup.sql

# 4. Update connection string
DATABASE_URL=postgresql://calvin_prod:password@calvin-prod.abc123.us-east-1.rds.amazonaws.com:5432/calvin_trading
```

#### **Option B: TimescaleDB Cloud setup**
```bash
# 1. Create TimescaleDB Cloud instance
# 2. Import schema and data
# 3. Update connection strings
```

### Phase 3: Application Deployment
```bash
# Option 1: ECS Fargate
aws ecs create-cluster --cluster-name calvin-prod

# Option 2: Kubernetes
kubectl create namespace calvin-prod
kubectl apply -f k8s/

# Option 3: Docker Swarm (simple)
docker swarm init
docker stack deploy -c docker-compose.prod.yml calvin
```

## Cost Estimates (Monthly)

### 🔥 **AWS-Only (NEW RECOMMENDED)**
- AWS RDS PostgreSQL (TimescaleDB): $50-300
- AWS ElastiCache Redis: $15-50  
- Application hosting (ECS): $50-200
- **Total: $115-550/month**
- **Benefits: Single vendor, unified billing, cost optimization**

### Managed (TimescaleDB Cloud)
- TimescaleDB Cloud: $95-500
- AWS ElastiCache: $15-50  
- Application hosting (ECS): $50-200
- **Total: $160-750/month**

### Self-Hosted
- AWS EC2 instances: $100-300
- EBS storage: $20-50
- Load balancer: $25
- **Total: $145-375/month**
- **Plus: Operational overhead (your time)**

### Hybrid
- TimescaleDB Cloud: $95-500
- Redis Cloud: $15-30
- Application (Serverless): $20-100
- **Total: $130-630/month**

## Recommendation for Calvin

### 🎯 **NEW: AWS-Only Approach (BEST for AWS Users)**
1. **AWS RDS PostgreSQL + TimescaleDB Extension** for primary database
2. **AWS ElastiCache Redis** for caching
3. **AWS ECS Fargate** for Calvin application

**Benefits**:
- ✅ **Lowest cost**: 20-30% cheaper than TimescaleDB Cloud
- ✅ **Single vendor**: All AWS, unified billing and support
- ✅ **Native integration**: VPC, IAM, CloudWatch, etc.
- ✅ **Same TimescaleDB features**: Extension is identical to TimescaleDB Cloud
- ✅ **No vendor lock-in**: Standard PostgreSQL with extensions
- ✅ **AWS ecosystem**: Reserved Instances, Spot pricing, etc.

**Migration Path**:
1. Set up AWS RDS PostgreSQL instance
2. Enable TimescaleDB extension (`CREATE EXTENSION timescaledb;`)
3. Migrate existing data (no schema changes needed!)
4. Update production_db.py connection strings
5. Deploy Calvin app to ECS Fargate
6. Monitor and optimize

**Monthly Cost**: ~$150-400 for production-ready setup

### Alternative: **Start with Managed Approach**
1. **TimescaleDB Cloud** for primary database
2. **AWS ElastiCache** for Redis caching
3. **AWS ECS Fargate** for Calvin application

**Monthly Cost**: ~$200-500 for production-ready setup 