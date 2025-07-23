#!/bin/bash

# Calvin AI NAV Refresh Service Management Script
# Usage: ./manage-nav-refresh.sh [install|start|stop|restart|status|logs|uninstall]

SERVICE_NAME="calvin-nav-refresh"
SERVICE_FILE="calvin-nav-refresh.service"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

function print_usage() {
    echo "Usage: $0 [install|start|stop|restart|status|logs|uninstall]"
    echo ""
    echo "Commands:"
    echo "  install   - Install the systemd service"
    echo "  start     - Start the service"
    echo "  stop      - Stop the service"
    echo "  restart   - Restart the service"
    echo "  status    - Show service status"
    echo "  logs      - Show service logs (tail -f)"
    echo "  uninstall - Remove the systemd service"
}

function check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}This command requires sudo privileges${NC}"
        exit 1
    fi
}

function install_service() {
    check_root
    
    echo -e "${YELLOW}Installing Calvin NAV Refresh Service...${NC}"
    
    # Copy service file to systemd directory
    cp "${SCRIPT_DIR}/${SERVICE_FILE}" "/etc/systemd/system/${SERVICE_FILE}"
    
    # Reload systemd daemon
    systemctl daemon-reload
    
    # Enable service to start on boot
    systemctl enable ${SERVICE_NAME}
    
    echo -e "${GREEN}Service installed successfully!${NC}"
    echo -e "${YELLOW}To start the service, run: sudo $0 start${NC}"
}

function start_service() {
    check_root
    
    echo -e "${YELLOW}Starting Calvin NAV Refresh Service...${NC}"
    systemctl start ${SERVICE_NAME}
    
    # Wait a moment and check status
    sleep 2
    if systemctl is-active --quiet ${SERVICE_NAME}; then
        echo -e "${GREEN}Service started successfully!${NC}"
        systemctl status ${SERVICE_NAME} --no-pager
    else
        echo -e "${RED}Failed to start service${NC}"
        systemctl status ${SERVICE_NAME} --no-pager
        exit 1
    fi
}

function stop_service() {
    check_root
    
    echo -e "${YELLOW}Stopping Calvin NAV Refresh Service...${NC}"
    systemctl stop ${SERVICE_NAME}
    echo -e "${GREEN}Service stopped${NC}"
}

function restart_service() {
    check_root
    
    echo -e "${YELLOW}Restarting Calvin NAV Refresh Service...${NC}"
    systemctl restart ${SERVICE_NAME}
    
    # Wait a moment and check status
    sleep 2
    if systemctl is-active --quiet ${SERVICE_NAME}; then
        echo -e "${GREEN}Service restarted successfully!${NC}"
        systemctl status ${SERVICE_NAME} --no-pager
    else
        echo -e "${RED}Failed to restart service${NC}"
        systemctl status ${SERVICE_NAME} --no-pager
        exit 1
    fi
}

function show_status() {
    systemctl status ${SERVICE_NAME}
}

function show_logs() {
    echo -e "${YELLOW}Showing logs for Calvin NAV Refresh Service (Ctrl+C to exit)...${NC}"
    journalctl -u ${SERVICE_NAME} -f
}

function uninstall_service() {
    check_root
    
    echo -e "${YELLOW}Uninstalling Calvin NAV Refresh Service...${NC}"
    
    # Stop service if running
    systemctl stop ${SERVICE_NAME} 2>/dev/null
    
    # Disable service
    systemctl disable ${SERVICE_NAME} 2>/dev/null
    
    # Remove service file
    rm -f "/etc/systemd/system/${SERVICE_FILE}"
    
    # Reload systemd daemon
    systemctl daemon-reload
    
    echo -e "${GREEN}Service uninstalled successfully!${NC}"
}

# Main script logic
case "$1" in
    install)
        install_service
        ;;
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    uninstall)
        uninstall_service
        ;;
    *)
        print_usage
        exit 1
        ;;
esac 