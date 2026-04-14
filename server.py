#!/usr/bin/env python3
import json, re
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("validator-ai-mcp")
@mcp.tool(name="validate_email")
async def validate_email(email: str) -> str:
    valid = re.match(r'^[^@]+@[^@]+\.[^@]+$', email) is not None
    return json.dumps({"email": email, "valid": valid})
@mcp.tool(name="validate_url")
async def validate_url(url: str) -> str:
    valid = url.startswith("http://") or url.startswith("https://")
    return json.dumps({"url": url, "valid": valid})
@mcp.tool(name="validate_json")
async def validate_json(text: str) -> str:
    try:
        json.loads(text)
        return json.dumps({"valid": True})
    except Exception as e:
        return json.dumps({"valid": False, "error": str(e)})
if __name__ == "__main__":
    mcp.run()
