#!/bin/sh
# One model stage of the staged pipeline: run dsh with the stage's prompt
# from /config, then validate the artifact it left in the pipeline dir.
# investigate also clones the repo (missions do that in brief.py).
#
# Every run ends legibly (Chris, 2026-09-04: two missions died in implement
# with "dsh session failed" and nothing else). dsh's full output is kept at
# $P/<stage>.log, its exit code and the last lines go into $P/stop, and
# the stage's wall time into $P/timing.json, whether or not it halts.
set -eu
S=$1
P=${PIPELINE_DIR:-/workspace/p}
REPO_DIR=${REPO_DIR:-/workspace/repo}
SCRIPTS=$(dirname "$0")
# seconds; a stage that runs longer is halted, not hung. implement gets an hour:
# a real change at ~40 tok/s on the spark ran past 1500 (mission-20260904-083236).
if [ "${1:-}" = implement ]; then STAGE_TIMEOUT=${STAGE_TIMEOUT:-3600}; else STAGE_TIMEOUT=${STAGE_TIMEOUT:-1500}; fi
DSH=${DSH:-dsh}
mkdir -p "$P"
[ -f "$P/quiet" ] && { echo "stage $S: quiet skip"; exit 0; }
[ -f "$P/stop" ] && { echo "stage $S: pipeline stopped upstream"; exit 0; }
START=$(date +%s)

