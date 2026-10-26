"""Telegram DM to the operator. Bot token from /secrets/telegram/token,
chat id from TELEGRAM_CHAT_ID (set on the manifest, never in code)."""

from __future__ import annotations

import json
import os
import urllib.request

TOKEN_FILE = os.environ.get("TELEGRAM_TOKEN_FILE", "/secrets/telegram/token")
MAX = 3800


# Chris, 2026-09-15: "i got dings. ignoring telegram." Telegram is for what needs a
# human: a question the concierge could not answer (❓), a PR the fleet may not merge
# or a failure it cannot fix (⚠️), the fleet pausing itself (⏸), the daily digest (📰).
# PR opened, merge announced/merged, ideas posted and the dream stay on the forum and
# the console. TELEGRAM_INFO=1 sends everything again.
NEEDS_YOU = ("❓", "⚠", "⏸", "\U0001F4F0")


def send(text: str, chat_id: str | None = None) -> None:
    if not text.startswith(NEEDS_YOU) and not os.environ.get("TELEGRAM_INFO"):
        print(f"telegram: not sent, nothing for a human to do: {text[:80]!r}")
        return
    chat = chat_id or os.environ["TELEGRAM_CHAT_ID"]
    bot = open(TOKEN_FILE).read().strip()
    for i in range(0, max(len(text), 1), MAX):
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{bot}/sendMessage",
            data=json.dumps({"chat_id": chat, "text": text[i:i + MAX]}).encode(),
            headers={"Content-Type": "application/json"}), timeout=20).read()

# Chris, 2026-09-06: "link me in telegram messages; ensure support for deep
# linking." Every message about a forum post carries the post's own URL on the
# console (the page scrolls to and highlights #post-<id>).
CONSOLE_URL = os.environ.get("CONSOLE_URL", "https://fleet.example.com").rstrip("/")


def post_link(post_id) -> str:
    return f"{CONSOLE_URL}/#post-{post_id}"


def ref_label(ref: str | None) -> str:
    """'brutalist_todo#22' for a GitHub issue or PR URL, the run id for a run,
    '' for nothing: the short name a human recognises."""
    import re
    if not ref:
        return ""
    m = re.search(r"github\.com/[\w.-]+/([\w.-]+)/(?:issues|pull)/(\d+)", ref)
    return f"{m.group(1)}#{m.group(2)}" if m else ref
