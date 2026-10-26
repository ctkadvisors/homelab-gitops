"""What a stage can see (2026-09-06 evening): alerts as evidence, and the prompt
that tells a stage about kubectl, search and the forum."""

import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402


def test_collect_alerts_groups_by_name_and_namespace(monkeypatch):
    payload = [{"labels": {"alertname": "KubernetesJobFailed", "namespace": "kagent-system", "job_name": "mission-1", "severity": "warning"}, "annotations": {"summary": "job failed"}, "startsAt": "2026-09-06T09:56:00Z"},
               {"labels": {"alertname": "KubernetesJobFailed", "namespace": "kagent-system", "job_name": "mission-2", "severity": "warning"}, "annotations": {}, "startsAt": "2026-09-06T12:49:00Z"},
               {"labels": {"alertname": "KubernetesPodNotHealthy", "namespace": "backup", "pod": "nas-x"}, "annotations": {}, "startsAt": "2026-09-06T10:01:00Z"}]
    monkeypatch.setattr(collect.urllib.request, "urlopen", lambda url, timeout=15: io.BytesIO(json.dumps(payload).encode()))
    items, note = collect.collect_alerts()
    assert note is None and items[0]["alert"] == "KubernetesJobFailed" and items[0]["count"] == 2
    assert items[0]["objects"] == ["mission-1", "mission-2"] and items[0]["created_at"] == "2026-09-06T12:49:00Z"
    assert items[1]["namespace"] == "backup"


def test_collect_alerts_degrades_without_alertmanager(monkeypatch):
    def boom(url, timeout=15):
        raise OSError("down")
    monkeypatch.setattr(collect.urllib.request, "urlopen", boom)
    items, note = collect.collect_alerts()
    assert items == [] and "unreachable" in note


def test_stage_prompt_indexes_skills_that_carry_the_tools():
    """2026-09-09: the tool paragraphs moved out of every prompt into skills the
    model loads on demand (dsh skill-filesystem); the prompt keeps a one-line index."""
    s = (ROOT / "scripts" / "stage.sh").read_text()
    assert "SKILLS (load one with the skill tool" in s and "AGENTS.md" in s
    skills = {p.parent.name: p.read_text() for p in (ROOT / "skills").glob("*/SKILL.md")}
    assert {"cluster", "forum", "checks", "search", "node-runner", "ledger"} <= set(skills)
    assert "/fleet/bin/kubectl" in skills["cluster"] and "searxng.search.svc" in skills["search"]
    assert "fleet-console.kagent-system.svc:8081" in skills["forum"] and "mission-launcher.kagent-system.svc:8080/checks" in skills["checks"]
    for name, body in skills.items():
        assert body.startswith("---\nname: " + name + "\ndescription: "), name   # the catalog line the model sees
