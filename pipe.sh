#!/bin/bash
set -e

# ---------------------------------------------------------------------------
# Entrypoint of the Bitbucket Pipe: solivellaluis/confluence-sync
#
# Required environment variables:
#   CONFLUENCE_URL        - Confluence base URL
#   CONFLUENCE_USER       - Email (Cloud) or username (Server)
#   CONFLUENCE_API_TOKEN  - API Token (Cloud) or password (Server)
#   CONFLUENCE_SPACE_KEY  - Space key (e.g., PROJ)
#
# Optional variables:
#   CONFLUENCE_PARENT_ID  - Root parent page ID
#   FILES                 - Files/directories to sync (space-separated)
#   DRY_RUN               - "true" to simulate without publishing changes
# ---------------------------------------------------------------------------

# Detect the workspace directory across different CI platforms:
#   - Bitbucket Pipelines: $BITBUCKET_CLONE_DIR
#   - GitLab CI:           $CI_PROJECT_DIR
#   - GitHub Actions:      $GITHUB_WORKSPACE
# Fallback: current directory (local execution)
WORKDIR="${BITBUCKET_CLONE_DIR:-${CI_PROJECT_DIR:-${GITHUB_WORKSPACE:-$(pwd)}}}"

echo "[INFO] Workspace: $WORKDIR"
cd "$WORKDIR"

# Validate that files/directories to sync have been provided
if [ -z "$FILES" ]; then
  echo "[ERROR] The FILES variable is required."
  echo "[ERROR] Specify the files or directories to sync, separated by spaces."
  echo "[ERROR] Example: FILES=\"README.md docs/ manual.md\""
  exit 1
fi

# Build the --dry-run flag if applicable
DRY_RUN_FLAG=""
if [ "${DRY_RUN}" = "true" ]; then
  DRY_RUN_FLAG="--dry-run"
  echo "[INFO] DRY RUN mode enabled. No changes will be made to Confluence."
fi

echo "[INFO] Files/directories to sync: $FILES"
echo "[INFO] Starting sync with Confluence..."
echo "------------------------------------------------------------"

# Run the sync script
# $FILES is intentionally unquoted to split by words
# shellcheck disable=SC2086
python /scripts/sync_to_confluence.py $FILES $DRY_RUN_FLAG
