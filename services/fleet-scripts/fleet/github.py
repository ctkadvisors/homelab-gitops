"""GitHub access for fleet jobs, without a long-lived token when possible.

Token resolution, in order:
  1. A GitHub App installation: /secrets/github-app/{app_id,installation_id,
     private_key.pem}. A 9-minute RS256 JWT (signed with the openssl CLI, no
     python crypto deps) mints a 1-hour installation token on demand. The
     private key never expires but is per-install, scoped by the App's
     permissions, and revocable from the App settings page.
  2. Fallback: a PAT at /secrets/git/token (GITHUB_TOKEN_FILE overrides).

This is the "OIDC-style" answer for a homelab calling GitHub: GitHub's
OIDC is for Actions authenticating *outward*; for inbound API calls the
short-lived credential is the App installation token.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.request

API = "https://api.github.com"
APP_DIR = os.environ.get("GITHUB_APP_DIR", "/secrets/github-app")
PAT_FILE = os.environ.get("GITHUB_TOKEN_FILE", "/secrets/git/token")
_cache: dict[str, object] = {}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def app_jwt(app_id: str, key_path: str, now: int | None = None) -> str:
    now = int(time.time()) if now is None else now
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({"iat": now - 60, "exp": now + 540, "iss": app_id}).encode())
    signature = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", key_path],
        input=f"{header}.{payload}".encode(), capture_output=True, check=True,
    ).stdout
    return f"{header}.{payload}.{_b64(signature)}"


def app_token(app_dir: str = APP_DIR, opener=urllib.request.urlopen) -> str:
    now = int(time.time())
    if isinstance(_cache.get("exp"), int) and _cache["exp"] > now + 60:  # type: ignore[operator]
        return str(_cache["token"])
    app_id = open(f"{app_dir}/app_id").read().strip()
    installation = open(f"{app_dir}/installation_id").read().strip()
    jwt = app_jwt(app_id, f"{app_dir}/private_key.pem", now)
    req = urllib.request.Request(
        f"{API}/app/installations/{installation}/access_tokens", data=b"{}", method="POST",
        headers={"Authorization": f"Bearer {jwt}", "Accept": "application/vnd.github+json"},
    )
    with opener(req, timeout=30) as r:
        body = json.load(r)
    _cache.update(token=body["token"], exp=now + 3300)
    return str(body["token"])


def set_app_webhook(url: str, secret: str, app_dir: str = APP_DIR, opener=urllib.request.urlopen) -> dict:
    """Point the App's webhook at `url` with `secret` (PATCH /app/hook/config,
    App JWT auth). Which events are delivered is still ticked on the App's
    permissions page; GitHub has no API for that."""
    app_id = open(f"{app_dir}/app_id").read().strip()
    jwt = app_jwt(app_id, f"{app_dir}/private_key.pem")
    req = urllib.request.Request(
        f"{API}/app/hook/config", method="PATCH",
        data=json.dumps({"url": url, "content_type": "json", "secret": secret, "insecure_ssl": "0"}).encode(),
        headers={"Authorization": f"Bearer {jwt}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"},
    )
    with opener(req, timeout=30) as r:
        return json.load(r)


def token() -> str:
    if os.path.exists(f"{APP_DIR}/private_key.pem"):
        return app_token()
    return open(PAT_FILE).read().strip()


def api(path: str, data=None, method: str | None = None,
        accept: str = "application/vnd.github+json", raw: bool = False):
    """One GitHub API call. `path` is absolute (/repos/...) or a full URL."""
    url = path if path.startswith("http") else API + path
    req = urllib.request.Request(
        url, data=json.dumps(data).encode() if data is not None else None, method=method,
        headers={"Authorization": "Bearer " + token(), "Accept": accept,
                 **({"Content-Type": "application/json"} if data is not None else {})},
    )
    # Retried like the in-cluster calls (fleet/net.py): a Job pod's first
    # seconds can also drop egress until the netpol ipset carries its IP, and
    # elitemini2 drops the odd connection (triage 2026-09-07 21:45Z died on
    # /installation/repositories with "urlopen error timed out"; six hooks
    # reviews the same afternoon). 4xx/5xx still raise at once.
    from fleet.net import urlopen_retry
    with urlopen_retry(req, timeout=30, tries=3) as r:
        text = r.read().decode(errors="replace")
    return text if raw else (json.loads(text) if text.strip() else {})


def tree(repo: str) -> set[str]:
    """Every path (files and folders) on the default branch; empty when GitHub truncated it."""
    t = api(f"/repos/{repo}/git/trees/HEAD?recursive=1")
    return set() if t.get("truncated") else {e["path"] for e in t.get("tree", [])}


def push_url(repo: str) -> str:
    """HTTPS remote with the current token embedded (x-access-token works for both kinds)."""
    return f"https://x-access-token:{token()}@github.com/{repo}.git"


def installation_repos() -> list[str]:
    """Every repo the App is installed on (owner/name), which is the fleet's
    allowlist by definition: no hardcoded repo lists anywhere else."""
    names: list[str] = []
    page = 1
    while True:
        r = api(f"/installation/repositories?per_page=100&page={page}")
        names += [x["full_name"] for x in r.get("repositories", [])]
        if len(names) >= r.get("total_count", 0) or not r.get("repositories"):
            return names
        page += 1


def repos_from_env(var: str = "REPOS") -> list[str]:
    """REPOS env overrides; otherwise the App installation decides."""
    fixed = [r for r in os.environ.get(var, "").split(",") if r]
    return fixed or installation_repos()


_topics: dict[str, tuple[float, list[str]]] = {}


def topics(repo: str) -> list[str]:
    """The repo's GitHub topics, cached ten minutes. Policy that is per-repo lives
    here, set by a human on the repo, never as a list of names in code."""
    import time
    hit = _topics.get(repo)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    names = list(api(f"/repos/{repo}/topics").get("names", []))
    _topics[repo] = (time.time(), names)
    return names


def kid_gloves(repo: str) -> bool:
    """Chris, 2026-09-06: "kid gloves around harknote and seekarc. those are public
    facing and wired up to drive revenue." A repo with the topic `fleet-kid-gloves`
    gets reviewed and never merged by the fleet, and no speculative improve run
    targets it. Unreadable topics count as kid gloves: fail closed on the merge path."""
    try:
        return "fleet-kid-gloves" in topics(repo)
    except Exception:
        # A transient GitHub error escalated new_localai#26 as "kid gloves" on
        # 2026-09-07 01:00Z. The last known answer, if any, is better than a
        # guess; with no history at all, fail closed.
        hit = _topics.get(repo)
        return "fleet-kid-gloves" in hit[1] if hit else True


def job_log(repo: str, job_id: str, gh=None) -> str:
    """A workflow job's log text. GitHub answers 302 to a signed blob URL that
    must be fetched WITHOUT the Authorization header, so the redirect is
    followed by hand."""
    import urllib.error
    url = f"{API}/repos/{repo}/actions/jobs/{job_id}/logs"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token(), "Accept": "application/vnd.github+json"})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=30) as r:
            return r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307) and e.headers.get("Location"):
            with urllib.request.urlopen(e.headers["Location"], timeout=60) as r:
                return r.read().decode(errors="replace")
        raise
