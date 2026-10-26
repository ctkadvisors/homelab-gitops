---
name: checks
description: The failing CI checks on a commit with the telling log lines, when you cannot see GitHub yourself. Use it before guessing what a check wants.
---
# Failing checks on a commit

```
curl -s http://mission-launcher.kagent-system.svc:8080/checks/<owner>/<repo>/<sha>
```
JSON: `failing[]` with `name`, `conclusion`, `url`, `lines[]` (the telling lines of that job's log,
at most ~80). A cancelled check is not a failing check: it was cut by a concurrency group or a
timeout, and re-running it is the fix, not a code change.
