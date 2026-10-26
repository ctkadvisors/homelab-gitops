"""validate.py salvages an artifact the model printed instead of writing
(kagent#22), and still halts legibly when there is nothing to salvage."""
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def run(tmp, stage):
    env = {**os.environ, "PIPELINE_DIR": str(tmp)}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), stage], env=env, capture_output=True, text=True)


def test_verdict_printed_in_the_log_is_recovered(tmp_path):
    verdict = {"evaluations": [{"id": "C1", "verdict": "PASS"}], "selected": "C1", "selection_reasoning": "fine"}
    (tmp_path / "adjudicate.log").write_text(
        "Let me check {not json} first.\n{\"evaluations\": []}\nI have enough to write the verdict.\n"
        + json.dumps(verdict, indent=2) + "\n\nVerdict written to `/workspace/p/02-verdict.json`.\n## Summary\n")
    r = run(tmp_path, "adjudicate")
    assert "recovered" in r.stdout and "validate adjudicate: ok" in r.stdout, r.stdout
    assert json.load(open(tmp_path / "02-verdict.json")) == verdict
    assert not (tmp_path / "stop").exists()


def test_nothing_to_salvage_still_stops_with_the_reason(tmp_path):
    (tmp_path / "investigate.log").write_text("I looked around and found nothing worth filing.\n")
    r = run(tmp_path, "investigate")
    stop = json.load(open(tmp_path / "stop"))
    assert stop["stage"] == "investigate" and "01-findings.json missing" in stop["reason"], r.stdout
