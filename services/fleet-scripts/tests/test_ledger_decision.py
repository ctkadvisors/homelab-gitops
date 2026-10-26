"""A decision for a run with no ledger row is kept (run_id NULL, orphan named), not a crash."""
import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from fleet import ledger  # noqa: E402


class Cur:
    def __init__(self, log): self.log = log
    def execute(self, sql, params):
        self.log.append(params)
        if params[0] == "mission-x":  # the FK the real table raises: decision.run_id -> run.id
            raise Exception("{'C': '23503', 'M': 'insert or update on table \"decision\" violates foreign key constraint'}")
    def fetchone(self): return (7,)


class Conn:
    def __init__(self, log): self.log = log
    def cursor(self): return Cur(self.log)


def test_decision_survives_missing_run(monkeypatch):
    log = []
    monkeypatch.setattr(ledger, "connect", lambda: contextlib.nullcontext(Conn(log)))
    assert ledger.record_decision("launch-mission", 1, "policy", "review round", run_id="mission-x") == 7
    assert log[-1][0] is None and "mission-x has no ledger row" in log[-1][5]
    assert ledger.record_decision("launch-mission", 1, "policy", "ok", run_id="mission-y") == 7 and log[-1][0] == "mission-y"
