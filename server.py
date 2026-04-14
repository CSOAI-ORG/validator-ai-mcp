#!/usr/bin/env python3

import sys, os
sys.path.insert(0, os.path.expanduser('~/clawd/meok-labs-engine/shared'))
from auth_middleware import check_access

import json, re
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("validator-ai-mcp")
@mcp.tool(name="validate_email")
async def validate_email(email: str, api_key: str = "") -> str:
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    valid = re.match(r'^[^@]+@[^@]+\.[^@]+$', email) is not None
    return {"email": email, "valid": valid}
@mcp.tool(name="validate_url")
async def validate_url(url: str, api_key: str = "") -> str:
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    valid = url.startswith("http://") or url.startswith("https://")
    return {"url": url, "valid": valid}
@mcp.tool(name="validate_json")
async def validate_json(text: str, api_key: str = "") -> str:
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    try:
        json.loads(text)
        return {"valid": True}
    except Exception as e:
        return {"valid": False, "error": str(e)}
if __name__ == "__main__":
    mcp.run()
