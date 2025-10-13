#!/usr/bin/env python3
"""
Script to fix OpenAPI security issues:
1. Remove authentication from logout endpoint
2. Remove AdminApiKeyQuery security scheme (query param auth is insecure)
"""

import json
import sys
from pathlib import Path


def fix_openapi_security():
    """Fix OpenAPI security issues."""
    openapi_file = Path("openapi.json")

    if not openapi_file.exists():
        print(f"Error: {openapi_file} not found")
        sys.exit(1)

    print(f"Reading {openapi_file}...")
    with open(openapi_file, 'r') as f:
        openapi = json.load(f)

    changes_made = []

    # Fix 1: Remove authentication from logout endpoint
    logout_path = "/admin/auth/logout"
    if logout_path in openapi.get("paths", {}):
        logout_endpoint = openapi["paths"][logout_path]["post"]

        # Remove security requirement
        if "security" in logout_endpoint:
            del logout_endpoint["security"]
            changes_made.append("Removed security requirement from logout endpoint")

        # Remove 401 response
        if "401" in logout_endpoint.get("responses", {}):
            del logout_endpoint["responses"]["401"]
            changes_made.append("Removed 401 response from logout endpoint")

        # Remove 403 response
        if "403" in logout_endpoint.get("responses", {}):
            del logout_endpoint["responses"]["403"]
            changes_made.append("Removed 403 response from logout endpoint")

    # Fix 2: Remove AdminApiKeyQuery security scheme
    if "components" in openapi and "securitySchemes" in openapi["components"]:
        if "AdminApiKeyQuery" in openapi["components"]["securitySchemes"]:
            del openapi["components"]["securitySchemes"]["AdminApiKeyQuery"]
            changes_made.append("Removed AdminApiKeyQuery security scheme")

    # Remove AdminApiKeyQuery from all endpoint security arrays
    endpoints_fixed = 0
    for path, methods in openapi.get("paths", {}).items():
        for method, endpoint in methods.items():
            if isinstance(endpoint, dict) and "security" in endpoint:
                original_security = endpoint["security"]
                # Filter out AdminApiKeyQuery entries
                endpoint["security"] = [
                    sec for sec in original_security
                    if "AdminApiKeyQuery" not in sec
                ]
                # Remove empty security arrays
                if not endpoint["security"]:
                    del endpoint["security"]

                if endpoint.get("security") != original_security:
                    endpoints_fixed += 1

    if endpoints_fixed > 0:
        changes_made.append(f"Removed AdminApiKeyQuery from {endpoints_fixed} endpoints")

    # Update API description to reflect removal
    if "info" in openapi and "description" in openapi["info"]:
        description = openapi["info"]["description"]
        if "AdminApiKeyQuery" in description or "query parameter" in description.lower():
            # Update description to remove query param auth mention
            description = description.replace(
                "Query parameter: `api_key=YOUR_API_KEY`\n", ""
            )
            description = description.replace(
                "or query parameter (`api_key`)", ""
            )
            openapi["info"]["description"] = description
            changes_made.append("Updated API description to remove query param auth")

    if not changes_made:
        print("No changes needed - OpenAPI spec is already correct")
        return

    # Write updated OpenAPI spec
    print(f"\nWriting updated {openapi_file}...")
    with open(openapi_file, 'w') as f:
        json.dump(openapi, f, indent=2)

    print("\n✅ Successfully fixed OpenAPI security issues:")
    for change in changes_made:
        print(f"  - {change}")

    print(f"\n📝 Updated file: {openapi_file}")


if __name__ == "__main__":
    fix_openapi_security()
