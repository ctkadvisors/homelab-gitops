"""The mentor's hand-down: what Claude learned running this fleet for Chris in
the week of 2026-09-01..08, written into the fleet's memory (fleet/memory.py)
so the fleet starts from it instead of rediscovering it. Idempotent: the same
line twice only raises its weight. Run from a pod with ledger write creds:

  python3 /app/scripts/seed_memory.py

Chris, 2026-09-08: "act as the parent/mentor, lay the foundation for it to
become a mini-you." Rules (feedback) are his; lessons and facts are what the
runs, the reviews and the nights of reading logs taught.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fleet import memory  # noqa: E402

FEEDBACK = [
    "Never route inference to the cloud. Everything runs on the spark or the minis; a cloud endpoint is a defect, not a fallback.",
    "Read everything, change things only through pull requests, touch a node only through the node runner's allow-list, never touch third-party systems.",
    "Say what you did and what you did not do. Never round 'mostly' up to 'done'. A halt with an honest reason and a question beats a padded result.",
    "Kid gloves on public, revenue-facing repos (GitHub topic fleet-kid-gloves: harknote, ai-interviewer): review them, never merge them, never choose them for speculative work.",
    "Status is computed, not narrated. Any 'is it healthy / what's broken' question is answered from fleet.health, and its summary sentence is quoted verbatim before anything else.",
    "An instruction from Chris on Telegram or the forum is acted on and closed with the outcome where it was asked. If the backend fails, retry, then say exactly what failed; never let his words disappear.",
    "Never silence a failing check to make it green. Make the check pass on what it should test (for npm audit: the production tree at high severity) or say why it cannot.",
    "Do not invent counts, trends or patterns. If a number is not in the data in front of you, do not say it.",
]

LESSONS = [
    ("npm reads `overrides` in package.json; `resolutions` is yarn and is ignored. After changing overrides, regenerate package-lock.json.", None),
    ("Installs, builds and test runs inside a stage are allowed when the task needs them to verify; the package caches under /workspace/cache persist across runs.", None),
    ("A cancelled CI check (concurrency group, job timeout) is not a failing check: re-run it; no code change fixes a cancellation.", None),
    ("The CRD drift check and cold `pnpm install` on the Kata runner can take over ten minutes; a five-minute job timeout reads as a failure.", "ctkadvisors/kagent"),
    ("A pull request that touches .github/workflows can only be merged with the GitHub App token; the gh OAuth token lacks the workflow scope.", None),
    ("A page that returns null until it has mounted is blank until all JavaScript runs, so Lighthouse's LCP equals time-to-interactive. Render the shell on the server; gate only client-only state.", "ctkadvisors/brutalist_todo"),
    ("Icon-only buttons need aria-label (button-name audit); a visible-text button must not get an aria-label that differs from its text (label-content-name-mismatch).", "ctkadvisors/brutalist_todo"),
    ("Both audit workflows gate on `npm audit --omit=dev --audit-level=high`; the production tree needs next >= 16.3.3 to be clean. Do not add a bare `npm audit` step next to it.", "ctkadvisors/brutalist_todo"),
    ("Lighthouse CI here: preset desktop with devtools throttling, median of three runs, report printed into the job log (the artifact service is unreachable from the homelab runner).", "ctkadvisors/brutalist_todo"),
    ("A reviewer escalation must state the CI state per check; red CI is never 'correct'. Size alone is a reason to escalate, not to call the change safe.", None),
    ("A fleet pull request merged by a human or the App token is recorded by the webhook; closing its issue is still a deliberate act with a comment.", None),
    ("Halts that are outcomes, not faults ('investigator found no candidates', an unchanged review round) file no issue and page nobody.", None),
]

FACTS = [
    ("elitemini2 (.58) has had a Deco address reservation and a DHCP lease since 2026-09-15; before that the Deco blackholed .58 for 7-27 s every minute. No source-IP workaround is in place. If its egress fails again, check the reservation for 58-47-CA-7E-5D-27 in the Deco app first.", None),
    ("The Deco's DHCP re-addresses hosts that look static: elitemini2 drifted .66->.58, valhalla .54->.67 (2026-09-08). Before declaring a host down, check `ip neigh` and mDNS for where it went.", None),
    ("A new pod's first in-cluster call is refused for a few seconds until the k3s network-policy ipset carries its IP (fleet/net.py urlopen_retry). ECONNREFUSED right after a rollout is that, not an outage.", None),
    ("ornith15 (the fleet's model) writes Python by default; the tool-gateway's code_interpreter has python3 and node. A tool error names the missing binary; the runner itself is up.", None),
    ("The fleet's own code lives in ctkadvisors/new_localai under services/fleet-scripts; halts of the pipeline machinery belong there, not in the target repo.", None),
    ("Backups: valhalla (Synology) first, the spark as fallback when the NAS refuses SSH; `--rsync-path=/usr/bin/rsync` bypasses DSM's wrapper; sqlite `VACUUM INTO` for the k3s datastore.", "ctkadvisors/new_localai"),
]


def main() -> int:
    n = 0
    for text in FEEDBACK:
        n += bool(memory.remember("feedback", text, source="claude"))
    for text, repo in LESSONS:
        n += bool(memory.remember("lesson", text, repo=repo, source="claude"))
    for text, repo in FACTS:
        n += bool(memory.remember("fact", text, repo=repo, source="claude"))
    print(f"seed: {n} rows written or reinforced")
    print(memory.recall(None, "", limit=30))
    return 0


if __name__ == "__main__":
    sys.exit(main())
