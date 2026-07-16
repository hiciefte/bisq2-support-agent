#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPOSITORY_DIR="$(cd "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REMOTE="origin"
COMMIT=""
MODEL_ENV_FILE=""
REPOSITORY_SLUG=""

usage() {
    cat <<'EOF'
Usage: verify-release-ai-quality-gate.sh [options]

Verify that the exact release commit has a remote AI-quality pass marker.

Options:
  --repository DIR  Repository to verify (defaults to the script's repository)
  --remote NAME     Git remote to inspect (default: origin)
  --commit SHA      Commit to verify (default: repository HEAD)
  --env-file FILE   Protected runtime env file (default: docker/.env)
  --repository-slug OWNER/REPOSITORY
                     Repository used for the authoritative workflow check
  -h, --help        Show this help
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --repository)
            [ "$#" -ge 2 ] || {
                echo "Missing value for --repository" >&2
                exit 2
            }
            REPOSITORY_DIR="$2"
            shift 2
            ;;
        --remote)
            [ "$#" -ge 2 ] || {
                echo "Missing value for --remote" >&2
                exit 2
            }
            REMOTE="$2"
            shift 2
            ;;
        --commit)
            [ "$#" -ge 2 ] || {
                echo "Missing value for --commit" >&2
                exit 2
            }
            COMMIT="$2"
            shift 2
            ;;
        --env-file)
            [ "$#" -ge 2 ] || {
                echo "Missing value for --env-file" >&2
                exit 2
            }
            MODEL_ENV_FILE="$2"
            shift 2
            ;;
        --repository-slug)
            [ "$#" -ge 2 ] || {
                echo "Missing value for --repository-slug" >&2
                exit 2
            }
            REPOSITORY_SLUG="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! "$REMOTE" =~ ^[a-zA-Z0-9._-]+$ ]]; then
    echo "Invalid git remote name" >&2
    exit 2
fi

if ! git -C "$REPOSITORY_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    echo "Release repository is not a git checkout" >&2
    exit 1
fi

if ! git -C "$REPOSITORY_DIR" remote get-url "$REMOTE" >/dev/null 2>&1; then
    echo "Release quality remote is unavailable" >&2
    exit 1
fi

resolve_repository_slug() {
    local remote_url

    remote_url=$(git -C "$REPOSITORY_DIR" remote get-url "$REMOTE")
    case "$remote_url" in
        git@github.com:*)
            REPOSITORY_SLUG="${remote_url#git@github.com:}"
            ;;
        https://github.com/*)
            REPOSITORY_SLUG="${remote_url#https://github.com/}"
            ;;
        ssh://git@github.com/*)
            REPOSITORY_SLUG="${remote_url#ssh://git@github.com/}"
            ;;
        *)
            echo "Could not derive the release repository identity" >&2
            return 1
            ;;
    esac
    REPOSITORY_SLUG="${REPOSITORY_SLUG%.git}"
    REPOSITORY_SLUG="${REPOSITORY_SLUG%/}"
}

if [ -z "$REPOSITORY_SLUG" ]; then
    resolve_repository_slug || exit 1
