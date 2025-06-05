#!/bin/bash

# ===========================================================================
# Calvin AI Development Environment Setup Script
# ===========================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

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

# Load environment variables
load_environment() {
    local env_file="$PROJECT_ROOT/.env.dev"
    
    if [[ -f "$env_file" ]]; then
        log_info "Loading environment from $env_file"
        # Filter only valid variable assignments and export them
        export $(cat "$env_file" | grep -v '^#' | grep -v '^$' | sed 's/#.*//' | grep '=' | xargs)
        log_success "Environment variables loaded"
    else
        log_error "Environment file not found: $env_file"
        exit 1
    fi
}

# Health check for docker services
health_check() {
    log_info "Performing health checks..."
    
    # Check if Docker is running
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker is not running. Please start Docker first."
        exit 1
    fi
    
    # Check containers
    local containers=("calvin-timescaledb-dev" "calvin-redis-dev" "calvin-pgbouncer-dev")
    
    for container in "${containers[@]}"; do
        if docker ps --format "table {{.Names}}" | grep -q "^${container}$"; then
            log_success "✓ $container is running"
        else
            log_warning "⚠ $container is not running"
        fi
    done
    
    # Test database connection
    if docker exec calvin-timescaledb-dev psql -U calvin_dev -d calvin_trading_dev -c "SELECT 1;" >/dev/null 2>&1; then
        log_success "✓ Database connection works"
    else
        log_error "✗ Database connection failed"
    fi
    
    # Test Redis connection
    if docker exec calvin-redis-dev redis-cli ping | grep -q "PONG"; then
        log_success "✓ Redis connection works"
    else
        log_error "✗ Redis connection failed"
    fi
}

# Development environment setup
setup_dev() {
    log_info "Setting up development environment..."
    
    cd "$PROJECT_ROOT/docker"
    
    # Stop any existing containers
    log_info "Stopping existing containers..."
    docker-compose -f docker-compose.dev.yml down --remove-orphans 2>/dev/null || true
    
    # Start development environment
    log_info "Starting development containers..."
    docker-compose -f docker-compose.dev.yml up -d
    
    # Wait for database to be ready
    log_info "Waiting for database to be ready..."
    sleep 10
    
    # Wait for TimescaleDB to be fully ready
    local retries=30
    while [ $retries -gt 0 ]; do
        if docker exec calvin-timescaledb-dev pg_isready -U calvin_dev >/dev/null 2>&1; then
            break
        fi
        log_info "Waiting for TimescaleDB... ($retries retries left)"
        sleep 2
        ((retries--))
    done
    
    if [ $retries -eq 0 ]; then
        log_error "TimescaleDB failed to start properly"
        exit 1
    fi
    
    log_success "Development environment started successfully"
    
    # Initialize tokens
    log_info "Initializing tokens..."
    initialize_tokens
    
    # Map LunarCrush IDs
    log_info "Mapping LunarCrush IDs..."
    map_lunarcrush_ids
    
    # Health check
    health_check
}

# Initialize tokens from BirdEye API
initialize_tokens() {
    log_info "Initializing tokens from BirdEye API..."
    
    # Load environment variables
    load_environment
    
    # Validate environment variables
    if [[ -z "$TRACKED_TOKENS" ]]; then
        log_error "TRACKED_TOKENS environment variable not set"
        exit 1
    fi
    
    if [[ -z "$BIRDEYE_API_KEY" ]]; then
        log_error "BIRDEYE_API_KEY environment variable not set"
        exit 1
    fi
    
    # Run Python token initialization script
    cd "$SCRIPT_DIR"
    
    if [[ -f "initialize_tokens.py" ]]; then
        log_info "Running token initialization script..."
        python3 initialize_tokens.py
        
        if [[ $? -eq 0 ]]; then
            log_success "Token initialization completed"
        else
            log_error "Token initialization failed"
            exit 1
        fi
    else
        log_error "Token initialization script not found: initialize_tokens.py"
        exit 1
    fi
}

