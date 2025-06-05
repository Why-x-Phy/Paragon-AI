#!/usr/bin/env python
"""
Script to drop Fartcoin social data from the database.
"""

import os
import sys
from dotenv import load_dotenv
import logging
from pathlib import Path

# Find and load environment variables from .env file
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent  # Navigate to project root
root_env_path = project_root / '.env'

if root_env_path.exists():
    load_dotenv(root_env_path)
else:
    # Fallback to the current directory
    current_dir_env = current_file.parent / '.env'
    if current_dir_env.exists():
        load_dotenv(current_dir_env)
    else:
        # Last resort, try default behavior
        load_dotenv()

# Set up basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("drop_fartcoin_social")

# Add the project root directory to sys.path to import project modules
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = current_dir
sys.path.append(project_root)

from src.database.db import get_session, Token
from sqlalchemy import text

def drop_fartcoin_social_data():
    """Delete all Fartcoin social data from the database."""
    session = get_session()
    try:
        # Get Fartcoin token ID - first try by symbol
        token = session.query(Token).filter(Token.symbol == "FART").first()
        
        # If not found by symbol, try by address
        if not token:
            token = session.query(Token).filter(Token.address == "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump").first()
        
        if not token:
            logger.error("Fartcoin not found in the database")
            return
        
        # Log token found
        logger.info(f"Found Fartcoin with token_id: {token.token_id}")
        
        # Count records before deletion
        count_query = session.execute(
            text("SELECT COUNT(*) FROM social_metrics WHERE token_id = :token_id"),
            {"token_id": token.token_id}
        )
        count_before = count_query.scalar()
        logger.info(f"Found {count_before} social records for Fartcoin")
        
        # Delete social metrics for Fartcoin
        if count_before > 0:
            delete_query = text("DELETE FROM social_metrics WHERE token_id = :token_id")
            result = session.execute(delete_query, {"token_id": token.token_id})
            session.commit()
            logger.info(f"Successfully deleted {count_before} Fartcoin social records")
        else:
            logger.info("No Fartcoin social records found to delete")
            
    except Exception as e:
        session.rollback()
        logger.error(f"Error dropping Fartcoin social data: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    logger.info("Starting script to drop Fartcoin social data")
    drop_fartcoin_social_data()
    logger.info("Script completed") 