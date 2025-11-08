'''
Ingest limit books into TimescaleDB.

python calvin_1/src/scripts/ingest_limitbooks.py \
  --dir calvin_1/limitbooks \
  --psql-url "postgres://calvin_dev:${DB_PASSWORD_DEV:-calvin_dev_password}@localhost:5433/calvin_trading_dev"

'''

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta
from io import StringIO
import requests
from requests.adapters import HTTPAdapter
from requests import exceptions as req_exc
from urllib3.util.retry import Retry
import csv
import psycopg2


STAGING_CREATE = """
CREATE TEMP TABLE staging_limitbook_raw (
  time_exchange text,
  time_coinapi text,
  update_type text,
  is_buy int,
  entry_px double precision,
  entry_sx bigint,
  order_id text
) ON COMMIT DROP;
"""

STAGING_INSERT = """
WITH params AS (
  SELECT to_date(:'day', 'YYYY-MM-DD')::timestamptz AS d,
         :'exchange'::text AS exchange,
         :'symbol'::text AS symbol
)
INSERT INTO limitbook_updates (ts, exchange, symbol, update_type, is_buy, price, size, order_id)
SELECT
  (params.d
   + make_interval(
       hours => split_part(r.time_exchange, ':', 1)::int,
       mins  => split_part(r.time_exchange, ':', 2)::int,
       secs  => split_part(split_part(r.time_exchange, ':', 3), '.', 1)::int
     )
   + ((('0.' || split_part(r.time_exchange, '.', 2))::double precision) * interval '1 second')
  ) AS ts,
  params.exchange,
  params.symbol,
  r.update_type,
  (r.is_buy = 1),
  r.entry_px,
  r.entry_sx,
  r.order_id::uuid
FROM staging_limitbook_raw r, params
WHERE r.time_exchange IS NOT NULL;
"""


COINAPI_STAGING_CREATE = """
CREATE TEMP TABLE staging_orderbook_levels (
  ts timestamptz,
  exchange text,
  market_type text,
  base text,
  quote text,
  side boolean,
  level smallint,
  price double precision,
  size double precision,
  amount double precision
) ON COMMIT DROP;
"""

COINAPI_STAGE_TO_FINAL = """
INSERT INTO orderbook_levels (ts, exchange, market_type, base, quote, side, level, price, size, amount)
SELECT ts, exchange, market_type, base, quote, side, level, price, size, amount
FROM staging_orderbook_levels
ON CONFLICT ON CONSTRAINT orderbook_levels_uq DO NOTHING;
"""


def parse_metadata_from_path(path: Path):
    # Prefer directory-structured metadata if available
    day = None
    exchange = None
    symbol = None

    # Day from parent-of-parent folder
    if path.parent.parent.name and re.match(r"\d{4}-\d{2}-\d{2}", path.parent.parent.name):
        day = path.parent.parent.name
    # Exchange from direct parent (ignore common root folders)
    if path.parent.name and path.parent.name not in ("", ".", "limitbooks", "archive"):
        exchange = path.parent.name

    # Symbol from filename suffix S-<symbol>.csv.gz (with __002D encoding for '-')
    m = re.search(r"S-([^.]+)\.csv\.gz$", path.name)
    if m:
        symbol = m.group(1).replace("__002D", "-")

    # Fallbacks: exchange from filename (SC-<EXCHANGE>_), day from D-YYYYMMDD anywhere in path
    if not exchange:
        m_ex = re.search(r"SC-([A-Za-z0-9]+)", path.name)
        if m_ex:
            exchange = m_ex.group(1)
    if not day:
        m_day = re.search(r"D-(\d{8})", str(path))
        if m_day:
            ymd = m_day.group(1)
            day = f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}"

    return day, exchange, symbol


def run_psql_stream(psql_url: str, sql_text: str, variables: dict, gz_path: Path):
    env = os.environ.copy()
    # Build psql -v bindings
    var_flags = []
    for k, v in variables.items():
        var_flags += ["-v", f"{k}={v}"]

    # Build SQL: create temp table, then copy, then insert
    prefix = "CREATE EXTENSION IF NOT EXISTS timescaledb;\n" + STAGING_CREATE
    copy_cmd = (
        f"\\copy staging_limitbook_raw FROM PROGRAM 'pigz -dc {str(gz_path)}' WITH (FORMAT csv, HEADER true, DELIMITER ';')\n"
    )
    payload = ("BEGIN;\n" + prefix + copy_cmd + STAGING_INSERT + "COMMIT;\n").encode()

    cmd = ["psql", psql_url, "-v", "ON_ERROR_STOP=1"] + var_flags
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    proc.stdin.write(payload)
    proc.stdin.close()
    return proc.wait()