# Map LunarCrush IDs for social data
map_lunarcrush_ids() {
    log_info "Mapping LunarCrush IDs for social data..."
    
    # Load environment variables
    load_environment
    
    # Validate LunarCrush API key
    if [[ -z "$LUNARCRUSH_API_KEY" ]]; then
        log_warning "LUNARCRUSH_API_KEY not set - skipping LunarCrush mapping"
        return 0
    fi
    
    # Run Python LunarCrush mapping script
    cd "$SCRIPT_DIR"
    
    if [[ -f "map_lunarcrush_ids.py" ]]; then
        log_info "Running LunarCrush ID mapping script..."
        python3 map_lunarcrush_ids.py
        
        if [[ $? -eq 0 ]]; then
            log_success "LunarCrush ID mapping completed"
        else
            log_warning "LunarCrush ID mapping failed (social data may be limited)"
        fi
    else
        log_error "LunarCrush mapping script not found: map_lunarcrush_ids.py"
    fi
}

# Stop development environment
stop_dev() {
    log_info "Stopping development environment..."
    
    cd "$PROJECT_ROOT/docker"
    docker-compose -f docker-compose.dev.yml down
    
    log_success "Development environment stopped"
}

# View logs
logs() {
    local service=$1
    cd "$PROJECT_ROOT/docker"
    
    if [[ -n "$service" ]]; then
        docker-compose -f docker-compose.dev.yml logs -f "$service"
    else
        docker-compose -f docker-compose.dev.yml logs -f
    fi
}

# Database management
db_shell() {
    docker exec -it calvin-timescaledb-dev psql -U calvin_dev -d calvin_trading_dev
}

db_status() {
    log_info "Database status:"
    
    # Show token status
    docker exec calvin-timescaledb-dev psql -U calvin_dev -d calvin_trading_dev -c "SELECT * FROM token_status ORDER BY status, symbol;"
    
    echo ""
    log_info "Table counts:"
    docker exec calvin-timescaledb-dev psql -U calvin_dev -d calvin_trading_dev -c "
        SELECT 
            'tokens' as table_name, COUNT(*) as count FROM tokens
        UNION ALL
        SELECT 'ohlcv', COUNT(*) FROM ohlcv
        UNION ALL  
        SELECT 'market_events', COUNT(*) FROM market_events
        UNION ALL
        SELECT 'positions', COUNT(*) FROM positions
        UNION ALL
        SELECT 'trades', COUNT(*) FROM trades;
    "
}

# Redis management
redis_shell() {
    docker exec -it calvin-redis-dev redis-cli
}

redis_status() {
    log_info "Redis status:"
    docker exec calvin-redis-dev redis-cli info replication
    docker exec calvin-redis-dev redis-cli dbsize
}

# Show usage information
usage() {
    echo "Calvin AI Development Setup Script"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  setup        - Setup complete development environment"
    echo "  stop         - Stop development environment"
    echo "  health       - Run health checks"
    echo "  tokens       - Initialize tokens from BirdEye API"
    echo "  lunarcrush   - Map LunarCrush IDs for social data"
    echo "  logs [svc]   - Show logs (optional service name)"
    echo "  db-shell     - Open database shell"
    echo "  db-status    - Show database status"
    echo "  redis-shell  - Open Redis shell"
    echo "  redis-status - Show Redis status"
    echo ""
    echo "Examples:"
    echo "  $0 setup                 # Full environment setup"
    echo "  $0 tokens                # Just initialize tokens"
    echo "  $0 lunarcrush            # Just map LunarCrush IDs"
    echo "  $0 logs timescaledb      # Show database logs"
    echo "  $0 health                # Check system health"
}

# Main script logic
main() {
    local command=$1
    
    case $command in
        "setup")
            setup_dev
            ;;
        "stop")
            stop_dev
            ;;
        "health")
            health_check
            ;;
        "tokens")
            initialize_tokens
            ;;
        "lunarcrush")
            map_lunarcrush_ids
            ;;
        "logs")
            logs $2
            ;;
        "db-shell")
            db_shell
            ;;
        "db-status")
            db_status
            ;;
        "redis-shell")
            redis_shell
            ;;
        "redis-status")
            redis_status
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@" 