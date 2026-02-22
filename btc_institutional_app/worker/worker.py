from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from urllib import request
from urllib.error import URLError

SNAPSHOT_URL = "http://api:8000/v1/ingestion/snapshot?symbol=BTCUSDT&run_analysis=true"


def trigger_snapshot() -> None:
    req = request.Request(SNAPSHOT_URL, data=b"", method="POST")
    with request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] snapshot ingested | "
            f"source={body.get('source')} degraded={body.get('data_degraded')} case_id={body.get('case_id')}"
        )


def main() -> None:
    while True:
        try:
            trigger_snapshot()
        except URLError as exc:
            print(f"worker warning: API/provider unreachable ({exc})")
        except Exception as exc:  # noqa: BLE001
            print(f"worker warning: unexpected error ({exc})")
        time.sleep(30)


if __name__ == "__main__":
    main()
