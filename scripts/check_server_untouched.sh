#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANALYTICS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${ANALYTICS_DIR}/config.env"

if [ -f "${CONFIG_FILE}" ]; then
    # shellcheck source=/dev/null
    source "${CONFIG_FILE}"
fi

SERVER_DIR="${SERVER_DIR:-../server}"
SERVER_DIR_ABS="$(cd "${ANALYTICS_DIR}/${SERVER_DIR}" && pwd)"
BASELINE_FILE="${SERVER_BASELINE_FILE:-${ANALYTICS_DIR}/data/raw/server_git_baseline.txt}"
MODE="${1:---check}"

usage() {
    cat <<'EOF'
Usage: ./scripts/check_server_untouched.sh [--init|--check]

--init   Capture the server commit and status if no baseline exists.
--check  Compare current server commit/status with the captured baseline.
EOF
}

current_commit() {
    git -C "${SERVER_DIR_ABS}" rev-parse HEAD
}

current_status() {
    git -C "${SERVER_DIR_ABS}" status --porcelain=v1
}

write_baseline() {
    mkdir -p "$(dirname "${BASELINE_FILE}")"
    {
        printf 'server_dir=%s\n' "${SERVER_DIR_ABS}"
        printf 'commit=%s\n' "$(current_commit)"
        printf 'captured_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf 'status_begin\n'
        current_status
        printf 'status_end\n'
    } > "${BASELINE_FILE}"
}

baseline_commit() {
    sed -n 's/^commit=//p' "${BASELINE_FILE}" | head -n 1
}

baseline_status_file() {
    local output="$1"
    sed -n '/^status_begin$/,/^status_end$/p' "${BASELINE_FILE}" | sed '1d;$d' | sort > "${output}"
}

print_lines_or_clean() {
    local file="$1"
    local label="$2"

    if [ -s "${file}" ]; then
        echo "${label}:"
        sed 's/^/  /' "${file}"
    else
        echo "${label}: none"
    fi
}

check_status() {
    local baseline_commit_value
    local current_commit_value
    local tmpdir
    local baseline_status
    local current_status_file
    local pre_existing
    local new_changes
    local resolved_changes
    local failed=0

    if [ ! -f "${BASELINE_FILE}" ]; then
        echo "No server baseline found at ${BASELINE_FILE}. Run with --init first." >&2
        return 2
    fi

    baseline_commit_value="$(baseline_commit)"
    current_commit_value="$(current_commit)"

    tmpdir="$(mktemp -d)"
    baseline_status="${tmpdir}/baseline_status"
    current_status_file="${tmpdir}/current_status"
    pre_existing="${tmpdir}/pre_existing"
    new_changes="${tmpdir}/new_changes"
    resolved_changes="${tmpdir}/resolved_changes"

    baseline_status_file "${baseline_status}"
    current_status | sort > "${current_status_file}"

    comm -12 "${baseline_status}" "${current_status_file}" > "${pre_existing}"
    comm -13 "${baseline_status}" "${current_status_file}" > "${new_changes}"
    comm -23 "${baseline_status}" "${current_status_file}" > "${resolved_changes}"

    echo "Server baseline commit: ${baseline_commit_value}"
    echo "Server current commit:  ${current_commit_value}"

    if [ "${baseline_commit_value}" != "${current_commit_value}" ]; then
        echo "Server commit changed after baseline capture." >&2
        failed=1
    fi

    print_lines_or_clean "${pre_existing}" "Pre-existing server status entries"
    print_lines_or_clean "${new_changes}" "Newly appearing server status entries"
    print_lines_or_clean "${resolved_changes}" "Baseline entries no longer present"

    if [ -s "${new_changes}" ]; then
        failed=1
    fi

    rm -rf "${tmpdir}"
    return "${failed}"
}

case "${MODE}" in
    --init)
        if [ -f "${BASELINE_FILE}" ] && [ "${FORCE_SERVER_BASELINE:-0}" != "1" ]; then
            echo "Server baseline already exists at ${BASELINE_FILE}"
            check_status
        else
            write_baseline
            echo "Captured server baseline at ${BASELINE_FILE}"
            check_status
        fi
        ;;
    --check)
        check_status
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

