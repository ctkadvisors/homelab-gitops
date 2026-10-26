"""After each model stage: is its artifact there and does it say go on?
A failed check writes a stop marker with the reason instead of crashing,
so a halted pipeline still leaves a trace of WHY."""

import json
import os
import subprocess
import sys

stage = sys.argv[1]
P = os.environ.get("PIPELINE_DIR", "/workspace/p")
REPO_DIR = os.environ.get("REPO_DIR", "/workspace/repo")


def stop(reason):
    json.dump({"stage": stage, "reason": reason}, open(f"{P}/stop", "w"))
    print(f"validate {stage}: STOP — {reason}")
    sys.exit(0)


# top-level key that marks each artifact, for salvage()
KEYS = {"01-findings.json": "candidates", "02-verdict.json": "evaluations", "04-test-report.json": "verdict"}


def salvage(name):
    """The model printed the artifact instead of writing it: kagent#22 had a
    complete verdict in the log, 'Verdict written to /workspace/p/02-verdict.json',
    and no file. The log is the durable copy, so take the last JSON object in it
    that carries the artifact's key."""
    log, key = f"{P}/{stage}.log", KEYS.get(name)
    if not key or not os.path.exists(log):
        return None
    text, dec, found, i = open(log, errors="replace").read(), json.JSONDecoder(), None, 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict) and key in obj:
            found = obj
        i = max(end, i + 1)
    return found


def load(name):
    try:
        return json.load(open(f"{P}/{name}"))
    except Exception as e:
        d = salvage(name)
        if d is None:
            stop(f"artifact {name} missing or not valid JSON: {e}")
        json.dump(d, open(f"{P}/{name}", "w"))
        print(f"validate {stage}: {name} was printed, not written; recovered it from {stage}.log")
        return d


if stage == "investigate":
    if not load("01-findings.json").get("candidates"):
        stop("investigator found no candidates")
elif stage == "adjudicate":
    d = load("02-verdict.json")
    if not d.get("evaluations"):
        stop("judge produced no evaluations")
    if not d.get("selected"):
        stop("no candidate passed adjudication: " + str(d.get("selection_reasoning", ""))[:400])
elif stage == "implement":
    if not os.path.exists(f"{P}/03-implementation.md"):
        stop("implementer wrote no 03-implementation.md")
    start = os.environ.get("STAGE_START_SHA")
    if start:  # stage.sh recorded HEAD before the model ran; a push to origin must not hide the work
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_DIR, capture_output=True, text=True).stdout.strip()
        if head == start:
            stop("implementer made no commit")
    else:
        r = subprocess.run(["git", "log", "origin/main..HEAD", "--oneline"], cwd=REPO_DIR, capture_output=True, text=True)
        if not r.stdout.strip():
            stop("implementer made no commit")
elif stage == "test":
    d = load("04-test-report.json")
    if d.get("verdict") != "SHIP":
        stop("tester rejected: " + str(d.get("reasoning", ""))[:400])
print(f"validate {stage}: ok")
