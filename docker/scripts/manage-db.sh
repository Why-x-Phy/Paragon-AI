#!/bin/bash

# =============================================================================
# Calvin AI Database Management Script
# =============================================================================

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$DOCKER_DIR")"
BACKUP_DIR="/opt/calvin/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Environment detection
detect_environment() {
    if [[ -f "$PROJECT_ROOT/.env.dev" ]]; then
        ENV="dev"
        COMPOSE_FILE="docker-compose.dev.yml"
        DB_CONTAINER="calvin-timescaledb-dev"
        REDIS_CONTAINER="calvin-redis-dev"
        DB_NAME="calvin_trading_dev"
        DB_USER="calvin_dev"
    elif [[ -f "$PROJECT_ROOT/.env.prod" ]]; then
        ENV="prod"
        COMPOSE_FILE="docker-compose.prod.yml"
        DB_CONTAINER="calvin-timescaledb-primary"
        REDIS_CONTAINER="calvin-redis-master"
        DB_NAME="calvin_trading"
        DB_USER="calvin_prod"
    else
        log_error "No environment configuration found (.env.dev or .env.prod)"
        exit 1
    fi
    
    log_info "Detected environment: $ENV"
}

# Check if Docker containers are running
check_containers() {
    if ! docker ps --format "table {{.Names}}" | grep -q "$DB_CONTAINER"; then
        log_error "Database container $DB_CONTAINER is not running"
        log_info "Start with: docker-compose -f $DOCKER_DIR/$COMPOSE_FILE up -d"
        exit 1
    fi
}

# Database backup
backup_database() {
    log_info "Starting database backup..."
    
    # Ensure backup directory exists
    mkdir -p "$BACKUP_DIR"
    
    # Create backup filename
    BACKUP_FILE="$BACKUP_DIR/calvin_${ENV}_${TIMESTAMP}.sql.gz"
    
    # Perform backup
    log_info "Creating backup: $BACKUP_FILE"
    docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"
    
    if [[ $? -eq 0 ]]; then
        log_success "Database backup completed: $BACKUP_FILE"
        
        # Get backup size
        BACKUP_SIZE=$(ls -lh "$BACKUP_FILE" | awk '{print $5}')
        log_info "Backup size: $BACKUP_SIZE"
        
        # Cleanup old backups (keep last 30 days)
        log_info "Cleaning up old backups (keeping last 30 days)..."
        find "$BACKUP_DIR" -name "calvin_${ENV}_*.sql.gz" -mtime +30 -delete
        
    else
        log_error "Database backup failed"
        exit 1
    fi
}

# Database restore
restore_database() {
    local backup_file="$1"
    
    if [[ -z "$backup_file" ]]; then
        log_error "Usage: $0 restore <backup_file>"
        exit 1
    fi
    
    if [[ ! -f "$backup_file" ]]; then
        log_error "Backup file not found: $backup_file"
        exit 1
    fi
    
    log_warning "This will REPLACE the current database with the backup!"
    read -p "Are you sure you want to continue? (y/N): " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Restore cancelled"
        exit 0
    fi
    
    log_info "Restoring database from: $backup_file"
    
    # Drop and recreate database (be careful!)
    log_info "Dropping and recreating database..."
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -c "DROP DATABASE IF EXISTS $DB_NAME;"
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -c "CREATE DATABASE $DB_NAME;"
    
    # Restore from backup
    log_info "Restoring data..."
    gunzip -c "$backup_file" | docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME"
    
    if [[ $? -eq 0 ]]; then
        log_success "Database restore completed"
    else
        log_error "Database restore failed"
        exit 1
    fi
}

# Migration from SQLite (if needed)
migrate_from_sqlite() {
    local sqlite_file="$1"
    
    if [[ -z "$sqlite_file" ]]; then
        log_error "Usage: $0 migrate-sqlite <sqlite_file>"
        exit 1
    fi
    
    if [[ ! -f "$sqlite_file" ]]; then
        log_error "SQLite file not found: $sqlite_file"
        exit 1
    fi
    
    log_info "Migrating from SQLite: $sqlite_file"
    
    # This would require a custom migration script
    # For now, we'll just log that it's not implemented
    log_warning "SQLite migration not yet implemented"
    log_info "You'll need to export your SQLite data and import manually"
}

