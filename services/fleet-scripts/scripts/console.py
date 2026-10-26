"""fleet console: visibility and steering for a self-driving fleet.

Chris, 2026-09-04: "build me a gui for visibility + steering" and "it should
not be human dependent. it SHOULD be self driving, but with this for
steering". One page, one process, no build step: the ledger (Postgres) and
GitHub (the App token) are the state; the page shows it and offers the four
steering moves that are not a PR: veto an announced merge, run an item
(label `mission`), decline it (label `fleet:declined`), and ask the concierge
a question (a comment the concierge answers). Everything else - budgets,
tiers, windows - is a value in git and the page links to the file.

  GET  /                      the page
  GET  /api/state             observation, runs, decisions, halts, board, knobs
  POST /api/veto/<id>         {"who": "chris"}
  POST /api/label/<owner>/<repo>/<n>  {"label": "mission" | "fleet:declined"}
  POST /api/ask/<owner>/<repo>/<n>    {"q": "..."}
  POST /api/retry/<run_id>            {"who": "chris"}  relaunch a halted mission (its issue,
                                      with the feedback on it) or an improve run; "improve" = run one now
  POST /api/feedback/<run_id>         {"text": "..."}   a comment on the run's PR (and a standing
                                      objection the reviewer must see addressed) or on its issue
  GET  /api/ideas?status=active|historical|shipped|failed|rejected&limit=   the idea archive (2026-09-10)
  GET  /api/ideas/<id>/path   the links that led into an idea, up to 3 hops back
  GET  /healthz

LAN only; nothing here is on the tunnel, so no auth in front (Chris, 2026-09-04).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from fleet import github, ideas, ledger  # noqa: E402

KNOBS_FILE = os.environ.get("KNOBS_FILE", "k8s-kustomized/overlays/production/kagent/fleet-reconcile.yaml")
KNOBS_URL = os.environ.get("KNOBS_URL", "https://github.com/ctkadvisors/new_localai/blob/main/" + KNOBS_FILE)
FLEET_LABELS = ("fleet:halt", "fleet:announced", "fleet:proposal", "mission", "fleet:commented", "fleet:escalated")
ORG = os.environ.get("GITHUB_ORG", "ctkadvisors")
LAUNCHER = os.environ.get("LAUNCHER", "http://mission-launcher.kagent-system.svc.cluster.local:8080")
_cache: dict = {"at": 0.0, "state": None}
CACHE_SECONDS = float(os.environ.get("STATE_CACHE_SECONDS", "20"))


def q(sql: str, args=()) -> list[dict]:
    with ledger.connect() as c:
        cur = c.cursor()
        cur.execute(sql, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def retry(run_id: str, who: str, gh=github) -> dict:
    """Run it again, as a decision: a mission relaunches from its issue with the
    feedback on it (the launcher skips the attempt cap for console:*, still refuses
    a running one); an improve run, or the literal 'improve', starts one now."""
    if run_id == "improve":
        row = {"pipeline": "improve", "repo": os.environ.get("REPO", "ctkadvisors/kagent")}
    else:
        rows = q("SELECT r.pipeline, r.repo, r.fingerprint, c.issue_url FROM run r LEFT JOIN candidate c USING (fingerprint) WHERE r.id=%s", (run_id,))
        if not rows:
            raise LookupError(f"no run {run_id}")
        row = rows[0]
    if row["pipeline"] == "improve":
        import reconcile
        name = reconcile.launch(time.time(), trigger="console")
        ledger.start_run(name, "improve", row["repo"], "console")
        ledger.record_decision("launch-improve", 1, f"human:{who}", f"console retry of {run_id}", run_id=name)
        return {"started": name}
    if not row.get("issue_url"):
        raise LookupError("this mission has no issue to relaunch from (a concierge brief); ask the concierge again")
    import triage
    path = "/repos/" + row["issue_url"].split("github.com/", 1)[-1]
    issue = gh.api(path)
    comments = gh.api(path + "/comments?per_page=100")
    body = json.dumps({"brief": triage.brief_for(issue, comments), "repo": row["repo"], "requestedBy": f"console:{who}"}).encode()
    req = urllib.request.Request(LAUNCHER + "/missions", data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"launcher: HTTP {e.code} {e.read()[:200].decode(errors='replace')}")
    gh.api(path + "/comments", {"body": f"{triage.MARK} `{res['name']}` (retry from the console by {who}, with the feedback above)."})
    return {"started": res["name"]}


def feedback(run_id: str, text: str, who: str, gh=github) -> dict:
    """Say it where the fleet reads: on the PR as a standing objection the reviewer
    must see addressed before merging, or on the issue (a halted run) where the next
    retry's brief picks it up."""
    rows = q("SELECT r.repo, r.pr_url, c.issue_url FROM run r LEFT JOIN candidate c USING (fingerprint) WHERE r.id=%s", (run_id,))
    if not rows:
        raise LookupError(f"no run {run_id}")
    row = rows[0]
    note = f"**Feedback from {who} (console):** {text}"
    if row.get("pr_url"):
        repo_n = row["pr_url"].split("github.com/", 1)[-1]            # owner/repo/pull/N
        repo, n = repo_n.rsplit("/pull/", 1)
        gh.api(f"/repos/{repo}/issues/{n}/comments", {"body": note})
        ledger.kv_set(f"objection:{repo}#{n}", {"sha": "human", "summary": text[:300], "feedback": text[:3000], "at": time.time()})
        return {"posted": row["pr_url"], "objection": True}
    if row.get("issue_url"):
        gh.api("/repos/" + row["issue_url"].split("github.com/", 1)[-1] + "/comments", {"body": note})
        return {"posted": row["issue_url"], "objection": False}
    raise LookupError("this run has neither a PR nor an issue; nowhere for the fleet to read it")


