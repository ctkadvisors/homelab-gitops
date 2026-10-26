# Evidence, not vibes: the fleet's OWN candidate sources, collected by one
# deterministic pass (no model) so an idle run on a quiet day still finds
# work instead of halting at "investigator found no candidates". Sources,
# from issue #5 (ctkadvisors/new_localai#5), each read-only and each guarded
# so a dead endpoint only shrinks the evidence file, it never kills the run:
#
#   1. workbench   failed AgentTasks from the last 7d, grouped by error string
#                  (the source that existed before #5; auth-free, in-cluster).
#   2. fleet issues every open `fleet:halt` and `fleet:proposal` issue across
#                  every repo the GitHub App is installed on (owner/name) - the
#                  fleet's own problems and its unactioned proposals, whether or
#                  not someone has labelled them `mission` yet - resolved through
#                  the App's installation token so private repos work too.
#   3. ledger runs the last `LEDGER_RUN_LIMIT` (default 10) runs, one per
#                  candidate, with outcome and halt reason, so a rejected, halted
#                  or rolled-back candidate is seen and not repeated.
#   4. reviewer feedback reviewer comments on the fleet's own open agent/* PRs,
#                  the "not repeatable / needs X" follow-ups.
#
# They are grouped into recurrences so a recurring failure is one line with a
# count, and ranked: by how often the recurrence appears, then by recency, so
# the investigator sees the strongest evidence first. Everything stays a dict
# of named sources -> ranked items; investigate.jsonl is the flat, ordered list
# the model stage reads. Written to /workspace/p/00-evidence.json.
import json, os, urllib.request, urllib.error, collections, datetime, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fleet import github, ideas  # noqa: E402

PIPELINE_DIR = os.environ.get("PIPELINE_DIR", "/workspace/p")
WORKBENCH_URL = os.environ.get("WORKBENCH_URL",
        "http://kagent-workbench.kagent-system.svc.cluster.local")
LEDGER_RUN_LIMIT = int(os.environ.get("LEDGER_RUN_LIMIT", "10"))


def _load(name, default=None):
    try:
        with open(f"{PIPELINE_DIR}/{name}") as f:
            return json.load(f)
    except Exception:
        return default


def collect_workbench():
    """The pre-#5 source, unchanged in intent: last 7d failed AgentTasks,
    grouped by (error, targetAgent), newest first. An unreachable workbench
    just yields nothing here."""
    out = []
    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (f"{WORKBENCH_URL}/api/tasks?phase=Failed&limit=60&since={since}")
    try:
        from fleet.net import urlopen_retry  # the first seconds of a new pod are refused by the workbench's netpol
        items = json.load(urlopen_retry(url, timeout=20, tries=6))["items"]
    except Exception as e:
        return out, f"workbench unreachable: {e}"
    groups = collections.defaultdict(list)
    for t in items:
        groups[(t.get("error") or "(no error recorded)", t.get("targetAgent"))].append(t)
    for (err, agent), ts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        out.append({"error": err, "agent": agent, "count": len(ts),
                    "tasks": [{"name": t["name"], "createdAt": t.get("createdAt"),
                               "completedAt": t.get("completedAt")} for t in sorted(ts,
                               key=lambda x: x.get("createdAt") or "")[::-1][:5]]})
    return out, None


def collect_fleet_issues():
    """Every open `fleet:halt` and `fleet:proposal` issue across every repo the
    App is installed on, `mission`-labelled or not: halts (kagent#17 is the
    pipeline's own) and proposals are the fleet's signals; `mission` is only
    the operator's go for one of them, and triage handles that separately."""
    out = []
    repos = github.repos_from_env()
    for repo in repos:
        for lbl in ("fleet:halt", "fleet:proposal"):
            try:
                issues = github.api(
                    f"/repos/{repo}/issues?state=open&labels={lbl}&per_page=30")
            except urllib.error.HTTPError as e:
                print(f"collect: {repo}: {lbl}: HTTP {e.code}")
                continue
            except Exception as e:
                print(f"collect: {repo}: {lbl}: {type(e).__name__}")
                continue
            for i in issues:
                if "pull_request" in i:
                    continue
                out.append({"repo": repo, "number": i["number"],
                            "title": i.get("title"), "url": i.get("html_url"),
                            "created_at": i.get("created_at"),
                            "source": lbl.split(":")[-1]})
    return out, None


def collect_ledger_runs():
    """The last few runs, one per candidate, from the ledger's run table joined to
    the candidate it attempted: the fleet's recent memory, so it does not repeat a
    halted, rejected or rolled-back candidate. No ledger -> nothing here."""
    out = []
    try:
        import fleet.ledger as ledger
        for r in ledger.recent_runs(LEDGER_RUN_LIMIT):
            halt = r.get("halt") if isinstance(r.get("halt"), dict) else None
            out.append({"run_id": r["id"], "pipeline": r["pipeline"], "repo": r["repo"], "trigger": r["trigger"],
                        "outcome": r["outcome"], "fingerprint": r["fingerprint"], "title": r["title"],
                        "state": r["state"], "pr_url": r["pr_url"],
                        "halt": f"{halt['stage']}: {halt['reason']}" if halt else None,
                        "started_at": str(r["started_at"] or ""), "finished_at": str(r["finished_at"] or "")})
    except Exception as e:
        return out, f"ledger unavailable: {type(e).__name__}: {str(e)[:120]}"
    return out, None


