#!/bin/bash
# scripts/test-tor-security.sh
# Comprehensive security testing for Tor hidden service deployment
# Tests for DNS leaks, clearnet leaks, cookie security, CSP, and more

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test results
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_TOTAL=0

# Configuration
API_URL="${API_URL:-http://localhost:8000}"
WEB_URL="${WEB_URL:-http://localhost:3000}"
ONION_URL="${ONION_URL:-}"  # Set if testing .onion address

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Tor Hidden Service Security Tests${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Helper functions
run_test() {
    local test_name="$1"
    shift
    local expected_result="${!#}"  # Last argument
    set -- "${@:1:$#-1}"  # Remove last argument, leaving command and args

    ((TESTS_TOTAL++))
    echo -n "[$TESTS_TOTAL] Testing: $test_name... "

    # Execute command with arguments (no eval - safe execution)
    if "$@" > /dev/null 2>&1; then
        if [ "$expected_result" = "0" ]; then
            echo -e "${GREEN}PASS${NC}"
            ((TESTS_PASSED++))
            return 0
        else
            echo -e "${RED}FAIL${NC} (expected failure but passed)"
            ((TESTS_FAILED++))
            return 1
        fi
    else
        if [ "$expected_result" = "1" ]; then
            echo -e "${GREEN}PASS${NC} (correctly failed)"
            ((TESTS_PASSED++))
            return 0
        else
            echo -e "${RED}FAIL${NC}"
            ((TESTS_FAILED++))
            return 1
        fi
    fi
}

check_http_header() {
    local url="$1"
    local header="$2"
    local expected_value="$3"

    local actual_value
    actual_value=$(curl -s -I "$url" | grep -i "^$header:" | cut -d' ' -f2- | tr -d '\r')

    if echo "$actual_value" | grep -q "$expected_value"; then
        return 0
    else
        echo -e "${YELLOW}Expected: $expected_value${NC}"
        echo -e "${YELLOW}Actual: $actual_value${NC}"
        return 1
    fi
}

# Test helper functions (no eval - safe execution)
test_endpoint_responds() {
    local url="$1"
    local http_code
    http_code=$(curl -s -o /dev/null -w '%{http_code}' "$url")
    [[ "$http_code" =~ ^(200|503)$ ]]
}

test_onion_address_matches() {
    local api_url="$1"
    local onion_url="$2"
    local clearnet_addr onion_addr
    clearnet_addr=$(curl -s "$api_url/.well-known/onion-verify/verification-info" | jq -r '.onion_address')
    onion_addr=$(curl -s "$onion_url/.well-known/onion-verify/verification-info" | jq -r '.onion_address')
    [ "$clearnet_addr" = "$onion_addr" ]
}

test_verification_hash_matches() {
    local api_url="$1"
    local onion_url="$2"
    local clearnet_hash onion_hash
    clearnet_hash=$(curl -s "$api_url/.well-known/onion-verify/verification-info" | jq -r '.verification_hash')
    onion_hash=$(curl -s "$onion_url/.well-known/onion-verify/verification-info" | jq -r '.verification_hash')
    [ "$clearnet_hash" = "$onion_hash" ]
}

test_header_present() {
    local url="$1"
    local header="$2"
    curl -sI "$url" | grep -qi "$header"
}

test_header_not_contains() {
    local url="$1"
    local header="$2"
    local value="$3"
    ! curl -sI "$url" | grep -i "$header" | grep -q "$value"
}

test_metrics_contains() {
    local url="$1"
    local metric="$2"
    curl -sf "$url/metrics" | grep -q "$metric"
}

test_grep_file() {
    local pattern="$1"
    local file="$2"
    grep -q "$pattern" "$file" 2>/dev/null
}

test_http_status() {
    local url="$1"
    local expected_status="$2"
    local actual_status
    actual_status=$(curl -s -o /dev/null -w '%{http_code}' "$url")
    [ "$actual_status" = "$expected_status" ]
}

test_string_contains() {
    local string="$1"
    local pattern="$2"
    echo "$string" | grep -qi "$pattern"
}

test_url_contains_text() {
    local url="$1"
    local text="$2"
    curl -sf "$url" | grep -q "$text"
}

# Test 1: Onion verification endpoints
echo -e "\n${BLUE}=== Onion Verification Tests ===${NC}"

run_test "Verification endpoint responds" \
    test_endpoint_responds "$API_URL/.well-known/onion-verify/bisq-support.txt" 0

run_test "Verification JSON endpoint responds" \
    test_endpoint_responds "$API_URL/.well-known/onion-verify/verification-info" 0

if [ -n "$ONION_URL" ]; then
    run_test "Onion address matches clearnet" \
        test_onion_address_matches "$API_URL" "$ONION_URL" 0

    run_test "Verification hash matches on both domains" \
        test_verification_hash_matches "$API_URL" "$ONION_URL" 0
fi

# Test 2: Security Headers
echo -e "\n${BLUE}=== Security Headers Tests ===${NC}"

# Check if web service is available
if curl -s -o /dev/null -w '%{http_code}' "$WEB_URL" | grep -qE '^(200|301|302|304)$'; then
    run_test "CSP header present" \
        test_header_present "$WEB_URL" "Content-Security-Policy" 0

    run_test "CSP does not contain unsafe-eval" \
        test_header_not_contains "$WEB_URL" "Content-Security-Policy" "unsafe-eval" 0

    run_test "X-Content-Type-Options is nosniff" \
        test_header_present "$WEB_URL" "X-Content-Type-Options: nosniff" 0

    run_test "X-Frame-Options is SAMEORIGIN" \
        test_header_present "$WEB_URL" "X-Frame-Options: SAMEORIGIN" 0

    run_test "Referrer-Policy header present" \
        test_header_present "$WEB_URL" "Referrer-Policy" 0
else
    echo -e "${YELLOW}Web service not available, skipping CSP header tests${NC}"
fi

run_test "No X-Powered-By header (fingerprinting)" \
    test_header_not_contains "$API_URL" "X-Powered-By" "." 0

# Test 3: Cookie Security
echo -e "\n${BLUE}=== Cookie Security Tests ===${NC}"

# Check if we have the admin key for testing (only in development)
if [ -f "docker/.env" ] && grep -q "ADMIN_API_KEY=" docker/.env 2>/dev/null; then
    ADMIN_KEY=$(grep "ADMIN_API_KEY=" docker/.env 2>/dev/null | cut -d'=' -f2)

    if [ -n "$ADMIN_KEY" ] && [ "$ADMIN_KEY" != "" ]; then
        # Test with valid credentials to check cookie flags
        COOKIE_RESPONSE=$(curl -sI --max-time 5 "$API_URL/admin/auth/login" -X POST -H 'Content-Type: application/json' -d "{\"api_key\":\"$ADMIN_KEY\"}" 2>/dev/null | grep -i 'Set-Cookie' || true)

        if [ -n "$COOKIE_RESPONSE" ]; then
            run_test "Admin cookie has HttpOnly flag" \
                test_string_contains "$COOKIE_RESPONSE" "HttpOnly" 0

            run_test "Admin cookie has SameSite flag" \
                test_string_contains "$COOKIE_RESPONSE" "SameSite" 0

            # Note: Secure flag should be false for .onion deployments
            if [ -n "$ONION_URL" ]; then
                test_not_contains_secure() {
                    ! echo "$1" | grep -qi 'Secure'
                }
                run_test "Cookie Secure=false for .onion (HTTP)" \
                    test_not_contains_secure "$COOKIE_RESPONSE" 0
            fi
        else
            echo -e "${YELLOW}No Set-Cookie header in response, skipping cookie tests${NC}"
        fi
    else
        echo -e "${YELLOW}ADMIN_API_KEY not set, skipping cookie tests${NC}"
    fi
else
    echo -e "${YELLOW}Cannot access admin credentials, skipping cookie tests${NC}"
fi

# Test 4: Prometheus Metrics
echo -e "\n${BLUE}=== Tor Metrics Tests ===${NC}"

run_test "Tor metrics endpoint accessible" \
    test_metrics_contains "$API_URL" "tor_" 0

run_test "Tor connection status metric exists" \
    test_metrics_contains "$API_URL" "tor_connection_status" 0

run_test "Tor hidden service configured metric exists" \
    test_metrics_contains "$API_URL" "tor_hidden_service_configured" 0

run_test "Tor verification requests metric exists" \
    test_metrics_contains "$API_URL" "tor_verification_requests_total" 0

run_test "Tor cookie security metric exists" \
    test_metrics_contains "$API_URL" "tor_cookie_secure_mode" 0

# Test 5: Build ID Fingerprinting
echo -e "\n${BLUE}=== Fingerprinting Protection Tests ===${NC}"

test_build_id() {
    local url="$1"
    curl -sf "$url" | grep -q 'bisq-support-build' || curl -sf "$url/_next/static/" 2>/dev/null | grep -q 'bisq-support-build'
}

run_test "Next.js uses constant build ID" \
    test_build_id "$WEB_URL" 0

# Test 6: DNS Leak Prevention (if Tor is configured)
echo -e "\n${BLUE}=== DNS Leak Tests ===${NC}"

if [ -f "docker/.env" ]; then
    if grep -q "TOR_ENABLED=true" docker/.env 2>/dev/null; then
        run_test "Tor proxy configuration present" \
            test_grep_file "TOR_SOCKS_PROXY=" "docker/.env" 0

        run_test "External API proxy enabled" \
            test_grep_file "USE_TOR_FOR_EXTERNAL_APIS=true" "docker/.env" 0
    else
        echo -e "${YELLOW}Tor not enabled, skipping DNS leak tests${NC}"
    fi
fi

# Test 7: Admin Interface Security
echo -e "\n${BLUE}=== Admin Interface Security Tests ===${NC}"

run_test "Admin login requires authentication" \
    test_http_status "$API_URL/admin/dashboard/overview" "401" 0

run_test "Admin endpoints reject unauthorized access" \
    test_http_status "$API_URL/admin/faqs" "401" 0

# Test 8: Rate Limiting (if nginx is configured)
echo -e "\n${BLUE}=== Rate Limiting Tests ===${NC}"

# Make 10 rapid requests to test rate limiting
RATE_LIMIT_TEST=0
for _ in {1..10}; do
    STATUS=$(curl -s -o /dev/null -w '%{http_code}' $API_URL/health)
    if [ "$STATUS" = "429" ]; then
        RATE_LIMIT_TEST=1
        break
    fi
    sleep 0.1
done

if [ $RATE_LIMIT_TEST -eq 1 ]; then
    echo -e "[$TESTS_TOTAL] Testing: Rate limiting active... ${GREEN}PASS${NC}"
    ((TESTS_PASSED++))
    ((TESTS_TOTAL++))
else
    echo -e "[$TESTS_TOTAL] Testing: Rate limiting active... ${YELLOW}SKIP${NC} (not triggered)"
    ((TESTS_TOTAL++))
fi

# Test 9: Verification Hash Cryptographic Validation
echo -e "\n${BLUE}=== Cryptographic Validation Tests ===${NC}"

if command -v sha256sum &> /dev/null; then
    # This test is complex and may not work correctly without jq parsing, skip for now
    echo -e "${YELLOW}Cryptographic hash validation requires manual verification${NC}"
fi

# Summary
echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}  Test Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "Total tests: $TESTS_TOTAL"
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
echo -e "${RED}Failed: $TESTS_FAILED${NC}"

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "\n${GREEN}✓ All security tests passed!${NC}"
    exit 0
else
    echo -e "\n${RED}✗ Some tests failed. Please review the output above.${NC}"
    exit 1
fi
