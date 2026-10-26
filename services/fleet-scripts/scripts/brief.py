"""Mission entry stage: the human already chose the work, so write what
investigate + adjudicate would have produced (one candidate, selected).
The repo is cloned by clone.py in the stage before this one. No model."""

import json
import os

P = os.environ.get("PIPELINE_DIR", "/workspace/p")
brief = os.environ["MISSION_BRIEF"].strip()

os.makedirs(P, exist_ok=True)
json.dump({"candidates": [{"id": "M1", "file": "(see brief)", "line": 0, "claim": brief,
                           "evidence": "requested by Chris via the concierge",
                           "rationale": "human-selected mission; implement exactly this, nothing else",
                           "risk": "medium", "est_changed_lines": 200}]}, open(f"{P}/01-findings.json", "w"))
json.dump({"evaluations": [{"id": "M1", "verdict": "PASS", "weighted_total": 10, "reasoning": "human-selected"}],
           "selected": "M1", "selection_reasoning": "mission brief from the operator"}, open(f"{P}/02-verdict.json", "w"))
print(f"brief: {brief[:120]}")
