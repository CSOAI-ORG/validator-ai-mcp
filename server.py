#!/usr/bin/env python3
"""Validator AI MCP Server - JSON schema validation, email/URL checking, data quality, and API response validation."""

import sys, os
sys.path.insert(0, os.path.expanduser('~/clawd/meok-labs-engine/shared'))
from auth_middleware import check_access

import json, re, time, hashlib
from collections import defaultdict
from urllib.parse import urlparse
from mcp.server.fastmcp import FastMCP

# Rate limiting
_rate_limits: dict = defaultdict(list)
RATE_WINDOW = 60
MAX_REQUESTS = 30

def _check_rate(key: str) -> bool:
    now = time.time()
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < RATE_WINDOW]
    if len(_rate_limits[key]) >= MAX_REQUESTS:
        return False
    _rate_limits[key].append(now)
    return True

# Common disposable email domains
DISPOSABLE_DOMAINS = {
    "tempmail.com", "throwaway.email", "guerrillamail.com", "mailinator.com",
    "yopmail.com", "10minutemail.com", "trashmail.com", "fakeinbox.com",
    "sharklasers.com", "guerrillamailblock.com", "grr.la", "dispostable.com",
}

# Common TLDs for basic validation
VALID_TLDS = {
    "com", "org", "net", "edu", "gov", "io", "co", "uk", "de", "fr",
    "ai", "app", "dev", "tech", "info", "biz", "us", "ca", "au",
    "jp", "cn", "in", "br", "nl", "se", "no", "fi", "dk", "it", "es",
}

mcp = FastMCP("validator-ai-mcp", instructions="Validate JSON against schemas, check email deliverability, verify URLs, assess data quality, and validate API responses. Uses RFC-compliant checks and heuristic analysis.")


def _validate_type(value, expected_type: str) -> bool:
    """Check if a value matches an expected JSON Schema type."""
    type_map = {
        "string": str, "number": (int, float), "integer": int,
        "boolean": bool, "array": list, "object": dict, "null": type(None),
    }
    expected = type_map.get(expected_type)
    if expected is None:
        return True
    return isinstance(value, expected)


def _validate_schema_recursive(data, schema: dict, path: str = "") -> list:
    """Recursively validate data against a JSON Schema subset."""
    errors = []
    current_path = path or "$"

    # Type check
    if "type" in schema:
        if not _validate_type(data, schema["type"]):
            errors.append({"path": current_path, "error": f"Expected type '{schema['type']}', got '{type(data).__name__}'"})
            return errors

    # String constraints
    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append({"path": current_path, "error": f"String length {len(data)} below minimum {schema['minLength']}"})
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errors.append({"path": current_path, "error": f"String length {len(data)} exceeds maximum {schema['maxLength']}"})
        if "pattern" in schema:
            if not re.search(schema["pattern"], data):
                errors.append({"path": current_path, "error": f"String does not match pattern '{schema['pattern']}'"})
        if "enum" in schema and data not in schema["enum"]:
            errors.append({"path": current_path, "error": f"Value '{data}' not in enum {schema['enum']}"})
        if "format" in schema:
            fmt = schema["format"]
            if fmt == "email" and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', data):
                errors.append({"path": current_path, "error": "Invalid email format"})
            elif fmt == "uri" and not re.match(r'^https?://', data):
                errors.append({"path": current_path, "error": "Invalid URI format"})
            elif fmt == "date" and not re.match(r'^\d{4}-\d{2}-\d{2}$', data):
                errors.append({"path": current_path, "error": "Invalid date format (expected YYYY-MM-DD)"})

    # Number constraints
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append({"path": current_path, "error": f"Value {data} below minimum {schema['minimum']}"})
        if "maximum" in schema and data > schema["maximum"]:
            errors.append({"path": current_path, "error": f"Value {data} exceeds maximum {schema['maximum']}"})
        if "exclusiveMinimum" in schema and data <= schema["exclusiveMinimum"]:
            errors.append({"path": current_path, "error": f"Value {data} not above exclusive minimum {schema['exclusiveMinimum']}"})

    # Array constraints
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errors.append({"path": current_path, "error": f"Array has {len(data)} items, minimum is {schema['minItems']}"})
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errors.append({"path": current_path, "error": f"Array has {len(data)} items, maximum is {schema['maxItems']}"})
        if "uniqueItems" in schema and schema["uniqueItems"]:
            seen = []
            for item in data:
                s = json.dumps(item, sort_keys=True)
                if s in seen:
                    errors.append({"path": current_path, "error": "Array contains duplicate items"})
                    break
                seen.append(s)
        if "items" in schema:
            for i, item in enumerate(data):
                errors.extend(_validate_schema_recursive(item, schema["items"], f"{current_path}[{i}]"))

    # Object constraints
    if isinstance(data, dict):
        if "required" in schema:
            for req in schema["required"]:
                if req not in data:
                    errors.append({"path": f"{current_path}.{req}", "error": f"Required property '{req}' is missing"})
        if "properties" in schema:
            for prop, prop_schema in schema["properties"].items():
                if prop in data:
                    errors.extend(_validate_schema_recursive(data[prop], prop_schema, f"{current_path}.{prop}"))
        if "additionalProperties" in schema and schema["additionalProperties"] is False:
            allowed_props = set(schema.get("properties", {}).keys())
            extra = set(data.keys()) - allowed_props
            for prop in extra:
                errors.append({"path": f"{current_path}.{prop}", "error": f"Additional property '{prop}' not allowed"})

    return errors