def main():
    parser = argparse.ArgumentParser(description="Ingest limit book .csv.gz files into TimescaleDB.")
    parser.add_argument("--dir", default=str(Path(__file__).resolve().parents[2] / "calvin_1" / "limitbooks"))
    parser.add_argument(
        "--psql-url",
        default="postgres://calvin_dev:calvin_dev_password@localhost:5433/calvin_trading_dev",
        help="psql connection URL (host-exposed compose port) [legacy mode only]",
    )
    parser.add_argument("--move-to", default="archive", help="Subdirectory to move processed files into")
    parser.add_argument("--default-day", help="YYYY-MM-DD fallback date for files lacking date in path")
    parser.add_argument("--max", type=int, help="Max files to process this run")
    parser.add_argument("--dry-run", action="store_true")
    # CoinAPI mode
    parser.add_argument("--coinapi", action="store_true", help="Enable CoinAPI date-range API→DB ingestion")
    parser.add_argument("--symbol-id", help="CoinAPI symbol_id (e.g., BINANCE_SPOT_BTC_USDT)")
    parser.add_argument("--date", help="Single date YYYY-MM-DD")
    parser.add_argument("--start-date", help="Start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--end-date", help="End date YYYY-MM-DD (inclusive)")
    parser.add_argument("--csv-out", help="Optional CSV preview output path (first ≤ csv-max-rows rows)")
    parser.add_argument("--csv-max-rows", type=int, default=10000, help="Max preview rows to write if --csv-out set")
    parser.add_argument("--api-key", help="CoinAPI API key (fallback to env COINAPI_API_KEY)")
    parser.add_argument("--http-timeout", type=int, default=600, help="HTTP read timeout in seconds for CoinAPI requests")
    parser.add_argument("--http-retries", type=int, default=5, help="Max HTTP retries on transient errors")
    parser.add_argument("--http-backoff", type=float, default=1.5, help="Exponential backoff factor for HTTP retries")

    args = parser.parse_args()

    if args.coinapi:
        return run_coinapi_mode(args)

    root = Path(args.dir)
    archive = root / args.move_to
    archive.mkdir(parents=True, exist_ok=True)

    # Ensure pigz and psql are present
    for tool in ("pigz", "psql"):
        if shutil.which(tool) is None:
            print(f"Missing dependency: {tool}")
            sys.exit(2)

    files = sorted(root.rglob("*.csv.gz"))
    if args.max:
        files = files[: args.max]

    processed = 0
    for gz in files:
        day, exchange, symbol = parse_metadata_from_path(gz)
        if not day and args.default_day:
            day = args.default_day
        if not (day and exchange and symbol):
            print(f"Skip (missing metadata): {gz} -> day={day} exchange={exchange} symbol={symbol}")
            continue

        print(f"Ingesting {gz} -> day={day} exchange={exchange} symbol={symbol}")
        if args.dry_run:
            continue

        rc = run_psql_stream(
            args.psql_url,
            STAGING_INSERT,
            {"day": day, "exchange": exchange, "symbol": symbol},
            gz,
        )
        if rc == 0:
            # Move to archive preserving directory
            rel = gz.relative_to(root)
            dest = archive / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            gz.rename(dest)
            processed += 1
        else:
            print(f"Failed ingest: {gz} (exit {rc})")

    print(f"Processed {processed} files.")


