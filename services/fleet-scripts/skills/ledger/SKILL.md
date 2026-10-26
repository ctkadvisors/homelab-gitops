---
name: ledger
description: Read the fleet's ledger (recent runs and how they ended, candidates, outcomes) from Python, read-only.
---
# The ledger, read-only

```
python3 -c 'import sys; sys.path[:0]=["/fleet","/fleet/vendor"]; from fleet import ledger; [print(r["id"], r["repo"], r["outcome"], (r.get("halt") or {}).get("reason")) for r in ledger.recent_runs(12)]'
```
`LEDGER_DSN_FILE` points at a read-only role; if it is missing, say so and move on. Package caches for
npm, pip and uv persist per node under `/workspace/cache`, so a second install is cheap.
