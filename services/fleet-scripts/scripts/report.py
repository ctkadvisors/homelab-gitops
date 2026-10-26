"""report: run an agent on a schedule and deliver its answer to Telegram.

The generic "scheduled agent -> operator" bridge. Replaces
homelab-orchestrator's daily digest: the prompt lives in a ConfigMap
(/config/prompt.txt), the agent is any Agent CR, the result goes to
Telegram and to the brain. No model runs here; the AgentTask does.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fleet import brain, telegram  # noqa: E402

WORKBENCH = os.environ.get("WORKBENCH_URL", "http://kagent-workbench.kagent-system.svc.cluster.local")
NAMESPACE = os.environ.get("AGENT_NAMESPACE", "kagent-system")
AGENT = os.environ["TARGET_AGENT"]
TITLE = os.environ.get("REPORT_TITLE", "Report")
PROMPT_FILE = os.environ.get("PROMPT_FILE", "/config/prompt.txt")
MAX_WAIT_S = int(os.environ.get("MAX_WAIT_SECONDS", "1500"))


def api(path: str, data=None):
    from fleet.net import urlopen_retry  # a new pod's first seconds are refused by the workbench's netpol (fleet/net.py)
    req = urllib.request.Request(WORKBENCH + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    return json.load(urlopen_retry(req, timeout=30))


def main() -> None:
    prompt = open(PROMPT_FILE).read().strip()
    created = api("/api/tasks", {"namespace": NAMESPACE, "targetAgent": AGENT, "originalUserMessage": prompt,
                                 "payload": {"text": prompt, "report": TITLE},
                                 "runConfig": {"maxIterations": int(os.environ.get("MAX_ITERATIONS", "10")),
                                               "timeoutSeconds": MAX_WAIT_S}})
    name = created.get("name") or created.get("task", {}).get("name")
    print(f"report: task {name} on {AGENT}")
    deadline = time.time() + MAX_WAIT_S + 60
    while time.time() < deadline:
        t = api(f"/api/tasks/{NAMESPACE}/{name}")
        if t.get("phase") in ("Completed", "Failed"):
            break
        time.sleep(15)
    phase = t.get("phase")
    result = t.get("result")
    text = (result.get("content") if isinstance(result, dict) else result) or t.get("error") or "(no content)"
    # Local models sometimes narrate their plan before the answer. The prompt
    # asks for a marker line; deliver only what follows it when present.
    marker = os.environ.get("ANSWER_MARKER", "DIGEST")
    if marker:
        if marker in text:
            text = text.split(marker, 1)[1]
        else:
            # No marker = the model narrated instead of answering (seen
            # 2026-09-03: 7.6k chars of plan, zero digest). Don't forward it.
            phase = "no-answer"
            text = (f"The agent produced no {TITLE.lower()} (it narrated its plan instead). "
                    f"Task {name}; first lines:\n" + "\n".join(text.strip().splitlines()[:4]))
    text = text.strip()
    telegram.send(f"\U0001F4F0 {TITLE} ({date.today()}) — {AGENT}, {phase}\n\n{text}")
    try:
        brain.add_episode(f"{TITLE.lower()} ({date.today()})", f"{TITLE} produced by {AGENT} ({phase}): {text[:5000]}",
                          "scheduled report", client="fleet-report")
    except Exception as e:
        print("brain write failed (non-fatal):", e)
    print(f"report: {phase}, {len(text)} chars delivered")


if __name__ == "__main__":
    main()
