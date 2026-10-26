"""brain-scribe: alerts that started firing in the last window become
brain episodes. Hourly, deterministic."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fleet import brain  # noqa: E402

AM = os.environ["ALERTMANAGER_URL"]
WINDOW_S = int(os.environ.get("WINDOW_SECONDS", "3900"))


def main() -> None:
    alerts = json.load(urllib.request.urlopen(AM + "/api/v2/alerts?active=true", timeout=30))
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=WINDOW_S)
    fresh = [(a, datetime.fromisoformat(a["startsAt"].replace("Z", "+00:00"))) for a in alerts]
    fresh = [(a, s) for a, s in fresh if s >= cutoff]
    if not fresh:
        print("no new alerts in window")
        return
    for a, started in fresh:
        labels, ann = a.get("labels", {}), a.get("annotations", {})
        name = labels.get("alertname", "unknown-alert")
        brain.add_episode(
            f"alert: {name} ({started.date()})",
            f"Alert {name} started firing at {started.isoformat()} on the homelab cluster. "
            f"Labels: {json.dumps(labels)}. Summary: {ann.get('summary', '')}. Description: {ann.get('description', '')}.",
            "alertmanager via brain-scribe", reference_time=started.isoformat(), client="brain-scribe")
        print(f"queued episode for {name}")


if __name__ == "__main__":
    main()
