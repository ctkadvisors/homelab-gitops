"""The bench's held-out split and the non-regression verdict (idea lineage, step 8)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import bench  # noqa: E402
from fleet import ledger  # noqa: E402


def summary(visible_ok: int, held_ok: bool, seconds: float) -> dict:
    rows = [{"task": t, "success": i < visible_ok, "held_out": False} for i, t in enumerate(sorted(bench.TASKS.keys() - bench.HELD_OUT))]
    rows += [{"task": t, "success": held_ok, "held_out": True} for t in bench.HELD_OUT]
    return {"success": sum(r["success"] for r in rows), "n": len(rows), "seconds": seconds, "prompt_bytes": 1, "schema_errors": 0, "dsh_calls": 3, "rows": rows}


def test_compare_verdict_is_decided_by_held_out_passes_only(monkeypatch, capsys):
    assert bench.HELD_OUT < set(bench.TASKS) and len(bench.HELD_OUT) == 1
    kv = {"bench:a": summary(2, False, 400.0), "bench:b": summary(3, True, 380.0),      # held-out went 0 -> 1
          "bench:c": summary(3, False, 300.0), "bench:d": summary(1, False, 900.0)}     # visible only: ties on the ruler
    monkeypatch.setattr(ledger, "kv_get", lambda k: kv.get(k))
    assert bench.compare(["a", "b"]) == "improved"
    assert bench.compare(["b", "a"]) == "regressed"
    assert bench.compare(["a", "c"]) == "no_change"       # more visible passes and faster, still a tie on the held-out
    assert bench.compare(["a", "d"]) == "no_change"
    assert bench.compare(["a", "missing"]) is None and bench.compare(["a"]) is None
    out = capsys.readouterr().out
    assert "verdict a -> b: improved (held-out 0 -> 1, 400.0s -> 380.0s)" in out and "(no record)" in out
    assert bench.verdict({"rows": [{"success": True}]}, {"rows": [{"success": True}]}) == "no_change"   # rows without the flag never count


def test_when_the_held_out_fixture_already_passes_seconds_decide():
    row = lambda secs, ok=True: {"held_out": True, "success": ok, "seconds": secs}
    before = {"rows": [row(100.0)]}
    assert bench.verdict(before, {"rows": [row(85.0)]}) == "improved"      # 15% faster
    assert bench.verdict(before, {"rows": [row(95.0)]}) == "no_change"     # within the band
    assert bench.verdict(before, {"rows": [row(120.0)]}) == "regressed"    # 20% slower
    assert bench.verdict(before, {"rows": [row(50.0, ok=False)]}) == "regressed"   # a pass lost beats any speed
    assert bench.verdict({"rows": [row(100.0, ok=False)]}, {"rows": [row(500.0)]}) == "improved"   # a pass gained beats any speed
