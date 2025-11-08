'''
Download limit books for a given token and date range from CoinAPI S3 bucket


python calvin_1/src/scripts/download_limitbooks.py \
  --start "$(date -u -d '90 days ago' +%F)" \
  --end "$(date -u +%F)" \
  --exchange COINBASE \
  --symbols BONK-USD \
  --out-dir calvin_1/limitbooks

'''

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current = current + timedelta(days=1)


def run(cmd: list[str]) -> int:
    proc = subprocess.run(cmd)
    return proc.returncode


def build_cp_cmd(endpoint: str, s3_prefix: str, out_dir: Path, includes: list[str]) -> list[str]:
    cmd = [
        "aws",
        "--endpoint-url",
        endpoint,
        "s3",
        "cp",
        s3_prefix,
        str(out_dir),
        "--recursive",
    ]
    if includes:
        # Exclude everything first, then add includes
        cmd += ["--exclude", "*"]
        for patt in includes:
            cmd += ["--include", patt]
    return cmd


def main():
    parser = argparse.ArgumentParser(description="Download CoinAPI limit book flat files by date range.")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD (inclusive)")
    parser.add_argument("--exchange", required=True, help="Exchange name as in S3 path, e.g., COINBASE")
    parser.add_argument(
        "--symbols",
        help="Comma-separated symbols to filter, e.g., BONK-USD,JUP-USD. If omitted, downloads all symbols.",
    )
    parser.add_argument(
        "--endpoint",
        default="http://s3.flatfiles.coinapi.io",
        help="S3-compatible endpoint for CoinAPI flat files",
    )
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parents[2] / "calvin_1" / "limitbooks"),
        help="Local output root directory",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")

    args = parser.parse_args()

    try:
        start_d = datetime.strptime(args.start, "%Y-%m-%d").date()
        end_d = datetime.strptime(args.end, "%Y-%m-%d").date()
    except ValueError as e:
        print(f"Invalid date: {e}")
        sys.exit(2)
    if end_d < start_d:
        print("End date must be >= start date")
        sys.exit(2)

    out_root = Path(args.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    includes: list[str] = []
    if args.symbols:
        # S3 filenames encode hyphen as __002D in the trailing S-<symbol> component
        # We'll include both raw and encoded just in case
        for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
            encoded = sym.replace("-", "__002D")
            includes.append(f"*S-{sym}.csv.gz")
            includes.append(f"*S-{encoded}.csv.gz")

    exit_code = 0
    for d in daterange(start_d, end_d):
        s3_prefix = f"s3://coinapi/T-LIMITBOOK_FULL/D-{d.strftime('%Y%m%d')}/E-{args.exchange}/"
        out_dir = out_root / d.strftime("%Y-%m-%d") / args.exchange
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = build_cp_cmd(args.endpoint, s3_prefix, out_dir, includes)
        print("Downloading:", " ".join(cmd))
        if args.dry_run:
            continue
        rc = run(cmd)
        if rc != 0:
            print(f"Download failed for {d} (exit {rc})")
            exit_code = rc

    sys.exit(exit_code)


if __name__ == "__main__":
    main()


