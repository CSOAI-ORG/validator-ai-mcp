#!/usr/bin/env python3
"""Validate data formats (email, URL, phone, JSON). — MEOK AI Labs."""
import json, os, re, hashlib, uuid as _uuid, random
from datetime import datetime, timezone
from collections import defaultdict
from mcp.server.fastmcp import FastMCP

FREE_DAILY_LIMIT = 30
_usage = defaultdict(list)
def _rl(c="anon"):
    now = datetime.now(timezone.utc)
    _usage[c] = [t for t in _usage[c] if (now-t).total_seconds() < 86400]
    if len(_usage[c]) >= FREE_DAILY_LIMIT: return json.dumps({"error": "Limit/day"})
    _usage[c].append(now); return None

mcp = FastMCP("validator", instructions="MEOK AI Labs — Validate data formats (email, URL, phone, JSON).")


@mcp.tool()
def validate_email(email: str) -> str:
    """Validate email format."""
    if err := _rl(): return err
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    valid = bool(re.match(pattern, email))
    return json.dumps({"email": email, "valid": valid}, indent=2)

@mcp.tool()
def validate_url(url: str) -> str:
    """Validate URL format."""
    if err := _rl(): return err
    pattern = r'^https?://[\w.-]+(?:\.[\w.-]+)+[\w.,@?^=%&:/~+#-]*$'
    valid = bool(re.match(pattern, url))
    return json.dumps({"url": url, "valid": valid}, indent=2)

if __name__ == "__main__":
    mcp.run()