def collect_reviewer_feedback():
    """Reviewer comments on the fleet's own open agent/* PRs: the follow-ups
    that say 'needs X' / 'not repeatable'. Same-repo only; fork PRs are not the
    fleet's to act on."""
    out = []
    prefix = "agent/"
    for repo in github.repos_from_env():
        try:
            prs = github.api(f"/repos/{repo}/pulls?state=open&per_page=30")
        except Exception as e:
            print(f"collect: {repo}: PRs: {type(e).__name__}")
            continue
        for pr in prs:
            head = pr.get("head", {}).get("ref", "")
            if not head.startswith(prefix):
                continue
            try:
                comments = github.api(pr["comments_url"] + "?per_page=100")
            except Exception:
                continue
            for c in comments:
                body = c.get("body") or ""
                low = body.lower()
                # only the comments that carry a concrete pointer forward
                if any(k in low for k in ("needs ", "not repeatable", "retry ",
                                          "reproduce ", "follow-up", "feedback:")):
                    out.append({"repo": repo, "number": pr["number"],
                                "head": head, "author": c.get("user", {}).get("login"),
                                "body": body[:500], "created_at": c.get("created_at")})
                    break
    return out, None


def collect_forum():
    """Ideas and open questions on the forum: what a human or an agent dumped on
    fleet.example.com becomes a candidate source (Chris, 2026-09-06: "status,
    scratchpad, and dumping ground for ideas"). No ledger -> nothing here."""
    try:
        from fleet import ledger
        rows = [r for t in ("idea", "question") for r in ledger.posts(limit=20, topic=t, unanswered=True)]
    except Exception as e:
        return [], f"forum unreachable: {type(e).__name__}"
    # The ideator opens its posts with `[idea:<id>]` (lineage spec, 2026-09-10): the
    # token stays in `text` for the investigator to copy into its finding, and the
    # id rides alongside so publish can close the loop on the idea.
    return [{"post": r["id"], "topic": r["topic"], "by": r["author"], "text": str(r["body"])[:1500],
             "idea": ideas.idea_in(str(r["body"])), "ref": r.get("ref"),
             "created_at": str(r.get("created_at") or ""), "count": 1} for r in rows], None


ALERTMANAGER_URL = os.environ.get("ALERTMANAGER_URL", "http://alertmanager.monitoring.svc.cluster.local:9093")


def collect_alerts():
    """Active Alertmanager alerts, grouped by (alertname, namespace) with a count:
    the cluster's own view of what is wrong, as improvement evidence. A dead
    Alertmanager just yields nothing here."""
    try:
        alerts = json.load(urllib.request.urlopen(f"{ALERTMANAGER_URL}/api/v2/alerts?active=true", timeout=15))
    except Exception as e:
        return [], f"alertmanager unreachable: {type(e).__name__}"
    groups = collections.defaultdict(list)
    for a in alerts:
        lb = a.get("labels", {})
        groups[(lb.get("alertname", "?"), lb.get("namespace", ""))].append(a)
    out = []
    for (name, ns), items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        newest = max((a.get("startsAt") or "" for a in items), default="")
        out.append({"alert": name, "namespace": ns, "count": len(items), "created_at": newest,
                    "severity": items[0].get("labels", {}).get("severity"),
                    "summary": (items[0].get("annotations", {}).get("summary") or "")[:200],
                    "objects": sorted({a.get("labels", {}).get("pod") or a.get("labels", {}).get("job_name") or "" for a in items} - {""})[:6]})
    return out, None


def rank(items):
    """Rank a source's items by recurrence weight (count if present, else 1)
    then recency; each item also carries a `source` so the model stage knows
    where it came from."""
    def key(x):
        count = x.get("count", 1) or 1
        return (count, str(x.get("created_at") or x.get("finished_at") or x.get("started_at") or ""))
    return sorted(items, key=key, reverse=True)


def main():
    evidence = {"sources": {}}
    flat = []  # ordered across sources, strongest first, for investigate.jsonl

    for name, fn in (("workbench", collect_workbench),
                     ("fleet_issues", collect_fleet_issues),
                     ("ledger_runs", collect_ledger_runs),
                     ("reviewer_feedback", collect_reviewer_feedback),
                     ("forum", collect_forum),
                     ("alerts", collect_alerts)):
        items, note = fn()
        ranked = rank(items)
        evidence["sources"][name] = {"count": len(ranked), "note": note}
        for it in ranked:
            flat.append({**it, "source": name})
        print(f"collect: {name}: {len(ranked)} items" + (f" ({note})" if note else ""))

    evidence["recent_runs"] = evidence["sources"].get("ledger_runs", {}).get("count", 0)
    evidence["recurrences"] = flat
    os.makedirs(PIPELINE_DIR, exist_ok=True)
    json.dump(evidence, open(f"{PIPELINE_DIR}/00-evidence.json", "w"), indent=1)
    print(f"collect: {len(flat)} evidence items across {len(evidence['sources'])} sources "
          f"=> {PIPELINE_DIR}/00-evidence.json")


if __name__ == "__main__":
    main()