@mcp.tool()
async def validate_json(data: str, schema: str = "", api_key: str = "") -> str:
    """Validate JSON string, optionally against a JSON Schema. Schema as JSON string."""
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return json.dumps({"error": msg, "upgrade_url": "https://meok.ai/pricing"})
    if not _check_rate(api_key or "anon"):
        return json.dumps({"error": "Rate limit exceeded. Try again in 60 seconds."})

    # Parse JSON
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as e:
        # Provide helpful error location
        return json.dumps({
            "valid": False,
            "parse_error": True,
            "error": str(e),
            "line": e.lineno,
            "column": e.colno,
            "position": e.pos,
        })

    result = {
        "valid": True,
        "parse_error": False,
        "data_type": type(parsed).__name__,
        "data_size": len(data),
    }

    # Basic stats
    if isinstance(parsed, dict):
        result["key_count"] = len(parsed)
        result["keys"] = list(parsed.keys())[:20]
    elif isinstance(parsed, list):
        result["item_count"] = len(parsed)
        if parsed:
            result["first_item_type"] = type(parsed[0]).__name__

    # Schema validation
    if schema:
        try:
            schema_obj = json.loads(schema)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid schema JSON: {e}"})

        errors = _validate_schema_recursive(parsed, schema_obj)
        result["schema_validation"] = {
            "valid": len(errors) == 0,
            "error_count": len(errors),
            "errors": errors[:25],
        }
        if errors:
            result["valid"] = False

    result["validated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return json.dumps(result)


@mcp.tool()
async def validate_email(email: str, api_key: str = "") -> str:
    """Validate email format, domain structure, and check for disposable addresses."""
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return json.dumps({"error": msg, "upgrade_url": "https://meok.ai/pricing"})
    if not _check_rate(api_key or "anon"):
        return json.dumps({"error": "Rate limit exceeded. Try again in 60 seconds."})

    if not email or not email.strip():
        return json.dumps({"error": "Email address is required"})

    email = email.strip().lower()
    issues = []
    checks = {}

    # Basic format check (RFC 5322 simplified)
    email_regex = r'^[a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'
    format_valid = bool(re.match(email_regex, email))
    checks["format_valid"] = format_valid
    if not format_valid:
        issues.append({"type": "format", "severity": "critical", "detail": "Email does not match RFC 5322 format"})

    # Split parts
    if "@" in email:
        local_part, domain = email.rsplit("@", 1)
    else:
        return json.dumps({"email": email, "valid": False, "issues": [{"type": "format", "detail": "Missing @ symbol"}]})

    # Local part checks
    if len(local_part) > 64:
        issues.append({"type": "local_part", "severity": "high", "detail": "Local part exceeds 64 characters"})
    if local_part.startswith(".") or local_part.endswith("."):
        issues.append({"type": "local_part", "severity": "medium", "detail": "Local part starts/ends with dot"})
    if ".." in local_part:
        issues.append({"type": "local_part", "severity": "medium", "detail": "Local part contains consecutive dots"})
    checks["local_part_valid"] = len([i for i in issues if i["type"] == "local_part"]) == 0

    # Domain checks
    if len(domain) > 253:
        issues.append({"type": "domain", "severity": "high", "detail": "Domain exceeds 253 characters"})
    domain_parts = domain.split(".")
    if len(domain_parts) < 2:
        issues.append({"type": "domain", "severity": "critical", "detail": "Domain must have at least two parts"})
    tld = domain_parts[-1] if domain_parts else ""
    checks["has_valid_tld"] = tld in VALID_TLDS
    if not checks["has_valid_tld"]:
        issues.append({"type": "domain", "severity": "medium", "detail": f"TLD '.{tld}' is uncommon (may still be valid)"})

    # Disposable check
    is_disposable = domain in DISPOSABLE_DOMAINS
    checks["is_disposable"] = is_disposable
    if is_disposable:
        issues.append({"type": "disposable", "severity": "high", "detail": f"Domain '{domain}' is a known disposable email provider"})

    # Role-based check
    role_prefixes = ["admin", "info", "support", "sales", "noreply", "no-reply", "postmaster", "webmaster", "abuse"]
    is_role = local_part in role_prefixes
    checks["is_role_address"] = is_role
    if is_role:
        issues.append({"type": "role_address", "severity": "low", "detail": f"'{local_part}' is a role-based address"})

    overall_valid = format_valid and not is_disposable and len([i for i in issues if i["severity"] == "critical"]) == 0

    # Quality score
    quality = 100
    for issue in issues:
        if issue["severity"] == "critical":
            quality -= 40
        elif issue["severity"] == "high":
            quality -= 20
        elif issue["severity"] == "medium":
            quality -= 10
        elif issue["severity"] == "low":
            quality -= 5
    quality = max(0, quality)

    return json.dumps({
        "email": email,
        "valid": overall_valid,
        "quality_score": quality,
        "local_part": local_part,
        "domain": domain,
        "tld": tld,
        "checks": checks,
        "issues": issues,
        "validated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


@mcp.tool()
async def validate_url(url: str, api_key: str = "") -> str:
    """Validate URL format, structure, and security characteristics."""
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return json.dumps({"error": msg, "upgrade_url": "https://meok.ai/pricing"})
    if not _check_rate(api_key or "anon"):
        return json.dumps({"error": "Rate limit exceeded. Try again in 60 seconds."})

    if not url or not url.strip():
        return json.dumps({"error": "URL is required"})

    url = url.strip()
    issues = []
    checks = {}

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        return json.dumps({"url": url, "valid": False, "error": f"URL parse error: {e}"})

    # Scheme check
    checks["has_scheme"] = bool(parsed.scheme)
    checks["is_https"] = parsed.scheme == "https"
    checks["scheme"] = parsed.scheme

    if not parsed.scheme:
        issues.append({"type": "scheme", "severity": "high", "detail": "Missing URL scheme (http:// or https://)"})
    elif parsed.scheme not in ["http", "https", "ftp", "ftps"]:
        issues.append({"type": "scheme", "severity": "medium", "detail": f"Unusual scheme: {parsed.scheme}"})
    if parsed.scheme == "http":
        issues.append({"type": "security", "severity": "medium", "detail": "Using HTTP instead of HTTPS - data not encrypted"})

    # Host check
    checks["has_host"] = bool(parsed.hostname)
    if not parsed.hostname:
        issues.append({"type": "host", "severity": "critical", "detail": "No hostname in URL"})
    else:
        hostname = parsed.hostname
        # IP address check
        is_ip = bool(re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', hostname))
        checks["is_ip_address"] = is_ip
        if is_ip:
            issues.append({"type": "host", "severity": "low", "detail": "URL uses IP address instead of domain name"})
            # Check for private IPs
            octets = hostname.split(".")
            if octets[0] in ["10", "127"] or (octets[0] == "192" and octets[1] == "168") or (octets[0] == "172" and 16 <= int(octets[1]) <= 31):
                issues.append({"type": "security", "severity": "high", "detail": "URL points to private/localhost IP address"})

        # Domain structure
        if not is_ip:
            parts = hostname.split(".")
            tld = parts[-1] if parts else ""
            checks["tld"] = tld
            checks["domain_depth"] = len(parts)
            if len(parts) < 2:
                issues.append({"type": "host", "severity": "high", "detail": "Domain lacks TLD"})
            if len(hostname) > 253:
                issues.append({"type": "host", "severity": "high", "detail": "Hostname exceeds 253 characters"})

    # Port check
    checks["port"] = parsed.port
    if parsed.port and parsed.port not in [80, 443, 8080, 8443]:
        issues.append({"type": "port", "severity": "low", "detail": f"Non-standard port: {parsed.port}"})

    # Path check
    checks["has_path"] = bool(parsed.path and parsed.path != "/")
    checks["path"] = parsed.path

    # Query string
    checks["has_query"] = bool(parsed.query)
    if parsed.query:
        params = parsed.query.split("&")
        checks["query_param_count"] = len(params)
        # Check for sensitive params
        sensitive_patterns = ["password", "token", "secret", "key", "apikey", "api_key", "auth"]
        for param in params:
            param_name = param.split("=")[0].lower()
            for pattern in sensitive_patterns:
                if pattern in param_name:
                    issues.append({"type": "security", "severity": "high", "detail": f"Potentially sensitive parameter in URL: {param_name}"})
                    break

    # Fragment
    checks["has_fragment"] = bool(parsed.fragment)

    # Overall
    has_critical = any(i["severity"] == "critical" for i in issues)
    overall_valid = checks.get("has_scheme", False) and checks.get("has_host", False) and not has_critical

    quality = 100
    for issue in issues:
        if issue["severity"] == "critical":
            quality -= 40
        elif issue["severity"] == "high":
            quality -= 20
        elif issue["severity"] == "medium":
            quality -= 10
        elif issue["severity"] == "low":
            quality -= 5
    quality = max(0, quality)

    return json.dumps({
        "url": url,
        "valid": overall_valid,
        "quality_score": quality,
        "components": {
            "scheme": parsed.scheme,
            "host": parsed.hostname,
            "port": parsed.port,
            "path": parsed.path,
            "query": parsed.query or None,
            "fragment": parsed.fragment or None,
        },
        "checks": checks,
        "issues": issues,
        "validated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


@mcp.tool()
async def validate_data_quality(data: str, api_key: str = "") -> str:
    """Check a JSON dataset for quality issues: nulls, duplicates, type consistency, outliers. Pass data as JSON array of objects."""
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return json.dumps({"error": msg, "upgrade_url": "https://meok.ai/pricing"})
    if not _check_rate(api_key or "anon"):
        return json.dumps({"error": "Rate limit exceeded. Try again in 60 seconds."})

    try:
        records = json.loads(data)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})

    if not isinstance(records, list):
        return json.dumps({"error": "Data must be a JSON array of objects"})
    if not records:
        return json.dumps({"error": "Empty dataset"})
    if not isinstance(records[0], dict):
        return json.dumps({"error": "Array items must be objects"})

    total_records = len(records)
    issues = []

    # Collect all field names
    all_fields = set()
    for rec in records:
        all_fields.update(rec.keys())
    all_fields = sorted(all_fields)

    # Per-field analysis
    field_stats = {}
    for field in all_fields:
        values = [rec.get(field) for rec in records]
        null_count = sum(1 for v in values if v is None or v == "" or v == "null")
        non_null_values = [v for v in values if v is not None and v != "" and v != "null"]

        # Type consistency
        types = set(type(v).__name__ for v in non_null_values)
        type_consistent = len(types) <= 1

        stats = {
            "present": total_records - null_count,
            "null_or_empty": null_count,
            "completeness_pct": round(((total_records - null_count) / total_records) * 100, 1),
            "types_found": list(types),
            "type_consistent": type_consistent,
        }

        # Numeric stats
        numeric_values = [v for v in non_null_values if isinstance(v, (int, float))]
        if numeric_values:
            mean_val = sum(numeric_values) / len(numeric_values)
            stats["min"] = min(numeric_values)
            stats["max"] = max(numeric_values)
            stats["mean"] = round(mean_val, 2)
            # Simple outlier detection (>3 std devs)
            if len(numeric_values) > 2:
                variance = sum((x - mean_val) ** 2 for x in numeric_values) / len(numeric_values)
                std_dev = variance ** 0.5
                if std_dev > 0:
                    outliers = [v for v in numeric_values if abs(v - mean_val) > 3 * std_dev]
                    stats["outlier_count"] = len(outliers)
                    if outliers:
                        issues.append({"field": field, "type": "outliers", "count": len(outliers), "severity": "medium"})

        # String uniqueness
        string_values = [v for v in non_null_values if isinstance(v, str)]
        if string_values:
            unique_count = len(set(string_values))
            stats["unique_values"] = unique_count
            stats["cardinality_pct"] = round((unique_count / len(string_values)) * 100, 1)

        # Flag issues
        if null_count > total_records * 0.5:
            issues.append({"field": field, "type": "high_null_rate", "null_pct": stats["completeness_pct"], "severity": "high"})
        elif null_count > total_records * 0.2:
            issues.append({"field": field, "type": "moderate_null_rate", "null_pct": stats["completeness_pct"], "severity": "medium"})
        if not type_consistent:
            issues.append({"field": field, "type": "mixed_types", "types": list(types), "severity": "high"})

        field_stats[field] = stats

    # Duplicate record detection
    seen_hashes = set()
    duplicate_count = 0
    for rec in records:
        rec_hash = hashlib.md5(json.dumps(rec, sort_keys=True).encode()).hexdigest()
        if rec_hash in seen_hashes:
            duplicate_count += 1
        seen_hashes.add(rec_hash)
    if duplicate_count > 0:
        issues.append({"field": "_record", "type": "duplicates", "count": duplicate_count, "severity": "high"})

    # Schema consistency (do all records have same fields?)
    field_presence = defaultdict(int)
    for rec in records:
        for f in rec.keys():
            field_presence[f] += 1
    inconsistent_fields = [f for f, count in field_presence.items() if count < total_records]
    if inconsistent_fields:
        issues.append({"field": "_schema", "type": "inconsistent_fields", "fields": inconsistent_fields, "severity": "medium"})

    # Quality score
    quality = 100
    for issue in issues:
        if issue["severity"] == "high":
            quality -= 15
        elif issue["severity"] == "medium":
            quality -= 8
    quality = max(0, quality)

    return json.dumps({
        "total_records": total_records,
        "total_fields": len(all_fields),
        "fields": all_fields,
        "field_stats": field_stats,
        "duplicate_records": duplicate_count,
        "quality_score": quality,
        "issue_count": len(issues),
        "issues": issues,
        "validated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


@mcp.tool()
async def validate_api_response(response_body: str, expected_status: int = 200, expected_content_type: str = "application/json", required_fields: str = "", api_key: str = "") -> str:
    """Validate an API response body and structure. Required fields as comma-separated string."""
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return json.dumps({"error": msg, "upgrade_url": "https://meok.ai/pricing"})
    if not _check_rate(api_key or "anon"):
        return json.dumps({"error": "Rate limit exceeded. Try again in 60 seconds."})

    issues = []
    checks = {}

    # Parse body
    parsed_body = None
    if expected_content_type == "application/json":
        try:
            parsed_body = json.loads(response_body)
            checks["body_parseable"] = True
        except json.JSONDecodeError as e:
            checks["body_parseable"] = False
            issues.append({"type": "parse_error", "severity": "critical", "detail": f"Response body is not valid JSON: {e}"})
    else:
        checks["body_parseable"] = True
        parsed_body = response_body

    # Status code validation
    checks["status_code"] = expected_status
    is_success = 200 <= expected_status < 300
    is_error = expected_status >= 400
    checks["is_success_status"] = is_success

    if is_error:
        issues.append({"type": "status", "severity": "high", "detail": f"Error status code: {expected_status}"})

    # Required fields check
    req_fields = [f.strip() for f in required_fields.split(",") if f.strip()] if required_fields else []
    if req_fields and isinstance(parsed_body, dict):
        missing = [f for f in req_fields if f not in parsed_body]
        present = [f for f in req_fields if f in parsed_body]
        checks["required_fields_present"] = len(missing) == 0
        checks["missing_fields"] = missing
        if missing:
            issues.append({"type": "missing_fields", "severity": "high", "detail": f"Missing required fields: {missing}"})
    elif req_fields and parsed_body is not None and not isinstance(parsed_body, dict):
        issues.append({"type": "structure", "severity": "medium", "detail": "Cannot check required fields - response is not an object"})

    # Common API response patterns
    if isinstance(parsed_body, dict):
        # Check for error indicators in body
        error_keys = ["error", "errors", "error_message", "error_code"]
        for key in error_keys:
            if key in parsed_body and parsed_body[key]:
                issues.append({"type": "error_in_body", "severity": "high", "detail": f"Error field '{key}' present: {str(parsed_body[key])[:100]}"})

        # Check for empty data
        data_keys = ["data", "results", "items", "records"]
        for key in data_keys:
            if key in parsed_body:
                if isinstance(parsed_body[key], list) and len(parsed_body[key]) == 0:
                    issues.append({"type": "empty_data", "severity": "low", "detail": f"'{key}' array is empty"})

        # Check for pagination indicators
        pagination_keys = ["page", "total", "total_count", "next", "has_more", "cursor", "offset", "limit"]
        has_pagination = any(k in parsed_body for k in pagination_keys)
        checks["has_pagination"] = has_pagination

        # Response size
        checks["response_keys"] = list(parsed_body.keys())[:20]
        checks["key_count"] = len(parsed_body)

    # Body size
    body_size = len(response_body)
    checks["body_size_bytes"] = body_size
    if body_size > 10_000_000:
        issues.append({"type": "size", "severity": "medium", "detail": f"Large response body: {body_size / 1_000_000:.1f} MB"})
    if body_size == 0:
        issues.append({"type": "empty", "severity": "medium", "detail": "Empty response body"})

    # Overall validity
    has_critical = any(i["severity"] == "critical" for i in issues)
    has_high = any(i["severity"] == "high" for i in issues)
    overall_valid = not has_critical and is_success

    quality = 100
    for issue in issues:
        if issue["severity"] == "critical":
            quality -= 40
        elif issue["severity"] == "high":
            quality -= 20
        elif issue["severity"] == "medium":
            quality -= 10
        elif issue["severity"] == "low":
            quality -= 5
    quality = max(0, quality)

    return json.dumps({
        "valid": overall_valid,
        "quality_score": quality,
        "expected_status": expected_status,
        "expected_content_type": expected_content_type,
        "body_size_bytes": body_size,
        "checks": checks,
        "issues": issues,
        "validated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


if __name__ == "__main__":
    mcp.run()