def run_coinapi_mode(args):
    """
    Date-range API→DB ingestion from CoinAPI into orderbook_levels.
    """
    # Resolve environment configuration
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("Missing DATABASE_URL in environment")
        sys.exit(2)
    api_key = args.api_key or os.environ.get("COINAPI_KEY")
    if not api_key:
        print("Missing CoinAPI API key (set --api-key or COINAPI_KEY env)")
        sys.exit(2)
    if not args.symbol_id:
        print("Missing --symbol-id (e.g., BINANCE_SPOT_BTC_USDT)")
        sys.exit(2)

    # Compute date list
    dates = []
    if args.date:
        dates = [args.date]
    else:
        if not (args.start_date and args.end_date):
            print("Provide --date or --start-date and --end-date (YYYY-MM-DD)")
            sys.exit(2)
        try:
            d0 = datetime.strptime(args.start_date, "%Y-%m-%d").date()
            d1 = datetime.strptime(args.end_date, "%Y-%m-%d").date()
        except ValueError:
            print("Invalid date format; use YYYY-MM-DD")
            sys.exit(2)
        if d1 < d0:
            print("end-date must be >= start-date")
            sys.exit(2)
        cur = d0
        while cur <= d1:
            dates.append(cur.isoformat())
            cur += timedelta(days=1)

    # Optional CSV preview
    csv_writer = None
    csv_file = None
    preview_remaining = args.csv_max_rows if args.csv_out else 0
    if args.csv_out:
        csv_file = open(args.csv_out, "w", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["ts", "exchange", "market_type", "base", "quote",
                             "side", "level", "price", "size", "amount"])

    try:
        # Configure HTTP session with retries/backoff
        session = requests.Session()
        retry = Retry(
            total=args.http_retries,
            backoff_factor=args.http_backoff,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                for date_str in dates:
                    print(f"Ingesting {args.symbol_id} for {date_str}")
                    url = f"https://rest.coinapi.io/v1/orderbooks/{args.symbol_id}/history"
                    headers = {
                        "Accept": "application/json",
                        "X-CoinAPI-Key": api_key
                    }

                    # Begin per-day transaction and staging (works for both daily and chunked paths)
                    cur.execute("BEGIN;")
                    cur.execute(COINAPI_STAGING_CREATE)

                    buffer = StringIO()
                    writer = csv.writer(buffer)

                    def flush_batch():
                        nonlocal buffer, writer
                        buffer.seek(0)
                        cur.copy_expert(
                            "COPY staging_orderbook_levels (ts, exchange, market_type, base, quote, side, level, price, size, amount) FROM STDIN WITH (FORMAT csv)",
                            buffer
                        )
                        buffer = StringIO()
                        writer = csv.writer(buffer)

                    def process_snapshots(snapshots_iterable):
                        nonlocal buffer
                        batch_rows_local = 0
                        exchange, market_type, base, quote = parse_symbol_id(args.symbol_id)
                        for snap in snapshots_iterable:
                            ts = snap.get("time_coinapi") or snap.get("time_exchange")
                            # asks (side=false)
                            for idx, level in enumerate(snap.get("asks", []), start=1):
                                price = float(level.get("price", 0))
                                size = float(level.get("size", 0))
                                amount = price * size
                                writer.writerow([ts, exchange, market_type, base, quote, "false", idx, price, size, amount])
                                batch_rows_local += 1
                                if csv_writer and preview_remaining > 0:
                                    csv_writer.writerow([ts, exchange, market_type, base, quote, False, idx, price, size, amount])
                                    preview_remaining -= 1
                            # bids (side=true)
                            for idx, level in enumerate(snap.get("bids", []), start=1):
                                price = float(level.get("price", 0))
                                size = float(level.get("size", 0))
                                amount = price * size
                                writer.writerow([ts, exchange, market_type, base, quote, "true", idx, price, size, amount])
                                batch_rows_local += 1
                                if csv_writer and preview_remaining > 0:
                                    csv_writer.writerow([ts, exchange, market_type, base, quote, True, idx, price, size, amount])
                                    preview_remaining -= 1

                            if batch_rows_local >= 100000:
                                flush_batch()
                                batch_rows_local = 0

                        if batch_rows_local > 0:
                            flush_batch()

                    # Try daily request first
                    try:
                        params = {"date": date_str, "limit_levels": 20}
                        resp = session.get(url, headers=headers, params=params, timeout=args.http_timeout)
                        if resp.status_code != 200:
                            raise req_exc.RequestException(f"HTTP {resp.status_code}: {resp.text[:200]}")
                        snapshots = resp.json()
                        process_snapshots(snapshots)
                    except (req_exc.ReadTimeout, req_exc.ConnectTimeout, req_exc.RequestException) as e:
                        # Fallback to hourly chunks within the same date
                        print(f"Daily request failed ({e}); falling back to hourly chunks for {date_str}")
                        for hour in range(24):
                            start_iso = f"{date_str}T{hour:02d}:00:00Z"
                            if hour == 23:
                                # end at next midnight
                                end_dt = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
                                end_iso = f"{end_dt.strftime('%Y-%m-%d')}T00:00:00Z"
                            else:
                                end_iso = f"{date_str}T{hour+1:02d}:00:00Z"
                            params_chunk = {"time_start": start_iso, "time_end": end_iso, "limit_levels": 20}
                            try:
                                r = session.get(url, headers=headers, params=params_chunk, timeout=args.http_timeout)
                                if r.status_code != 200:
                                    print(f"Chunk {start_iso}→{end_iso} HTTP {r.status_code}: {r.text[:120]}")
                                    continue
                                process_snapshots(r.json())
                            except (req_exc.ReadTimeout, req_exc.ConnectTimeout) as ce:
                                print(f"Chunk timeout {start_iso}→{end_iso}: {ce}")
                                continue

                    # Upsert into final table
                    cur.execute(COINAPI_STAGE_TO_FINAL)
                    cur.execute("COMMIT;")
                    print(f"Committed {date_str}")

    finally:
        if csv_file:
            csv_file.close()

    print("Completed CoinAPI ingestion.")


def parse_symbol_id(symbol_id: str):
    """
    Parse CoinAPI symbol_id like BINANCE_SPOT_BTC_USDT into components.
    Returns (exchange, market_type, base, quote).
    """
    parts = symbol_id.split("_")
    if len(parts) >= 4:
        return parts[0], parts[1], parts[2], parts[3]
    # Fallbacks for odd formats
    exchange = parts[0] if parts else ""
    market_type = parts[1] if len(parts) > 1 else ""
    base = parts[2] if len(parts) > 2 else ""
    quote = parts[3] if len(parts) > 3 else ""
    return exchange, market_type, base, quote


if __name__ == "__main__":
    main()

