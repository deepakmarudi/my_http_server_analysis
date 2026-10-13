#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANALYTICS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WRK2_DIR="${ANALYTICS_DIR}/loadtest/wrk2"
WRK2_REPO_URL="${WRK2_REPO_URL:-https://github.com/giltene/wrk2.git}"

need_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        exit 1
    fi
}

need_command git
need_command make
need_command gcc

if [ ! -d "${WRK2_DIR}/.git" ]; then
    git clone --depth 1 "${WRK2_REPO_URL}" "${WRK2_DIR}"
else
    echo "wrk2 already exists at ${WRK2_DIR}"
fi

make -C "${WRK2_DIR}"

if [ ! -x "${WRK2_DIR}/wrk" ]; then
    echo "wrk2 build finished, but ${WRK2_DIR}/wrk is missing or not executable" >&2
    exit 1
fi

echo "wrk2 is ready: ${WRK2_DIR}/wrk"