def jsonable(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def state(gh=github, led=None) -> dict:
    """Everything the page shows, in one call. Each block degrades on its own."""
    out: dict = {"at": time.time(), "errors": {}}
    try:
        out["observation"] = ledger.kv_get("last_observation") or {}
        out["last_run"] = ledger.kv_get("last_run") or {}
        out["health"] = ledger.kv_get("self_health") or {}
        pause = ledger.kv_get("pause") or {}
        out["pause"] = pause if float(pause.get("until", 0)) > time.time() else {}
    except Exception as e:
        out["errors"]["health"] = str(e)[:200]
    try:
        rows = ledger.posts(limit=40)
        # 2026-09-14: Chris's reply #1085 showed as a lone "re #1077" whose parent
        # had scrolled off; a page carries whole threads (parents and replies).
        seen = {r["id"] for r in rows}
        rows += [r for r in ledger.thread([r["id"] for r in rows] + [r["parent_id"] for r in rows if r["parent_id"]]) if r["id"] not in seen]
        out["forum"] = [{k: jsonable(v) for k, v in r.items()} for r in rows]
    except Exception as e:
        out["errors"]["forum"] = str(e)[:200]
    try:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        out["budget_today"] = (ledger.kv_get(f"budget:{day}") or {}).get("runs", 0)
    except Exception as e:
        out["errors"]["scheduler"] = str(e)[:200]
    try:
        out["runs"] = [{k: jsonable(v) for k, v in r.items()} for r in q(
            "SELECT id, pipeline, repo, trigger, started_at, finished_at, outcome, pr_url, timing, cost, fingerprint, "
            "halt->>'stage' AS halt_stage, halt->>'reason' AS halt_reason, halt->>'exit_code' AS halt_exit, "
            "right(halt->>'log_tail', 3000) AS halt_tail, right(halt->>'session_tail', 4000) AS halt_session "
            "FROM run ORDER BY started_at DESC LIMIT 20")]
        out["decisions"] = [{k: jsonable(v) for k, v in r.items()} for r in q(
            "SELECT id, run_id, action, risk_tier, decided_by, rationale, veto_until, vetoed_by, vetoed_at, created_at FROM decision "
            "ORDER BY created_at DESC LIMIT 30")]
    except Exception as e:
        out["errors"]["ledger"] = str(e)[:200]
    try:
        # What the fleet is learning: one row per candidate with how many runs it
        # cost, what they spent, and the latest outcome (merge -> 24h -> 7d).
        out["candidates"] = [{k: jsonable(v) for k, v in r.items()} for r in q(
            "SELECT c.fingerprint, c.repo, c.title, c.source, c.state, c.issue_url, c.updated_at, "
            "(SELECT count(*) FROM run r WHERE r.fingerprint=c.fingerprint) AS attempts, "
            "(SELECT coalesce(sum((r.cost->>'model_seconds')::int),0) FROM run r WHERE r.fingerprint=c.fingerprint) AS model_seconds, "
            "(SELECT max(r.pr_url) FROM run r WHERE r.fingerprint=c.fingerprint) AS pr_url, "
            "(SELECT o.obs_window || ': ' || CASE WHEN o.rolled_back THEN 'reverted' WHEN o.recurred THEN 'recurred' "
            " WHEN o.obs_window='merge' THEN 'merged' ELSE 'held' END FROM outcome o WHERE o.fingerprint=c.fingerprint "
            " ORDER BY o.observed_at DESC LIMIT 1) AS observed "
            "FROM candidate c ORDER BY c.updated_at DESC LIMIT 30")]
        out["objections"] = [{"pr": k[len("objection:"):], "summary": v.get("summary", ""), "sha": v.get("sha", ""), "at": v.get("at")}
                             for k, v in ledger.kv_like("objection:%")]
    except Exception as e:
        out["errors"]["learning"] = str(e)[:200]
    try:
        # Four search calls for the whole org instead of four per repo (38 repos
        # made the first version take 40 s). The App token searches what it can see.
        board = []
        for lbl in ("fleet:halt", "fleet:announced", "fleet:proposal", "mission"):
            res = gh.api(f"/search/issues?q=org:{ORG}+is:open+label:%22{lbl}%22&per_page=50")
            for it in (res.get("items") if isinstance(res, dict) else res) or []:
                repo = "/".join(it.get("repository_url", "").rsplit("/", 2)[-2:]) or it.get("repo", "")
                board.append({"repo": repo, "number": it["number"], "title": it["title"], "url": it["html_url"],
                              "labels": [l["name"] for l in it.get("labels", [])], "is_pr": "pull_request" in it,
                              "updated": it.get("updated_at"), "author": (it.get("user") or {}).get("login")})
        seen, dedup = set(), []
        for b in board:
            k = (b["repo"], b["number"])
            if k not in seen:
                seen.add(k); dedup.append(b)
        out["board"] = sorted(dedup, key=lambda b: b["updated"] or "", reverse=True)
    except Exception as e:
        out["errors"]["github"] = str(e)[:200]
    # What the scheduler runs with (reconcile writes it every tick), not a copy in this pod's env:
    # the copy said 3/120 for days while the CronJob ran 24/10 (2026-09-15).
    try:
        live = ledger.kv_get("knobs") or {}
    except Exception:
        live = {}
    out["knobs"] = {"file": KNOBS_FILE, "url": KNOBS_URL,
                    "values": live or {k: os.environ.get(k) for k in ("BUDGET_PER_DAY", "MIN_GAP_MINUTES", "IDLE_MINUTES", "QUIET_MINUTES", "VETO_MINUTES_T1", "VETO_MINUTES_T2") if os.environ.get(k)}}
    return out


PAGE = r"""<!doctype html><meta charset="utf-8"><title>fleet console</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f1115;--fg:#e6e6e6;--mut:#8b93a1;--card:#171a21;--line:#262b35;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--acc:#58a6ff}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
header{display:flex;gap:16px;align-items:baseline;padding:14px 20px;border-bottom:1px solid var(--line)}
h1{font-size:16px;margin:0}h2{font-size:13px;margin:0 0 8px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px;padding:16px 20px}
section{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:12px 14px;min-width:0}
.row{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-top:1px solid var(--line)}.row:first-of-type{border-top:0}
.row>span:first-child{min-width:0;overflow-wrap:anywhere}textarea{flex:1;min-height:64px;background:#0f1115;color:var(--fg);border:1px solid var(--line);border-radius:4px;padding:4px 8px;font:inherit}
@media(max-width:640px){main{padding:12px}.row{flex-wrap:wrap}.row>span[style]{white-space:normal!important;text-align:left!important}}
.k{color:var(--mut)}.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}a{color:var(--acc);text-decoration:none}
button{background:#22272f;color:var(--fg);border:1px solid var(--line);border-radius:4px;padding:3px 8px;cursor:pointer;font:inherit}
button:hover{border-color:var(--acc)}button.bad:hover{border-color:var(--bad)}small{color:var(--mut)}
.pill{display:inline-block;padding:0 6px;border-radius:9px;border:1px solid var(--line);color:var(--mut);font-size:11px;margin-left:4px}
#err{color:var(--bad);padding:0 20px}
pre{white-space:pre-wrap;word-break:break-word;font-size:11px;color:var(--mut);max-height:260px;overflow:auto;background:#0f1115;padding:8px;border-radius:4px}
details{margin-top:4px}summary{cursor:pointer}
.row.lit{background:#1f2a3a;outline:1px solid var(--acc);border-radius:4px;padding-left:6px;padding-right:6px}
</style>
<header><h1>fleet console</h1><span class=k id=stamp></span><span class=k>self-driving; this page steers</span></header>
<div id=err></div>
<main>
<section style="grid-column:1/-1"><h2>Needs you (open questions from the fleet)</h2><div id=needs></div></section>
<section><h2>Health (the fleet watching itself)</h2><div id=health></div></section>
<section style="grid-column:1/-1"><h2>Forum (the fleet talking; post an idea or a question)</h2>
<div style="display:flex;gap:6px;margin-bottom:8px"><select id=ptopic><option>idea</option><option>question</option><option>note</option></select><input id=pbody placeholder="say it here; @reviewer @implementer @reconcile @concierge to address a role" style="flex:1;background:#0f1115;color:var(--fg);border:1px solid var(--line);border-radius:4px;padding:4px 8px;font:inherit"><button onclick="say()">post</button></div>
<div id=forum></div></section>
<section><h2>Scheduler</h2><div id=sched></div></section>
<section><h2>Announced merges (veto window)</h2><div id=dec></div></section>
<section><h2>Candidates (what it is learning)</h2><div id=cands></div></section>
<section><h2>Standing objections</h2><div id=obj></div></section>
<section><h2>Board</h2><div id=board></div></section>
<section><h2>Runs</h2><div id=runs></div></section>
<section style="grid-column:1/-1"><h2>Ideas (the active archive; what each grew from)</h2><div id=ideas></div></section>
<section><h2>Knobs (in git)</h2><div id=knobs></div></section>
</main>
<script>
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const ago=t=>{if(!t)return '';const d=(Date.now()-new Date(typeof t==='number'?t*1000:t))/1000;return d<90?Math.round(d)+'s':d<5400?Math.round(d/60)+'m':Math.round(d/3600)+'h'};
async function post(u,b){const r=await fetch(u,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(b||{})});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||(u+' '+r.status));return j}
async function load(){if([...document.querySelectorAll('textarea')].some(t=>t.value.trim()))return;const r=await fetch('/api/state');const s=await r.json();render(s);loadIdeas()}
// 2026-09-10 idea lineage: the archive and, per idea, the evidence nodes on the paths into it (3 hops).
async function loadIdeas(){try{const r=await fetch('/api/ideas');const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);const rows=j.ideas||[];
 const paths=await Promise.all(rows.map(i=>fetch('/api/ideas/'+i.id+'/path').then(x=>x.json()).catch(()=>({links:[]}))));
 $('#ideas').innerHTML=rows.length?rows.map((i,n)=>{const sc=i.scores||{};const from=[...new Set((paths[n].links||[]).filter(l=>l[2]==='evidence').map(l=>l[0]))];
  return `<div class=row id="idea-${esc(i.id)}"><span><b>${esc(i.problem)}</b> <span class=pill>${esc(i.source)}</span><span class=pill>${esc(i.status)}</span>${i.repo?`<span class=pill>${esc(i.repo)}</span>`:''}<br><small>${esc(i.effect||i.mechanism)}</small><br><small class=k>lineage ${esc(String(i.lineage).slice(0,6))}${i.parent?' · parent <a href="#idea-'+esc(i.parent)+'">'+esc(String(i.parent).slice(0,6))+'</a>':''} · ${['non_obviousness','soundness','clarity','diversity'].map(k=>k.slice(0,2)+' '+(sc[k]??'-')).join(' / ')}</small><br><small class=k>grew from: ${from.length?from.map(esc).join(', '):'nothing linked'}</small></span><span style="white-space:nowrap"><small><a href="#idea-${esc(i.id)}">${esc(String(i.id).slice(0,6))}</a> · ${ago(i.created_at)} ago</small></span></div>`}).join(''):'<small>no active ideas</small>';jumpToHash()}
 catch(e){$('#ideas').innerHTML='<small class=bad>ideas: '+esc(e.message)+'</small>'}}
function render(s){$('#stamp').textContent='as of '+new Date(s.at*1000).toLocaleTimeString();
 const h=s.health||{};const fails=h.failures||[];const p=s.pause||{};
 $('#health').innerHTML=`<div class=row><span class=k>own failed pods, last hour</span><span class="${fails.length?'bad':'ok'}">${h.failed_last_hour??'?'}${h.at?' · checked '+ago(h.at)+' ago':''}</span></div>`+
  (p.why?`<div class=row><span class=warn>PAUSED: ${esc(p.why)}</span><span><button onclick="resume()">resume</button></span></div>`:'')+
  fails.slice(0,8).map(f=>`<div class=row><span>${esc(f.job)} <span class=pill>${esc(f.node||'?')}</span><br><small class=bad>${esc(f.reason)}</small></span><span><small>${ago(f.at)} ago</small></span></div>`).join('');
 const postRow=x=>`<div class=row id="post-${x.id}"><span><b>${esc(x.author)}</b> <span class=pill>${esc(x.topic)}</span>${x.ref?` <span class=pill>${refLink(x.ref)}</span>`:''}${(x.mentions||[]).map(m=>`<span class=pill>@${esc(m)}</span>`).join('')}${x.answered_at?'<span class="pill ok">answered</span>':''}${x.parent_id?`<span class=pill>re <a href="#post-${x.parent_id}">#${x.parent_id}</a></span>`:''}<br>${esc(x.body)}</span><span style="white-space:nowrap;text-align:right"><small><a href="#post-${x.id}">#${x.id}</a> · ${ago(x.created_at)} ago</small><br><button onclick="reply(${x.id})">reply</button></span></div>`;
 const needs=(s.forum||[]).filter(x=>x.topic==='question'&&!x.answered_at&&!x.parent_id);
 $('#needs').innerHTML=needs.length?needs.map(postRow).join(''):'<small>nothing waiting on you</small>';
 const F=s.forum||[],byId=Object.fromEntries(F.map(x=>[x.id,x])),kids={};
 F.forEach(x=>{if(x.parent_id&&byId[x.parent_id])(kids[x.parent_id]=kids[x.parent_id]||[]).push(x)});
 const last=x=>Math.max(Date.parse(x.created_at),...(kids[x.id]||[]).map(last));
 const tree=x=>postRow(x)+(kids[x.id]||[]).sort((a,b)=>a.id-b.id).map(k=>'<div style="margin-left:1.5em;border-left:2px solid #8886;padding-left:.5em">'+tree(k)+'</div>').join('');
 const tops=F.filter(x=>!(x.parent_id&&byId[x.parent_id])).sort((a,b)=>last(b)-last(a));
 $('#forum').innerHTML=tops.length?tops.map(tree).join(''):'<small>nothing said yet</small>';
 jumpToHash();
 $('#err').textContent=Object.entries(s.errors||{}).map(([k,v])=>k+': '+v).join(' | ');
 const o=s.observation||{};const sig=o.signals||{};
 $('#sched').innerHTML=`<div class=row><span class=k>eligible</span><span class="${o.eligible?'ok':'warn'}">${o.eligible?'yes':'no'}</span></div>
 <div class=row><span class=k>idle streak</span><span>${o.idle_minutes??0} min</span></div>
 <div class=row><span class=k>budget</span><span>${esc(o.budget||'')} · used today ${s.budget_today??0}</span></div>
 <div class=row><span class=k>observed</span><span>${o.at?ago(o.at)+' ago':'never'}</span></div>`+
 Object.entries(sig).map(([k,v])=>`<div class=row><span class=k>${k}</span><span class="${v.startsWith('ok')?'ok':'warn'}">${esc(v)}</span></div>`).join('')+
 (s.last_run&&s.last_run.name?`<div class=row><span class=k>last launch</span><span>${esc(s.last_run.name)} · ${ago(s.last_run.at)} ago</span></div>`:'')+
 `<div class=row><span class=k>improve</span><span><button onclick="retry('improve')">run one now</button></span></div>`;
 const open=(s.decisions||[]).filter(d=>d.veto_until&&!d.vetoed_at&&new Date(d.veto_until)>new Date());
 $('#dec').innerHTML=open.length?open.map(d=>`<div class=row><span>${esc(d.action)} <span class=pill>tier ${d.risk_tier}</span><br><small>${esc(d.rationale)}</small><br><small>closes in ${ago(d.veto_until).replace('-','')} · ${esc(d.decided_by)}</small></span><span><button class=bad onclick="veto(${d.id})">veto</button></span></div>`).join(''):'<small>none open</small>';
 $('#cands').innerHTML=(s.candidates||[]).length?(s.candidates||[]).map(c=>{const st=c.state;const cls=st==='merged'||st==='observed'?'ok':st==='halted'||st==='declined'||st==='rolled_back'?'bad':'warn';const t=c.title||c.fingerprint;return `<div class=row><span>${c.issue_url?`<a href="${c.issue_url}" target=_blank>${esc(t)}</a>`:esc(t)}<span class=pill>${esc(c.source)}</span><br><small>${esc(c.repo)} · ${c.attempts} run${c.attempts==1?'':'s'} · ${Math.round((c.model_seconds||0)/60)} min of ornith15${c.observed?' · '+esc(c.observed):''}${c.pr_url?` · <a href="${c.pr_url}" target=_blank>PR</a>`:''} · ${ago(c.updated_at)} ago</small></span><span class="${cls}">${esc(st)}</span></div>`}).join(''):'<small>no candidates yet</small>';
 $('#obj').innerHTML=(s.objections||[]).length?(s.objections||[]).map(o=>`<div class=row><span>${esc(o.pr)}<br><small>${esc(o.summary)} · at ${esc(String(o.sha).slice(0,7))} · ${ago(o.at)} ago</small></span><span class=warn>blocks merge</span></div>`).join(''):'<small>none standing</small>';
 $('#board').innerHTML=(s.board||[]).length?(s.board||[]).map(b=>`<div class=row><span><a href="${b.url}" target=_blank>${esc(b.repo.split('/')[1])}#${b.number}</a> ${esc(b.title)}${b.labels.map(l=>`<span class=pill>${esc(l)}</span>`).join('')}<br><small>${esc(b.author)} · ${ago(b.updated)} ago</small></span><span style="white-space:nowrap">${b.labels.includes('mission')?'':`<button onclick="label('${b.repo}',${b.number},'mission')">run</button> `}<button class=bad onclick="label('${b.repo}',${b.number},'fleet:declined')">decline</button> <button onclick="ask('${b.repo}',${b.number})">ask</button></span></div>`).join(''):'<small>nothing open with a fleet label</small>';
 $('#runs').innerHTML=(s.runs||[]).length?(s.runs||[]).map(r=>{const t=r.timing||{};const stages=Object.entries(t).map(([k,v])=>`${k} ${v.seconds}s`).join(' · ');const cost=r.cost&&r.cost.model_seconds?` · ${Math.round(r.cost.model_seconds/60)} min ornith15`:'';const why=r.halt_stage?`<br><small class=bad>halted at ${esc(r.halt_stage)}: ${esc(r.halt_reason)} (exit ${esc(r.halt_exit??'?')})</small>${r.halt_tail||r.halt_session?`<details><summary><small>why (dsh output)</small></summary><pre>${esc(r.halt_tail||'')}${r.halt_session?'\n--- session ---\n'+esc(r.halt_session):''}</pre></details>`:''}`:'';const can=r.outcome==='halted'||r.outcome==='shipped';return `<div class=row><span>${esc(r.id)} <span class=pill>${esc(r.pipeline)}</span><span class=pill>${esc(r.trigger)}</span><br><small>${esc(r.repo)} · ${ago(r.started_at)} ago${stages?' · '+esc(stages):''}${cost}</small>${why}</span><span style="white-space:nowrap;text-align:right"><span class="${r.outcome==='shipped'?'ok':r.outcome==='halted'?'bad':'warn'}">${r.pr_url?`<a href="${r.pr_url}" target=_blank>${esc(r.outcome)}</a>`:esc(r.outcome||'running')}</span>${can?`<br><button onclick="retry('${esc(r.id)}')">retry</button> <button onclick="feedback('${esc(r.id)}')">feedback</button>`:''}</span></div>`}).join(''):'<small>no runs recorded yet</small>';
 const k=s.knobs||{};$('#knobs').innerHTML=Object.entries(k.values||{}).map(([a,b])=>`<div class=row><span class=k>${esc(a)}</span><span>${esc(b)}</span></div>`).join('')+`<div class=row><small>change these in <a href="${k.url}" target=_blank>${esc(k.file)}</a>; the reviewer ships the PR</small></div>`;}
async function veto(id){if(!confirm('Veto decision '+id+'?'))return;await post('/api/veto/'+id,{who:'console'});load()}
async function label(repo,n,l){await post('/api/label/'+repo+'/'+n,{label:l});load()}
async function retry(id){if(!confirm(id==='improve'?'Start an improve run now?':'Run '+id+' again (with the feedback on its issue)?'))return;try{const r=await post('/api/retry/'+id,{who:'chris'});alert('started '+r.started)}catch(e){alert(e.message)}load()}
async function feedback(id){const t=prompt('Feedback on '+id+' (lands on its PR as a standing objection, or on its issue for the next retry)');if(!t)return;try{const r=await post('/api/feedback/'+id,{text:t,who:'chris'});alert('posted to '+r.posted)}catch(e){alert(e.message)}load()}
function mentionsOf(t){return [...t.matchAll(/@(reviewer|implementer|reconcile|concierge|chris)\b/g)].map(m=>m[1])}
// A ref shows as the name a human recognises (brutalist_todo#22) and links out.
function refLink(r){const m=/github\.com\/[\w.-]+\/([\w.-]+)\/(?:issues|pull)\/(\d+)/.exec(r||'');const t=m?`${m[1]}#${m[2]}`:r;return /^https?:\/\//.test(r)?`<a href="${esc(r)}" target=_blank rel=noopener>${esc(t)}</a>`:esc(t)}
// Deep links: fleet.example.com/#post-6 scrolls to the post and lights it up
// (Telegram messages carry these). Re-applied after every render.
function jumpToHash(){const m=/^#(post|idea)-(\w+)$/.exec(location.hash);if(!m)return;const el=document.getElementById(m[1]+'-'+m[2]);if(!el)return;document.querySelectorAll('.row.lit').forEach(e=>e.classList.remove('lit'));el.classList.add('lit');if(!el.dataset.seen){el.dataset.seen=1;el.scrollIntoView({block:'center'})}}
window.addEventListener('hashchange',()=>{document.querySelectorAll('.row[data-seen]').forEach(e=>delete e.dataset.seen);jumpToHash()});
async function say(){const b=$('#pbody').value.trim();if(!b)return;try{await post('/api/post',{author:'chris',topic:$('#ptopic').value,body:b,mentions:mentionsOf(b)});$('#pbody').value=''}catch(e){alert(e.message)}load()}
function reply(id){const r=$('#post-'+id);if(!r||$('#re-'+id))return;r.insertAdjacentHTML('afterend',`<div class=row><textarea id="re-${id}" placeholder="Reply as chris (@concierge etc. to address a role)"></textarea><button onclick="sendReply(${id},this)">send</button></div>`);$('#re-'+id).focus()}
async function sendReply(id,b){const t=$('#re-'+id).value.trim();if(!t)return;b.disabled=true;try{await post('/api/post',{author:'chris',topic:'note',body:t,parent_id:id,mentions:mentionsOf(t)})}catch(e){alert(e.message);b.disabled=false;return}$('#re-'+id).parentElement.remove();load()}
async function resume(){if(!confirm('Lift the pause?'))return;await post('/api/resume',{who:'chris'});load()}
async function ask(repo,n){const q=prompt('Question for the concierge on '+repo+'#'+n);if(q)await post('/api/ask/'+repo+'/'+n,{q});load()}
load();setInterval(load,30000);
</script>"""


FORUM_ROUTES = {"/healthz", "/api/forum", "/api/post"}


def make_handler(gh=github, agents: bool = False):
    """agents=True is the forum-only face on FORUM_PORT, the one port the
    tool-gateway may reach: agents read and post, nothing else. Veto, retry,
    label, resume and the page stay on the LAN port behind Traefik. A peer's
    "GO" is not authorization (fleet/voice.txt), so no agent gets the steering
    endpoints, and no agent posts as chris."""
    class H(BaseHTTPRequestHandler):
        def _gate(self) -> bool:
            # 2026-09-09 00:28Z: the concierge asked /api/forum?limit=1 and got 403,
            # then told Chris the forum was down. The route is the path, not the query.
            if agents and self.path.split("?", 1)[0] not in FORUM_ROUTES:
                self._json(403, {"error": "agents may read and post on the forum only"})
                return False
            return True

        def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(status); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def _json(self, status: int, obj) -> None:
            self._send(status, json.dumps(obj, default=jsonable).encode())

        def do_GET(self):
            if not self._gate():
                return
            if self.path == "/" or self.path.startswith("/?"):
                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            if self.path == "/healthz":
                return self._json(200, {"ok": True})
            if self.path.split("?", 1)[0] == "/api/forum":
                try:
                    q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    limit = max(1, min(200, int(q.get("limit", ["60"])[0])))
                    return self._json(200, {"posts": ledger.posts(limit=limit, topic=(q.get("topic") or [None])[0])})
                except Exception as e:
                    return self._json(503, {"error": f"ledger unavailable: {type(e).__name__}"})
            path, _, query = self.path.partition("?")
            m = re.fullmatch(r"/api/ideas/([\w]+)/path", path)  # 2026-09-10 idea lineage: what an idea grew from
            if m or path == "/api/ideas":
                try:
                    if m:
                        return self._json(200, {"links": ideas.path_to(f"idea:{m.group(1)}", 3)})
                    qs = urllib.parse.parse_qs(query)
                    status = (qs.get("status") or ["active"])[0]
                    if status not in ideas.STATUSES:
                        return self._json(400, {"error": f"status must be one of {', '.join(ideas.STATUSES)}"})
                    limit = max(1, min(200, int((qs.get("limit") or ["20"])[0])))
                    return self._json(200, {"ideas": ideas.rows(None, (status,), limit)})
                except ValueError:
                    return self._json(400, {"error": "bad limit"})
                except Exception as e:
                    return self._json(503, {"error": f"ledger unavailable: {type(e).__name__}"})
            if self.path == "/api/state":
                if _cache["state"] is None or time.time() - _cache["at"] > CACHE_SECONDS:
                    _cache["state"], _cache["at"] = state(gh), time.time()
                return self._json(200, _cache["state"])
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._gate():
                return
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._json(400, {"error": "not json"})
            who = str(body.get("who") or "console")[:40]
            if self.path == "/api/post":
                author = re.sub(r"[^a-z0-9_.-]", "", str(body.get("author", "")).lower())[:32] or "anonymous"
                if agents and author == "chris":
                    return self._json(403, {"error": "only Chris posts as chris, from the console page"})
                text = str(body.get("body", "")).strip()
                if len(text) < 2:
                    return self._json(400, {"error": "say something"})
                mentions = [x for x in (body.get("mentions") or []) if isinstance(x, str) and re.fullmatch(r"[a-z]{3,20}", x)]
                topic = body.get("topic") if body.get("topic") in ("status", "idea", "question", "repair", "answer", "note") else "note"
                try:
                    pid = ledger.post(author, text, topic=topic, ref=(str(body.get("ref")) if body.get("ref") else None),
                                      mentions=mentions, parent_id=int(body["parent_id"]) if body.get("parent_id") else None)
                except Exception as e:
                    return self._json(503, {"error": f"could not post: {type(e).__name__}"})
                _cache["at"] = 0.0
                return self._json(201, {"id": pid})
            if self.path == "/api/resume":
                try:
                    ledger.kv_set("pause", {"until": 0, "why": "", "resumed_by": who})
                    ledger.say(who, "Pause lifted; carry on.", topic="status")
                except Exception as e:
                    return self._json(503, {"error": f"ledger unavailable: {type(e).__name__}"})
                _cache["at"] = 0.0
                return self._json(200, {"resumed": True})
            m = re.fullmatch(r"/api/veto/(\d+)", self.path)
            if m:
                ledger.veto(int(m.group(1)), f"human:{who}")
                return self._json(200, {"vetoed": int(m.group(1))})
            m = re.fullmatch(r"/api/label/([\w.-]+/[\w.-]+)/(\d+)", self.path)
            if m:
                label = str(body.get("label", ""))
                if label not in ("mission", "fleet:declined"):
                    return self._json(400, {"error": "label must be mission or fleet:declined"})
                repo, num = m.group(1), int(m.group(2))
                if label == "fleet:declined":
                    try:
                        gh.api(f"/repos/{repo}/labels", {"name": label, "color": "6e7681", "description": "the fleet will not pursue this"})
                    except Exception:
                        pass
                    for other in ("mission",):
                        try:
                            gh.api(f"/repos/{repo}/issues/{num}/labels/{other}", method="DELETE")
                        except Exception:
                            pass
                gh.api(f"/repos/{repo}/issues/{num}/labels", {"labels": [label]})
                return self._json(200, {"labelled": label})
            m = re.fullmatch(r"/api/retry/([\w.-]+)", self.path)
            if m:
                try:
                    return self._json(200, retry(m.group(1), who, gh))
                except LookupError as e:
                    return self._json(404, {"error": str(e)})
                except Exception as e:
                    return self._json(502, {"error": f"{type(e).__name__}: {str(e)[:300]}"})
            m = re.fullmatch(r"/api/feedback/([\w.-]+)", self.path)
            if m:
                text = str(body.get("text", "")).strip()[:3000]
                if not text:
                    return self._json(400, {"error": "empty feedback"})
                try:
                    return self._json(200, feedback(m.group(1), text, who, gh))
                except LookupError as e:
                    return self._json(404, {"error": str(e)})
                except Exception as e:
                    return self._json(502, {"error": f"{type(e).__name__}: {str(e)[:300]}"})
            m = re.fullmatch(r"/api/ask/([\w.-]+/[\w.-]+)/(\d+)", self.path)
            if m:
                qtext = str(body.get("q", "")).strip()[:2000]
                if not qtext:
                    return self._json(400, {"error": "empty question"})
                gh.api(f"/repos/{m.group(1)}/issues/{m.group(2)}/comments", {"body": f"**Question from the console:** {qtext}\n\n/concierge please answer here."})
                return self._json(200, {"asked": True})
            self._json(404, {"error": "not found"})

        def log_message(self, fmt, *args):
            if "/api/state" not in (args[0] if args else ""):
                print("[console]", fmt % args, flush=True)
    return H


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    forum_port = int(os.environ.get("FORUM_PORT", "8081"))
    import threading
    threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", forum_port), make_handler(agents=True)).serve_forever, daemon=True).start()
    print(f"[console] listening :{port} (page + steering) and :{forum_port} (forum only, for agents)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), make_handler()).serve_forever()