fi
if [[ ! "$REPOSITORY_SLUG" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    echo "Release repository identity is invalid" >&2
    exit 2
fi

if [ -z "$MODEL_ENV_FILE" ]; then
    MODEL_ENV_FILE="$REPOSITORY_DIR/docker/.env"
fi
if [ ! -f "$MODEL_ENV_FILE" ]; then
    echo "Protected runtime model configuration is unavailable" >&2
    exit 1
fi

MODEL_LINE_COUNT=$(awk '/^OPENAI_MODEL=/{count++} END{print count+0}' "$MODEL_ENV_FILE")
if [ "$MODEL_LINE_COUNT" -ne 1 ]; then
    echo "Protected runtime model configuration must contain one model ID" >&2
    exit 1
fi
MODEL_ID=$(sed -n 's/^OPENAI_MODEL=//p' "$MODEL_ENV_FILE")
if [[ ! "$MODEL_ID" =~ ^openai:[A-Za-z0-9][A-Za-z0-9._-]{0,99}$ ]]; then
    echo "Protected runtime model ID is invalid" >&2
    exit 1
fi
if command -v sha256sum >/dev/null 2>&1; then
    MODEL_SHA256=$(printf '%s' "$MODEL_ID" | sha256sum | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
    MODEL_SHA256=$(printf '%s' "$MODEL_ID" | shasum -a 256 | awk '{print $1}')
else
    echo "A SHA-256 utility is required to verify the release model" >&2
    exit 1
fi
if [[ ! "$MODEL_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Could not derive the release model identity" >&2
    exit 1
fi

if [ -z "$COMMIT" ]; then
    COMMIT=$(git -C "$REPOSITORY_DIR" rev-parse HEAD)
fi
COMMIT=$(printf '%s' "$COMMIT" | tr '[:upper:]' '[:lower:]')

if [[ ! "$COMMIT" =~ ^[0-9a-f]{40,64}$ ]]; then
    echo "Release commit must be a full git object ID" >&2
    exit 2
fi

if ! git -C "$REPOSITORY_DIR" cat-file -e "${COMMIT}^{commit}" 2>/dev/null; then
    echo "Release commit is unavailable in the checkout" >&2
    exit 1
fi

HEAD_COMMIT=$(git -C "$REPOSITORY_DIR" rev-parse HEAD | tr '[:upper:]' '[:lower:]')
if [ "$HEAD_COMMIT" != "$COMMIT" ]; then
    echo "Release commit does not match the checked-out build tree" >&2
    exit 1
fi
if ! git -C "$REPOSITORY_DIR" diff --quiet "$COMMIT" --; then
    echo "Release build tree differs from the evaluated commit" >&2
    exit 1
fi
UNTRACKED_FOUND=false
while IFS= read -r -d '' _path; do
    UNTRACKED_FOUND=true
    break
done < <(git -C "$REPOSITORY_DIR" ls-files --others --exclude-standard -z)
if [ "$UNTRACKED_FOUND" = true ]; then
    echo "Release build tree contains untracked inputs" >&2
    exit 1
fi

if ! command -v curl >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
    echo "curl and jq are required to verify the release workflow" >&2
    exit 1
fi
WORKFLOW_RUNS_URL="https://api.github.com/repos/${REPOSITORY_SLUG}/actions/workflows/ai-quality-gate.yml/runs?head_sha=${COMMIT}&per_page=100"
if ! WORKFLOW_RUNS=$(
    curl -fsS --connect-timeout 10 --max-time 30 --retry 2 \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2026-03-10" \
        "$WORKFLOW_RUNS_URL"
); then
    echo "Could not verify the authoritative AI-quality workflow result" >&2
    exit 1
fi
if ! LATEST_RUN=$(
    printf '%s' "$WORKFLOW_RUNS" | jq -cer --arg commit "$COMMIT" '
        [
          .workflow_runs[]?
          | select(.head_sha == $commit)
          | select(
              (.event == "push"
               and (.head_branch | type) == "string"
               and (.head_branch | test("^release/[^/]+$")))
              or (.event == "schedule" and .head_branch == "main")
              or (.event == "workflow_dispatch"
                  and ((.head_branch == "main")
                       or ((.head_branch | type) == "string"
                           and (.head_branch | test("^release/[^/]+$")))))
            )
        ]
        | if length == 0
          then error("no eligible run")
          else max_by(.run_number, .run_attempt)
          end
        | {
            head_sha,
            status,
            conclusion,
            run_number,
            run_attempt
          }
    ' 2>/dev/null
); then
    echo "No authoritative AI-quality workflow run exists for this commit" >&2
    exit 1
fi
if ! printf '%s' "$LATEST_RUN" | jq -e --arg commit "$COMMIT" '
    .head_sha == $commit
    and .status == "completed"
    and .conclusion == "success"
' >/dev/null; then
    echo "Latest AI-quality workflow run is not successful" >&2
    exit 1
fi

MARKER_REF="refs/tags/release-ai-quality/${COMMIT}/${MODEL_SHA256}"
if ! REMOTE_RESULT=$(
    git -C "$REPOSITORY_DIR" ls-remote --refs "$REMOTE" "$MARKER_REF"
); then
    echo "Could not verify the remote AI-quality pass marker" >&2
    exit 1
fi

REMOTE_COMMIT=$(printf '%s\n' "$REMOTE_RESULT" | awk 'NR == 1 { print $1 }')
REMOTE_REF=$(printf '%s\n' "$REMOTE_RESULT" | awk 'NR == 1 { print $2 }')
if [ "$REMOTE_COMMIT" != "$COMMIT" ] || [ "$REMOTE_REF" != "$MARKER_REF" ]; then
    echo "Release commit has no matching AI-quality pass marker" >&2
    exit 1
fi

echo "Release AI-quality pass marker verified"
