#!/usr/bin/env python3
"""Shared GitHub helpers for skill install scripts."""

from __future__ import annotations

import os
from pathlib import Path
import urllib.request


def skills_directory() -> str:
    """E_coder's registry, with a portable fallback for direct script calls."""
    configured = os.environ.get("ECODER_SKILLS_DIR")
    return str(Path(configured).resolve() if configured else Path(__file__).resolve().parents[2])


def github_request(url: str, user_agent: str) -> bytes:
    headers = {"User-Agent": user_agent}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def github_api_contents_url(repo: str, path: str, ref: str) -> str:
    return f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
