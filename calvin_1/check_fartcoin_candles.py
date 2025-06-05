import sqlite3
import pandas as pd
from datetime import datetime, timedelta

# Connect to the SQLite database
conn = sqlite3.connect('data/tradingbot.db')
cursor = conn.cursor()

# First, get the token_id for Fartcoin
cursor.execute("SELECT token_id FROM tokens WHERE symbol LIKE 'FART%'")
token = cursor.fetchone()

if not token:
    print("Fartcoin not found in the database")
    conn.close()
    exit(1)

token_id = token[0]
print(f"Found Fartcoin with token_id: {token_id}")

# Get count of 1m candles
cursor.execute(
    "SELECT COUNT(*) FROM ohlcv WHERE token_id = ? AND resolution = '1m'",
    (token_id,)
)
count_1m = cursor.fetchone()[0]
print(f"Total 1m candles: {count_1m}")

# Get count of 5m candles
cursor.execute(
    "SELECT COUNT(*) FROM ohlcv WHERE token_id = ? AND resolution = '5m'",
    (token_id,)
)
count_5m = cursor.fetchone()[0]
print(f"Total 5m candles: {count_5m}")

# Check for overlapping timestamps
print("\nChecking for overlapping timestamps between 1m and 5m candles...")

# Get all 5m timestamps
cursor.execute(
    "SELECT timestamp FROM ohlcv WHERE token_id = ? AND resolution = '5m'",
    (token_id,)
)
timestamps_5m = [row[0] for row in cursor.fetchall()]

# Check if any 1m candles have the same timestamps as 5m candles
cursor.execute(
    "SELECT COUNT(*) FROM ohlcv WHERE token_id = ? AND resolution = '1m' AND timestamp IN (SELECT timestamp FROM ohlcv WHERE token_id = ? AND resolution = '5m')",
    (token_id, token_id)
)
overlapping_count = cursor.fetchone()[0]
print(f"Candles with same timestamp in both 1m and 5m: {overlapping_count}")

# The issue might be that 5m candles don't match exactly with 1m candles
# Let's check if 1m candles align with 5m candle timestamps (should be every 5th minute)
print("\nAnalyzing 1m candles alignment with 5m intervals...")

# Get a sample of 1m timestamps for analysis (limit to avoid processing too much data)
cursor.execute(
    "SELECT timestamp FROM ohlcv WHERE token_id = ? AND resolution = '1m' ORDER BY timestamp LIMIT 500",
    (token_id,)
)
timestamps_1m = [datetime.fromisoformat(row[0].replace('Z', '+00:00')) if isinstance(row[0], str) else row[0] for row in cursor.fetchall()]

if timestamps_1m:
    # Count candles at each minute position
    minutes_distribution = {}
    for ts in timestamps_1m:
        minute = ts.minute % 5
        minutes_distribution[minute] = minutes_distribution.get(minute, 0) + 1
    
    print("Distribution of 1m candles by minute position within 5m intervals:")
    for minute, count in sorted(minutes_distribution.items()):
        print(f"  Minute {minute}: {count} candles")
    
    # If perfectly aligned with 5m candles, minutes 0 would have the same frequency as 5m candles
    aligned_count = minutes_distribution.get(0, 0)
    print(f"\nCandles aligned with 5m intervals (minute ending in 0): {aligned_count}")
    if count_5m > 0:
        print(f"Potential match rate with 5m candles: {aligned_count / count_5m:.2%}")

# Get sample data to compare actual values
print("\nComparing sample 1m and 5m candle data...")

# Get 10 recent 5m candles
cursor.execute(
    "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE token_id = ? AND resolution = '5m' ORDER BY timestamp DESC LIMIT 10",
    (token_id,)
)
sample_5m = cursor.fetchall()

if sample_5m:
    # For each 5m candle, find matching 1m candles in that time range
    for candle_5m in sample_5m:
        timestamp_5m, open_5m, high_5m, low_5m, close_5m, volume_5m = candle_5m
        ts_5m = datetime.fromisoformat(timestamp_5m.replace('Z', '+00:00')) if isinstance(timestamp_5m, str) else timestamp_5m
        
        # Find 1m candles in this 5m interval
        ts_start = ts_5m - timedelta(minutes=4)
        
        cursor.execute(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE token_id = ? AND resolution = '1m' AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            (token_id, ts_start, ts_5m)
        )
        candles_1m = cursor.fetchall()
        
        print(f"\n5m Candle at {ts_5m}:")
        print(f"  OHLCV: {open_5m:.6f}, {high_5m:.6f}, {low_5m:.6f}, {close_5m:.6f}, {volume_5m:.6f}")
        print(f"  Found {len(candles_1m)} corresponding 1m candles")
        
        if candles_1m:
            # Calculate what the 5m values should be based on 1m candles
            highs_1m = [c[2] for c in candles_1m]
            lows_1m = [c[3] for c in candles_1m]
            volumes_1m = [c[5] for c in candles_1m]
            
            # First 1m candle's open and last 1m candle's close
            open_calc = candles_1m[0][1] if candles_1m else None
            close_calc = candles_1m[-1][4] if candles_1m else None
            
            # High should be max of all highs, low should be min of all lows
            high_calc = max(highs_1m) if highs_1m else None
            low_calc = min(lows_1m) if lows_1m else None
            
            # Volume should be sum of all volumes
            volume_calc = sum(volumes_1m) if volumes_1m else None
            
            print("  Calculated from 1m candles:")
            print(f"    OHLCV: {open_calc:.6f}, {high_calc:.6f}, {low_calc:.6f}, {close_calc:.6f}, {volume_calc:.6f}")
            
            # Check if values match
            matches = []
            if open_calc is not None and abs(open_5m - open_calc) < 0.000001:
                matches.append("open")
            if high_calc is not None and abs(high_5m - high_calc) < 0.000001:
                matches.append("high")
            if low_calc is not None and abs(low_5m - low_calc) < 0.000001:
                matches.append("low")
            if close_calc is not None and abs(close_5m - close_calc) < 0.000001:
                matches.append("close")
            if volume_calc is not None and abs(volume_5m - volume_calc) < 0.000001:
                matches.append("volume")
                
            if len(matches) == 5:
                print("  ✓ All values match - this 5m candle appears to be derived from these 1m candles")
            else:
                print(f"  ✗ Only these values match: {', '.join(matches) if matches else 'none'}")

conn.close()
print("\nAnalysis completed") 