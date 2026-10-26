"""The judge sees where a diff's new names are consumed (reviewer escalation #486)."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import review  # noqa: E402

DIFF = """--- a/scripts/stage.sh
+++ b/scripts/stage.sh
@@ -1 +1,2 @@
 export FORUM_AUTHOR="$S"
+export FORUM_REF="${RUN_ID:-}"
"""


def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "stage.sh").write_text('export FORUM_AUTHOR="$S"\nexport FORUM_REF="${RUN_ID:-}"\n')
    (tmp_path / "plugin.js").write_text('const ref = process.env.FORUM_REF || undefined;\n')
    (tmp_path / "launcher.py").write_text('env = [{"name": "RUN_ID", "value": name}]\n')
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], check=True)
    return str(tmp_path)


def test_references_find_the_consumers_and_skip_touched_files(tmp_path):
    out = review.references(repo(tmp_path), DIFF)
    assert "plugin.js:1:const ref = process.env.FORUM_REF" in out
    assert "launcher.py:1:" in out          # RUN_ID is read too
    assert "stage.sh" not in out            # the diff's own file is excluded


def test_references_is_empty_without_a_checkout_or_names():
    assert review.references(None, DIFF) == ""
    assert review.references("/nonexistent", "+++ b/x\n+x = 1\n") == ""
