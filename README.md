# Validator Ai

> By [MEOK AI Labs](https://meok.ai) — Validate JSON against schemas, check email deliverability, verify URLs, assess data quality, and validate API responses. Uses RFC-compliant checks and heuristic analysis.

Validator AI MCP Server - JSON schema validation, email/URL checking, data quality, and API response validation.

## Installation

```bash
pip install validator-ai-mcp
```

## Usage

```bash
# Run standalone
python server.py

# Or via MCP
mcp install validator-ai-mcp
```

## Tools

### `validate_json`
Validate JSON string, optionally against a JSON Schema. Schema as JSON string.

**Parameters:**
- `data` (str)
- `schema` (str)

### `validate_email`
Validate email format, domain structure, and check for disposable addresses.

**Parameters:**
- `email` (str)

### `validate_url`
Validate URL format, structure, and security characteristics.

**Parameters:**
- `url` (str)

### `validate_data_quality`
Check a JSON dataset for quality issues: nulls, duplicates, type consistency, outliers. Pass data as JSON array of objects.

**Parameters:**
- `data` (str)

### `validate_api_response`
Validate an API response body and structure. Required fields as comma-separated string.

**Parameters:**
- `response_body` (str)
- `expected_status` (int)
- `expected_content_type` (str)
- `required_fields` (str)


## Authentication

Free tier: 15 calls/day. Upgrade at [meok.ai/pricing](https://meok.ai/pricing) for unlimited access.

## Links

- **Website**: [meok.ai](https://meok.ai)
- **GitHub**: [CSOAI-ORG/validator-ai-mcp](https://github.com/CSOAI-ORG/validator-ai-mcp)
- **PyPI**: [pypi.org/project/validator-ai-mcp](https://pypi.org/project/validator-ai-mcp/)

## License

MIT — MEOK AI Labs
