#!/usr/bin/env python3
"""
Script to refresh lbu_1m continuous aggregate in chunks to avoid memory issues.
"""

import os
import sys
from datetime import datetime, timedelta
import psycopg2

DB_CONFIG = {
    'host': 'localhost',
    'port': 5433,
    'user': 'calvin_dev',
    'password': os.environ.get('DB_PASSWORD_DEV'),
    'database': 'calvin_trading_dev'
}

def refresh_chunks():
    """Refresh lbu_1m continuous aggregate in small chunks."""
    print("Starting lbu_1m refresh...")

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True  # Enable autocommit to avoid transaction blocks
    cursor = conn.cursor()

    # Start from most recent data and work backwards
    start_date = datetime(2025, 6, 11, 0, 0, 0)
    end_date = datetime(2025, 9, 17, 0, 0, 0)
    chunk_hours = 4  # 4-hour chunks to stay under memory limits

    current = start_date
    successful_chunks = 0
    failed_chunks = 0

    while current < end_date:
        chunk_end = min(current + timedelta(hours=chunk_hours), end_date)

        try:
            print(f"Refreshing {current} to {chunk_end}")
            cursor.execute("CALL refresh_continuous_aggregate('lbu_1m', %s, %s)",
                          (current, chunk_end))
            print("✓ Completed chunk")
            successful_chunks += 1

        except Exception as e:
            print(f"✗ Failed chunk {current} to {chunk_end}: {e}")
            failed_chunks += 1

            # If we hit memory limit, try smaller chunks
            if "temp_file_limit" in str(e):
                print("Reducing chunk size due to memory limit...")
                chunk_hours = max(1, chunk_hours // 2)
                continue

        current = chunk_end

    print(f"\nRefresh complete: {successful_chunks} successful, {failed_chunks} failed")

    # Check final coverage
    cursor.execute("""
        SELECT COUNT(*) as total_buckets,
               SUM(CASE WHEN lb_best_bid IS NOT NULL THEN 1 ELSE 0 END) as with_data,
               ROUND(100.0 * SUM(CASE WHEN lb_best_bid IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) as coverage
        FROM lbu_1m WHERE symbol = 'BONK-USD'
    """)

    total, with_data, coverage = cursor.fetchone()
    print(".2f")
    cursor.close()
    conn.close()

if __name__ == "__main__":
    refresh_chunks()