halt() {  # halt <reason> [exit-code]: write $P/stop with the log tail
  python3 - "$S" "$1" "${2:-}" "$P" <<'PY'
import json, os, sys, time
stage, reason, code, p = sys.argv[1:5]
log = f"{p}/{stage}.log"
tail = "\n".join(open(log, errors="replace").read().splitlines()[-40:])[-4000:] if os.path.exists(log) else ""
st = f"{p}/{stage}.session-tail"
session_tail = open(st, errors="replace").read()[-6000:] if os.path.exists(st) else ""
json.dump({"stage": stage, "reason": reason, "exit_code": code, "log": log if os.path.exists(log) else None,
           "log_tail": tail, "session_tail": session_tail, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, open(f"{p}/stop", "w"))
PY
}
mark() {  # mark <status>: append this stage's wall time to $P/timing.json
  python3 - "$S" "$1" "$P" "$START" <<'PY'
import json, os, sys, time
stage, status, p, start = sys.argv[1:5]
f = f"{p}/timing.json"
t = json.load(open(f)) if os.path.exists(f) else {}
t[stage] = {"status": status, "seconds": round(time.time() - float(start)), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
m = f"{p}/{stage}.metrics.json"   # tool calls by name ride to the ledger with the timing (the LSP experiment reads them)
if os.path.exists(m):
    t[stage]["tool_calls"] = json.load(open(m)).get("tool_calls") or {}
json.dump(t, open(f, "w"))
PY
}

if [ "$S" = "investigate" ]; then
  # Guard is best-effort: anonymous GitHub API calls rate-limit at 60/hr/IP.
  # Unknown -> proceed; publish's branch-name collision is the backstop.
  OPEN=$(python3 -c '
import json, os, urllib.request
repo = os.environ.get("REPO", "ctkadvisors/kagent")
try:
    prs = json.load(urllib.request.urlopen(
        f"https://api.github.com/repos/{repo}/pulls?state=open&per_page=50", timeout=30))
    print(sum(1 for p in prs if p["head"]["ref"].startswith("agent/dsh-daily-")))
except Exception:
    print("unknown")') || OPEN=unknown
  if [ "$OPEN" = "unknown" ]; then
    echo "guard: GitHub unreachable/rate-limited — proceeding without pileup check"
  elif [ "$OPEN" != "0" ]; then
    echo "guard: $OPEN open agent/dsh-daily-* PR(s) — not stacking another"
    touch "$P/quiet"
    exit 0
  fi
fi
# clone.py (the stage before investigate/brief) already put the repo here.
if [ ! -d "$REPO_DIR/.git" ]; then
  echo "stage $S: no repo at $REPO_DIR (clone stage missing?)"
  halt "repo not cloned"; mark halted; exit 0
fi
cd "$REPO_DIR"
# dsh's own output is the diagnostic: all of it to $P/<stage>.log, exit code
# to $P/<stage>.rc (the pipeline's left side is a subshell in POSIX sh, so
# the code has to leave it through a file). `timeout` guards a hung session.
if command -v timeout >/dev/null 2>&1; then RUN="timeout -k 30 $STAGE_TIMEOUT"; else RUN=""; fi
BASE=$(cat "/config/$S.txt")
# Everything appended to the stage's own prompt (repo, voice, what we learned,
# tool schemas) is SUFFIX, so a second pass can rebuild a prompt from it.
# The repo this run works (reconcile chooses it from the evidence) and how the
# fleet talks to itself (fleet/voice.txt, one copy for every role).
SUFFIX="

REPOSITORY: ${REPO:-unknown} (the current directory is its clone)."
# How the fleet talks (fleet/voice.txt) rides in the clone's AGENTS.md, which dsh
# loads once per session (agent-instructions) instead of every prompt carrying it;
# the tool paragraphs are skills under /fleet/skills (skill-filesystem), loaded
# when the model asks for them. 2026-09-09: the suffix was ~4 KB per stage.
if [ ! -f "$REPO_DIR/AGENTS.md" ] && [ -f /fleet/fleet/voice.txt ]; then
  { cat /fleet/fleet/voice.txt; echo; [ -f "$REPO_DIR/CLAUDE.md" ] && echo "Repository guidance: read CLAUDE.md in this directory before changing anything."; } > "$REPO_DIR/AGENTS.md"
  mkdir -p "$REPO_DIR/.git/info" && echo "AGENTS.md" >> "$REPO_DIR/.git/info/exclude"   # never part of a commit
fi
SUFFIX="$SUFFIX
LIMITS: this stage has ${STAGE_TIMEOUT}s of wall time in total and a model that writes about 70 tokens a second with a 200k-token window; a single tool call that runs more than five minutes is a hang to kill, not patience; when a question needs a human, ask it early (ask_user_question), the answer can take twenty minutes.
SUBAGENTS: the subagent tool starts a fresh agent with its own context for a bounded side job (explore a directory, run one check, try one approach, read something long) and returns its final text; use it for parallel or throwaway work, never for the main edit, and give it a complete brief because it sees none of yours.
SKILLS (load one with the skill tool when you need it): ponytail (how to keep a change to the smallest diff that works), cluster (read-only kubectl), forum (read, post, ask), checks (failing CI lines for a commit), search (web), node-runner (allow-listed node actions), ledger (recent runs).
FLEET CODE: the pipeline running you (stage.sh, brief.py, validate.py, publish.py, reconcile.py, fleet/*.py) is in this pod at /fleet/scripts and /fleet/fleet; its source is ctkadvisors/new_localai services/fleet-scripts and the stage prompts are k8s-kustomized/overlays/production/kagent/improve-daily.yaml there. No other repo holds stage code; a change to how stages run belongs in new_localai."
# Ponytail (Chris, 2026-09-15: "if ponytail.dev is helpful, add it as a skill"):
# ornith15 does well on a small, on-task change and comes apart on a mid-sized
# one, so the implement stage carries the core always and the skill on demand.
if [ "$S" = implement ]; then SUFFIX="$SUFFIX
PONYTAIL (load the ponytail skill before your first edit): the deliverable is the smallest diff that works, in the fewest files. Reuse what the repo already has before writing anything new; no abstraction, config, or scaffolding the brief did not ask for; fix a bug once where every caller routes through, not per caller; leave one runnable check (verify.sh). Read the code you touch end to end first, then cut."; fi
# What the fleet has learned (fleet/memory.py): Chris's rules, past halts,
# objections, rollbacks — ranked against this run's brief. Read-only role.
LEARNED=$(python3 -c 'import sys, os; sys.path[:0]=["/fleet","/fleet/vendor"]; from fleet import memory; print(memory.recall(os.environ.get("REPO"), (os.environ.get("MISSION_BRIEF","") + " " + open("/config/'"$S"'.txt").read())[:2000]))' 2>/dev/null || true)
[ -n "$LEARNED" ] && SUFFIX="$SUFFIX

$LEARNED
End your report with one or more lines 'LESSON: <what the next run should know>' when you learned something a future run would pay for again; nothing generic."
# ornith15 keeps guessing Anthropic-style keys for dsh's file tools (file_text, path,
# old_string) and gets "missing required property" on every write. Say the schema once.
SUFFIX="$SUFFIX

TOOL SCHEMAS (exact keys): write{file_path, content}; str_replace_editor{command, path, old_str, new_str, file_text}; read{file_path}."
# Harness change 3 (2026-09-09): a question no longer ends the run. The forum
# provider (fleet-scripts/plugins/dsh-forum-questions) turns ask_user_question
# into a forum post and waits for the reply; the patch mounts it by name from
# the profile's node_modules, so it is copied there first.
if [ -d /fleet/plugins/dsh-forum-questions ]; then
  mkdir -p "$HOME/.dsh/profiles/headless/node_modules/@homelab" 2>/dev/null \
    && cp -r /fleet/plugins/dsh-forum-questions "$HOME/.dsh/profiles/headless/node_modules/@homelab/" 2>/dev/null || true
fi
export FORUM_AUTHOR="$S"
# Tie this stage's forum thread to the run (C1, 2026-09-09): without a ref every
# stage question lands on the forum at ref=NULL, so ask_concierge / context_for
# can never match a reply thread back to this run. RUN_ID is the run's own id; a
# run with none still posts exactly as before (the plugin falls back to null).
export FORUM_REF="${RUN_ID:-}"
PROMPT="$BASE$SUFFIX"
# Who thinks and who types (2026-09-08): the stages that decide run on the
# judge model when the overlay ships one (dsh-patch-judge.yml: qwen38, thinking
# on); implement and every fix pass stay on ornith15's hands.
PATCH=/config/dsh-patch.yml
# adjudicate only, for now: it reads two JSON artifacts and writes one. In the
# reviewer, qwen38 inside dsh's tool loop wandered and returned no JSON (#71,
# #72); investigate and test lean on tools, so they stay on ornith15 until a
# stage log proves the judge completes inside dsh.
# 2026-09-09 05:07Z: adjudicate on the judge inside dsh sat two hours with no
# output (improve-20260909-050500), the same dsh<->llama-server streaming break
# the reviewer hit. Until that is understood, every dsh stage runs on ornith15;
# the judge is reached directly (review.ask_judge, reconcile.ideate). Set
# JUDGE_STAGES to re-enable, e.g. JUDGE_STAGES=adjudicate.
case ",${JUDGE_STAGES:-}," in *",$S,"*) [ -f /config/dsh-patch-judge.yml ] && PATCH=/config/dsh-patch-judge.yml ;; esac
# LSP (2026-09-15, bench-gated): stages named in LSP_STAGES get dsh's lsp tool
# (definition/references/implementation/hover). The plugins are baked into
# agent-coder at /opt/dsh-plugins and copied, not linked, under the profile so they
# resolve dsh's own cordis; an image without them runs the stage as before.
case ",${LSP_STAGES:-}," in *",$S,"*)
  if [ -d /opt/dsh-plugins/node_modules/@deepseek-ai ] && [ -f /fleet/plugins/dsh-patch-lsp.yml ]; then
    mkdir -p "$HOME/.dsh/profiles/headless/node_modules" \
      && cp -r /opt/dsh-plugins/node_modules/. "$HOME/.dsh/profiles/headless/node_modules/" \
      && cat "$PATCH" /fleet/plugins/dsh-patch-lsp.yml > /tmp/dsh-patch-lsp.yml && PATCH=/tmp/dsh-patch-lsp.yml \
      && echo "stage $S: lsp tool mounted"
    # Mounted is not used: kagent#60's round had it and made 0 lsp calls against 33 bash
    # and 14 read (the tool's own prompt says search/read first). Say when it is the
    # cheaper tool. In SUFFIX, so an implement round's rebuilt prompt keeps it.
    SUFFIX="$SUFFIX
LSP: an lsp tool is mounted (goToDefinition, findReferences, goToImplementation, hover). For \"where is X defined\" and \"who calls X\" use it instead of grep and cat: one call returns the exact file:line list for a fraction of the tokens. Positions are 1-based line and character on the symbol; the first query after start can return only the declaration while the server indexes, so retry it once."
    PROMPT="$BASE$SUFFIX"
  fi ;;
esac
echo "stage $S: model patch $(basename "$PATCH")"
echo "stage $S: prompt bytes ${#PROMPT}"
# A pnpm repo with no pnpm on PATH cost every kagent round a hand-rolled install into
# /tmp and a --no-verify commit (the pre-commit hook runs pnpm), 2026-09-15. node:22
# ships corepack, which fetches the version the repo's packageManager pins.
if [ -f "$REPO_DIR/pnpm-lock.yaml" ] && ! command -v pnpm >/dev/null 2>&1 && command -v corepack >/dev/null 2>&1; then
  export COREPACK_HOME="${COREPACK_HOME:-/tmp/corepack}" COREPACK_ENABLE_DOWNLOAD_PROMPT=0
  mkdir -p /tmp/corepack-bin && (cd "$REPO_DIR" && corepack enable --install-directory /tmp/corepack-bin pnpm) >/dev/null 2>&1 \
    && export PATH="/tmp/corepack-bin:$PATH" && echo "stage $S: pnpm via corepack on PATH"
fi
run_dsh() {  # one dsh session with $PROMPT and $PATCH; output appended to $P/$S.log, exit code to $P/$S.rc
  set +e   # a failing dsh must reach the echo below; set -e would abort the group first
  { $RUN "$DSH" --patch "$PATCH" --profile headless "$PROMPT" 2>&1; echo "$?" > "$P/$S.rc"; } | tee -a "$P/$S.log"
  set -e
  RC=$(cat "$P/$S.rc" 2>/dev/null || echo 1)
}
START_SHA=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true); export STAGE_START_SHA="$START_SHA"
committed() { [ -n "$START_SHA" ] && [ "$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null)" != "$START_SHA" ]; }
: > "$P/$S.log"
# Plan (2026-09-15, Chris: "qwen38 as the planner, delegate to ornith"): the judge
# writes the checklist, the implementer works it. In SUFFIX so every round keeps it.
if [ "$S" = implement ] && [ -n "${JUDGE_URL:-}" ] && python3 "$SCRIPTS/plan.py" >/dev/null 2>"$P/plan.err" && [ -s "$P/plan.md" ]; then
  SUFFIX="$SUFFIX

PLAN (written by the judge that will review this change; do every step, in order, and tick each one off in $P/03-implementation.md):
$(cat "$P/plan.md")"
  PROMPT="$BASE$SUFFIX"
  echo "stage implement: plan with $(grep -c '^[0-9]' "$P/plan.md") step(s)"
fi
run_dsh
# A model stage that answered as if it had no task: five halts on 2026-09-13 were
# "No request has been provided yet" to a 12 KB prompt, 5 s each, no artifact.
# One more pass with the nudge; the implement stage has its own second pass.
case "$S" in investigate) ART=01-findings.json ;; adjudicate) ART=02-verdict.json ;; test) ART=04-test-report.json ;; *) ART= ;; esac
if [ -n "$ART" ] && [ "$RC" = 0 ] && [ ! -f "$P/$ART" ] && [ "$(wc -c < "$P/$S.log")" -lt 2500 ] && [ ! -f "$P/$S.blank-retried" ]; then
  touch "$P/$S.blank-retried"
  echo "stage $S: first pass answered without doing the task ($(wc -c < "$P/$S.log") bytes, no $ART); second pass"
  PROMPT="$BASE$SUFFIX

SECOND PASS. Your first pass replied as if no task had been given. This prompt IS the task: do not ask for details, start by reading the files named above and finish by writing $P/$ART."
  run_dsh
fi
# Stages that survive their own mistakes (new_localai#66; 4 of 22 halts this
# week were "wrote no 03-implementation.md", and the tester's rejection went
# to the reviewer instead of back to the implementer). One more pass each.
if [ "$S" = implement ] && [ "$RC" = 0 ] && [ ! -f "$P/03-implementation.md" ] && ! committed && [ ! -f "$P/implement.retried" ]; then
  touch "$P/implement.retried"
  echo "stage implement: first pass wrote no 03-implementation.md; second pass with a narrowed brief"
  TAIL=$(tail -25 "$P/$S.log" | cut -c1-300)
  PROMPT="$BASE$SUFFIX

SECOND PASS. Your first pass ended without writing $P/03-implementation.md. Its last lines:
$TAIL
Do the smallest slice that moves the task: one file, one change, its test, one commit. Write $P/03-implementation.md FIRST (what you will do), then do it and update the file. Do not investigate again."
  run_dsh
fi
# Harness change 2 (2026-09-09): iterate until the model's own proof passes.
# The implementer writes $P/verify.sh (the one command that proves its change);
# a failing verify.sh buys another round with its output, IMPLEMENT_ROUNDS at
# most. Deterministic: no model cooperation needed beyond writing the file.
IMPLEMENT_ROUNDS=${IMPLEMENT_ROUNDS:-3}
VTMO=""; ETMO=""; command -v timeout >/dev/null 2>&1 && VTMO="timeout -k 10 300" && ETMO="timeout -k 10 1500"
ROUND=1
# Escalation (2026-09-15, Chris: "Escalate to qwen38"): ornith15 implements first. Two
# pre-review rejections, or a session that collapsed into token salad (3ca8: "Ber db Ber"
# to the token ceiling), hand the open points to the judge model in patch mode
# (escalate.py). Its result gets one more verify and pre-review, then ships as it stands.
ESCALATED=""; REJECTS=0
escalate() {
  ESCALATED=1; IMPLEMENT_ROUNDS=$((ROUND + 1))
  echo "stage implement: escalating to ${JUDGE_MODEL:-the judge} ($1)"
  if ${ETMO:-} python3 -u "$SCRIPTS/escalate.py" "$1" >> "$P/escalate.log" 2>&1; then
    RC=0; echo "stage implement: escalation committed ($(tail -1 "$P/escalate.log" | cut -c1-160))"
  else
    IMPLEMENT_ROUNDS=$ROUND; echo "stage implement: escalation applied nothing ($(tail -1 "$P/escalate.log" | cut -c1-160))"
  fi
}
salad() { [ "$S" = implement ] && [ "$RC" != 0 ] && [ -z "$ESCALATED" ] && [ -n "${JUDGE_URL:-}" ] \
  && tail -c 4000 "$P/$S.log" | python3 "$SCRIPTS/escalate.py" --degenerate; }
salad && escalate degenerate
# A verify.sh committed at the repo root is still the run's proof: kagent#60's round wrote
# it there, the loop saw no $P/verify.sh, and verify and pre-review were skipped (2026-09-15).
if [ "$S" = implement ] && [ ! -f "$P/verify.sh" ] && [ -f "$REPO_DIR/verify.sh" ] && committed \
   && git -C "$REPO_DIR" diff --name-only "$START_SHA..HEAD" 2>/dev/null | grep -qx verify.sh; then
  cp "$REPO_DIR/verify.sh" "$P/verify.sh" && echo "stage implement: verify.sh was written at the repo root; running it as the proof"
fi
# A committed change with no proof no longer walks past the gate: no verify.sh means no
# verify and no pre-review, so it buys another round instead of shipping unchecked.
while [ "$S" = implement ] && [ "$RC" = 0 ] && committed && [ "$ROUND" -lt "$IMPLEMENT_ROUNDS" ]; do
  # Honour the shebang: a bash verify.sh (set -o pipefail) run by dash dies before its
  # first command, and that burned a whole implement round twice (bd9bc38, 2026-09-15).
  VSH=sh; [ -f "$P/verify.sh" ] && head -1 "$P/verify.sh" | grep -q bash && command -v bash >/dev/null 2>&1 && VSH=bash
  if [ ! -f "$P/verify.sh" ]; then
    echo 1 > "$P/verify.rc"
    WHY="You wrote no $P/verify.sh, so nothing proves the change and the judge that reviews it never saw it run. Write $P/verify.sh (the pipeline's proof script, NOT a file in the repo): the commands that prove every step of the plan, printing their output."
  elif (cd "$REPO_DIR" && ${VTMO:-} $VSH "$P/verify.sh") > "$P/verify.out" 2>&1; then
    echo 0 > "$P/verify.rc"; echo "stage implement: verify.sh passed (round $ROUND)"
    # Pre-review (2026-09-15): the PR reviewer's own judge scores this diff before it
    # is a PR; below its bar the open points come back here, not in a review round.
    if python3 "$SCRIPTS/precheck.py" > "$P/precheck.out" 2>&1; then
      echo "stage implement: pre-review passed ($(head -1 "$P/precheck.out" | cut -c1-80))"; break
    fi
    REJECTS=$((REJECTS + 1))
    WHY="The judge that will review this PR scored your diff below its bar. Its verdict:
$(head -40 "$P/precheck.out" | cut -c1-400)
Address every open point it names, one by one."
  else
    echo 1 > "$P/verify.rc"
    WHY="Your verify.sh failed after your last commit. Its output (tail):
$(tail -30 "$P/verify.out" | cut -c1-300)
Fix the cause, run verify.sh yourself until it passes. If the check itself is wrong, fix verify.sh and say so."
  fi
  [ -n "$ESCALATED" ] && { echo "stage implement: the escalated change did not pass either; it ships as it stands"; break; }
  ROUND=$((ROUND + 1)); echo "$ROUND" > "$P/implement.rounds"
  echo "stage implement: another round, $ROUND of $IMPLEMENT_ROUNDS"
  PROMPT="$BASE$SUFFIX

ROUND $ROUND. $WHY
Commit, and update $P/03-implementation.md."
  if [ "$REJECTS" -ge 2 ]; then escalate rejected; else run_dsh; salad && escalate degenerate; fi
done
# The repo's formatter, not the model, has the last word on style: kagent#55, #58
# and #59 went red on CI's "Format check" alone (2026-09-15). Prettier on the files
# this run changed, as its own commit: the repo's own binary when installed, else
# the version its package.json pins, through npx (#59's install was filtered to one
# package and left no root node_modules/.bin/prettier). No prettier declared: untouched.
if [ "$S" = implement ] && committed; then
  PRETTIER=""
  if [ -x "$REPO_DIR/node_modules/.bin/prettier" ]; then PRETTIER="node_modules/.bin/prettier"
  elif [ -f "$REPO_DIR/package.json" ] && command -v node >/dev/null 2>&1; then
    PV=$(node -e 'const p=require(process.argv[1]);process.stdout.write(((p.devDependencies||{}).prettier||(p.dependencies||{}).prettier||"").replace(/^[^0-9]*/,""))' "$REPO_DIR/package.json" 2>/dev/null || true)
    [ -n "$PV" ] && PRETTIER="npx -y prettier@$PV"
  fi
  CHANGED=$(git -C "$REPO_DIR" diff --name-only --diff-filter=d "$START_SHA..HEAD" 2>/dev/null | grep -E '\.(ts|tsx|js|mjs|md|json|ya?ml)$' || true)
  if [ -n "$PRETTIER" ] && [ -n "$CHANGED" ]; then
    # ./ prefix: a changed file named like a flag (--plugin=x.js) must stay a path, not an option
    (cd "$REPO_DIR" && echo "$CHANGED" | sed 's|^|./|' | xargs $PRETTIER --write --ignore-unknown >/dev/null 2>&1) || true
    git -C "$REPO_DIR" commit -qam "style: prettier on the files this run changed" 2>/dev/null && echo "stage implement: prettier reformatted changed files"
  fi
fi
# The evidence is verify.sh on the head that ships: the loop's last round and the prettier
# commit both land after the last check, and kagent#62 went out with round 3's script beside
# round 2's output (2026-09-15). One more run, its output is what publish shows.
if [ "$S" = implement ] && committed && [ -f "$P/verify.sh" ]; then
  VSH=sh; head -1 "$P/verify.sh" | grep -q bash && command -v bash >/dev/null 2>&1 && VSH=bash
  if (cd "$REPO_DIR" && ${VTMO:-} $VSH "$P/verify.sh") > "$P/verify.out" 2>&1; then echo 0 > "$P/verify.rc"; else echo 1 > "$P/verify.rc"; fi
  echo "stage implement: final verify.sh on the shipped head: rc $(cat "$P/verify.rc")"
fi
# The work is there (a commit) but the report is not: four of six bench runs on
# 2026-09-09 ended "wrote no 03-implementation.md" with green tests and a commit.
# The report is a formality the pipeline can write itself; a LESSON: line is the
# only thing lost, and that is the model's to write next time.
if [ "$S" = implement ] && [ ! -f "$P/03-implementation.md" ] && committed; then
  echo "stage implement: commit present, report missing; synthesizing 03-implementation.md"
  { echo "# Implementation (synthesized by the pipeline: the implementer committed but wrote no report)"; echo
    echo "## Commits"; git -C "$REPO_DIR" log "$START_SHA..HEAD" --format='- %s' 2>/dev/null; echo
    echo "## Diff stat"; git -C "$REPO_DIR" diff --stat "$START_SHA..HEAD" 2>/dev/null; echo
    echo "## Scope adherence"; echo "Not stated by the implementer; the reviewer judges the diff."; } > "$P/03-implementation.md"
  echo 1 > "$P/report.synthesized"
fi
if [ "$S" = test ] && [ "$RC" = 0 ] && [ ! -f "$P/test.retried" ] && [ -f "$P/04-test-report.json" ] \
   && ! python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("verdict") == "SHIP" else 1)' "$P/04-test-report.json" 2>/dev/null; then
  touch "$P/test.retried"
  echo "stage test: tester rejected; one fix pass by the implementer, then the tester again"
  REPORT=$(cut -c1-3000 "$P/04-test-report.json")
  PROMPT="$(cat /config/implement.txt)$SUFFIX

FIX PASS. The adversarial tester rejected your change:
$REPORT
Fix exactly what it names, run the test it names, commit, and append what changed to $P/03-implementation.md. Nothing else."
  JUDGE_PATCH=$PATCH; PATCH=/config/dsh-patch.yml   # the fix is the implementer's (ornith15)
  run_dsh
  PATCH=$JUDGE_PATCH
  if [ "$RC" = 0 ]; then
    PROMPT="$BASE$SUFFIX"
    run_dsh
  fi
fi
# dsh's own session transcript (~/.dsh/sessions/<cwd>/session-*/session.jsonl.zstd)
# is the only record of what it did when it exits 1 without a word; keep it on
# the shared workspace and, when zstd is available, put its tail in the bundle.
if [ -d "$HOME/.dsh/sessions" ]; then
  mkdir -p "$P/dsh-sessions/$S" && cp -r "$HOME/.dsh/sessions/." "$P/dsh-sessions/$S/" 2>/dev/null || true
  LAST=$(find "$P/dsh-sessions/$S" -name 'session.jsonl.zstd' -newer "$P/$S.rc" -o -name 'session.jsonl.zstd' 2>/dev/null | tail -1)
  # agent-coder has no zstd binary, but its Node 22 has zlib.zstdDecompressSync.
  # dsh appends one zstd frame per event and Node decodes only the first frame,
  # so split on the frame magic and decode each. ponytail: a frame whose
  # compressed bytes happen to contain the magic loses one event, nothing more.
  if [ -n "$LAST" ]; then
    # every session this stage ran (an implement round is a new session), decoded in
    # full: the metrics below count its tool calls (is the lsp tool used? 2026-09-15)
    : > "$P/$S.session.jsonl"
    for F in $(find "$P/dsh-sessions/$S" -name 'session.jsonl.zstd' 2>/dev/null); do
      { zstd -dcq "$F" 2>/dev/null || node -e '
const fs=require("fs"),z=require("zlib"),b=fs.readFileSync(process.argv[1]),m=Buffer.from([0x28,0xb5,0x2f,0xfd]);
const idx=[];for(let p=b.indexOf(m);p!==-1;p=b.indexOf(m,p+4))idx.push(p);
const out=[];for(let k=0;k<idx.length;k++){try{out.push(z.zstdDecompressSync(b.subarray(idx[k],idx[k+1]??b.length)))}catch(e){}}
process.stdout.write(Buffer.concat(out))' "$F" 2>/dev/null; } >> "$P/$S.session.jsonl" || true
    done
    tail -30 "$P/$S.session.jsonl" | cut -c1-400 > "$P/$S.session-tail" || true
  fi
fi
if [ "$RC" = "124" ] || [ "$RC" = "137" ]; then
  halt "dsh exceeded the ${STAGE_TIMEOUT}s stage timeout" "$RC"; mark halted; exit 0
fi
if [ "$RC" != "0" ]; then
  halt "dsh session failed" "$RC"; mark halted; exit 0
fi
if ! python3 "$SCRIPTS/validate.py" "$S"; then
  halt "stage artifact failed validation" "validate"; mark halted; exit 0
fi
# validate.py may itself decide to stop the pipeline (e.g. "investigator found
# no candidates"); give that stop the same bundle: exit code, log tail, time.
if [ -f "$P/stop" ]; then
  python3 - "$S" "$P" "$RC" <<'PY'
import json, os, sys, time
stage, p, rc = sys.argv[1:4]
st = json.load(open(f"{p}/stop"))
if not st.get("log_tail"):
    log = f"{p}/{stage}.log"
    st.setdefault("exit_code", rc)
    st.setdefault("at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    st["log"] = log if os.path.exists(log) else None
    st["log_tail"] = "\n".join(open(log, errors="replace").read().splitlines()[-40:])[-4000:] if os.path.exists(log) else ""
    json.dump(st, open(f"{p}/stop", "w"))
PY
  mark halted; exit 0
fi
# What the bench (scripts/bench.py) measures per stage: prompt size, dsh sessions,
# tool-schema errors (ornith15 guessing Anthropic-style keys), wall time.
python3 - "$S" "$P" "${#PROMPT}" <<'PY' 2>/dev/null || true
import json, os, re, sys
stage, p, nbytes = sys.argv[1], sys.argv[2], int(sys.argv[3])
log = open(f"{p}/{stage}.log", errors="replace").read() if os.path.exists(f"{p}/{stage}.log") else ""
calls = 1 + (1 if os.path.exists(f"{p}/{stage}.retried") else 0) + (1 if stage == "test" and os.path.exists(f"{p}/test.retried") else 0)
rounds = int(open(f"{p}/implement.rounds").read().strip()) if os.path.exists(f"{p}/implement.rounds") else 1
calls += rounds - 1
verified = os.path.exists(f"{p}/verify.sh")
synth = os.path.exists(f"{p}/report.synthesized")
# tool calls by name, from dsh's session events ({"type": "tool/call", "data": {...}}):
# whether the lsp tool is used at all is the first question of the LSP experiment
tools = {}
if os.path.exists(f"{p}/{stage}.session.jsonl"):
    for line in open(f"{p}/{stage}.session.jsonl", errors="replace"):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "tool/call":
            d = ev.get("data") or {}
            n = str(d.get("name") or d.get("tool") or d.get("toolName") or "?")
            tools[n] = tools.get(n, 0) + 1
json.dump({"prompt_bytes": nbytes, "schema_errors": len(re.findall(r"missing required property|Unrecognized key|invalid_type", log)), "dsh_calls": calls,
           "rounds": rounds, "wrote_verify": verified, "report_synthesized": synth, "tool_calls": tools},
          open(f"{p}/{stage}.metrics.json", "w"))
PY
mark ok
