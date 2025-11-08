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
        help="psql connection URL (host-exposed compose port)",
    )
    parser.add_argument("--move-to", default="archive", help="Subdirectory to move processed files into")
    parser.add_argument("--default-day", help="YYYY-MM-DD fallback date for files lacking date in path")
    parser.add_argument("--max", type=int, help="Max files to process this run")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
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


if __name__ == "__main__":
    main()


