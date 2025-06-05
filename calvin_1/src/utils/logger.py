import os
import sys
from pathlib import Path
from loguru import logger
from datetime import datetime

from src.config.config import config

class Logger:
    def __init__(self):
        self.log_level = config.log_level
        
        # Create logs directory if it doesn't exist
        self.logs_dir = Path("logs")
        self.logs_dir.mkdir(exist_ok=True)
        
        # Remove default logger
        logger.remove()
        
        # Add console logger
        logger.add(
            sys.stdout,
            level=self.log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            colorize=True
        )
        
        # Add file logger
        log_file = self.logs_dir / f"solana_bot_{datetime.now().strftime('%Y%m%d')}.log"
        logger.add(
            log_file,
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            rotation="12:00",  # New file at noon
            retention="30 days",  # Keep logs for 30 days
            compression="zip"
        )
    
    def get_logger(self, name=None):
        """Get a contextualized logger instance"""
        return logger.bind(name=name)

# Global logger instance
log_manager = Logger()

# Default logger
log = log_manager.get_logger("solana_ml_bot")