# Health check
health_check() {
    log_info "Performing health check..."
    
    # Check database connectivity
    log_info "Checking database connectivity..."
    if docker exec "$DB_CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" > /dev/null 2>&1; then
        log_success "Database: Connected"
    else
        log_error "Database: Connection failed"
        return 1
    fi
    
    # Check Redis connectivity
    log_info "Checking Redis connectivity..."
    if docker exec "$REDIS_CONTAINER" redis-cli ping > /dev/null 2>&1; then
        log_success "Redis: Connected"
    else
        log_error "Redis: Connection failed"
        return 1
    fi
    
    # Check database size
    DB_SIZE=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT pg_size_pretty(pg_database_size('$DB_NAME'));")
    log_info "Database size: $DB_SIZE"
    
    # Check table counts
    log_info "Table row counts:"
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
        SELECT 
            schemaname,
            tablename,
            n_tup_ins as inserts,
            n_tup_upd as updates,
            n_tup_del as deletes,
            n_live_tup as live_rows
        FROM pg_stat_user_tables 
        ORDER BY n_live_tup DESC;
    "
    
    # Check recent activity
    log_info "Recent database activity (last 24 hours):"
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
        SELECT 
            COUNT(*) as ohlcv_records
        FROM ohlcv 
        WHERE created_at > NOW() - INTERVAL '24 hours';
    "
    
    log_success "Health check completed"
}

# Database statistics
show_stats() {
    log_info "Database Statistics:"
    
    # Connection stats
    log_info "Active connections:"
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
        SELECT 
            state,
            COUNT(*) as count
        FROM pg_stat_activity 
        WHERE datname = '$DB_NAME'
        GROUP BY state;
    "
    
    # Table sizes
    log_info "Table sizes:"
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
        SELECT 
            schemaname,
            tablename,
            pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
        FROM pg_tables 
        WHERE schemaname = 'public'
        ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
    "
    
    # TimescaleDB hypertables
    if docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1 FROM pg_extension WHERE extname = 'timescaledb';" | grep -q "1"; then
        log_info "TimescaleDB hypertables:"
        docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
            SELECT 
                hypertable_name,
                num_chunks,
                table_size,
                index_size,
                total_size
            FROM timescaledb_information.hypertables;
        "
    fi
    
    # Redis stats
    log_info "Redis statistics:"
    docker exec "$REDIS_CONTAINER" redis-cli info memory | grep -E "used_memory_human|used_memory_peak_human"
    docker exec "$REDIS_CONTAINER" redis-cli info stats | grep -E "total_commands_processed|instantaneous_ops_per_sec"
}

# Initialize database (run migrations)
init_database() {
    log_info "Initializing database..."
    
    # The database should be initialized automatically via docker-entrypoint-initdb.d
    # But we can check if tables exist and create them if not
    
    # Check if tables exist
    TABLE_COUNT=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';")
    
    if [[ "$TABLE_COUNT" -gt 0 ]]; then
        log_success "Database already initialized ($TABLE_COUNT tables found)"
    else
        log_warning "Database appears empty, tables should be created automatically on first startup"
    fi
    
    # Verify TimescaleDB extension
    if docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1 FROM pg_extension WHERE extname = 'timescaledb';" | grep -q "1"; then
        log_success "TimescaleDB extension installed"
    else
        log_error "TimescaleDB extension not found"
    fi
}

# Reset database (dangerous!)
reset_database() {
    log_warning "This will COMPLETELY RESET the database, deleting ALL data!"
    read -p "Type 'RESET' to confirm: " confirmation
    
    if [[ "$confirmation" != "RESET" ]]; then
        log_info "Reset cancelled"
        exit 0
    fi
    
    log_info "Resetting database..."
    
    # Stop containers
    docker-compose -f "$DOCKER_DIR/$COMPOSE_FILE" down
    
    # Remove volumes
    docker volume prune -f
    
    # Start containers
    docker-compose -f "$DOCKER_DIR/$COMPOSE_FILE" up -d
    
    # Wait for database to be ready
    log_info "Waiting for database to be ready..."
    sleep 30
    
    log_success "Database reset completed"
}

# Show usage
show_usage() {
    echo "Calvin AI Database Management Script"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  backup                  Create database backup"
    echo "  restore <file>          Restore from backup file"
    echo "  migrate-sqlite <file>   Migrate from SQLite database"
    echo "  health                  Perform health check"
    echo "  stats                   Show database statistics"
    echo "  init                    Initialize/verify database setup"
    echo "  reset                   Reset database (DANGEROUS!)"
    echo "  help                    Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 backup"
    echo "  $0 restore /opt/calvin/backups/calvin_dev_20231201_120000.sql.gz"
    echo "  $0 health"
    echo ""
}

# Main script
main() {
    detect_environment
    
    case "${1:-help}" in
        backup)
            check_containers
            backup_database
            ;;
        restore)
            check_containers
            restore_database "$2"
            ;;
        migrate-sqlite)
            check_containers
            migrate_from_sqlite "$2"
            ;;
        health)
            check_containers
            health_check
            ;;
        stats)
            check_containers
            show_stats
            ;;
        init)
            check_containers
            init_database
            ;;
        reset)
            reset_database
            ;;
        help|--help|-h)
            show_usage
            ;;
        *)
            log_error "Unknown command: $1"
            show_usage
            exit 1
            ;;
    esac
}

# Run main function
main "$@" 