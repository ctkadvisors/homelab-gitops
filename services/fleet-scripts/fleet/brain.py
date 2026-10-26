"""One episode into the graphiti brain over its MCP endpoint (streamable
HTTP: initialize -> notifications/initialized -> tools/call add_memory).
BRAIN_URL from env, bearer token from /secrets/brain/token."""

from __future__ import annotations

import json
import os
import urllib.request

from fleet import net

URL = os.environ.get("BRAIN_URL", "http://graphiti-mcp.ai-services.svc.cluster.local:8000/mcp")
TOKEN_FILE = os.environ.get("BRAIN_TOKEN_FILE", "/secrets/brain/token")


def _call(method: str, params=None, session: str | None = None, want_id: int | None = None, token: str = ""):
    body: dict = {"jsonrpc": "2.0", "method": method}
    if want_id is not None:
        body["id"] = want_id
    if params is not None:
        body["params"] = params
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "Authorization": "Bearer " + token}
    if session:
        headers["mcp-session-id"] = session
    # graphiti queues the episode server-side, so a busy spark never fails this call;
    # a restarting MCP does, and that is worth three tries rather than a dropped episode
    return net.urlopen_retry(urllib.request.Request(URL, json.dumps(body).encode(), headers), timeout=30, tries=3)


def add_episode(name: str, body: str, source_description: str, source: str = "text",
                reference_time: str | None = None, client: str = "fleet") -> None:
    token = os.environ.get("BRAIN_TOKEN") or open(TOKEN_FILE).read().strip()
    r = _call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                             "clientInfo": {"name": client, "version": "1"}}, want_id=1, token=token)
    session = r.headers.get("mcp-session-id")
    r.read()
    _call("notifications/initialized", session=session, token=token).read()
    args = {"name": name, "episode_body": body, "source": source, "source_description": source_description}
    if reference_time:
        args["reference_time"] = reference_time
    _call("tools/call", {"name": "add_memory", "arguments": args}, session=session, want_id=2, token=token).read()
