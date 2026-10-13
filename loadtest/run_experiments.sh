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
SERVER_IMAGE="${SERVER_IMAGE:-epoll-perf-analytics-server}"
SERVER_CONTAINER_NAME="${SERVER_CONTAINER_NAME:-epoll-perf-server}"
SERVER_PORT="${SERVER_PORT:-8080}"
HOST_PORT="${HOST_PORT:-8080}"
SERVER_ROOT="${SERVER_ROOT:-/app/public}"
SERVER_WORKERS="${SERVER_WORKERS:-4}"
TARGET_PATH="${TARGET_PATH:-/}"
WORKLOAD_NAME="${WORKLOAD_NAME:-default-index}"
SMOKE_RATE="${SMOKE_RATE:-10}"
SMOKE_DURATION_SECONDS="${SMOKE_DURATION_SECONDS:-5}"
RATES="${RATES:-50 100 200 400 800}"
REPEATS="${REPEATS:-3}"
FULL_DURATION_SECONDS="${FULL_DURATION_SECONDS:-30}"
WRK2_BIN="${WRK2_BIN:-./loadtest/wrk2/wrk}"
WRK_THREADS="${WRK_THREADS:-2}"
WRK_CONNECTIONS="${WRK_CONNECTIONS:-50}"
RESOURCE_SAMPLE_INTERVAL_SECONDS="${RESOURCE_SAMPLE_INTERVAL_SECONDS:-1}"

MODE="${1:-smoke}"
SERVER_DIR_ABS="$(cd "${ANALYTICS_DIR}/${SERVER_DIR}" && pwd)"
TARGET_URL="http://127.0.0.1:${HOST_PORT}${TARGET_PATH}"
RAW_DIR="${ANALYTICS_DIR}/data/raw"
CHECK_SCRIPT="${ANALYTICS_DIR}/scripts/check_server_untouched.sh"
CONTAINER_STARTED="0"
RUN_FAILURES="0"

usage() {
    cat <<'EOF'
Usage: ./loadtest/run_experiments.sh [smoke|full]

smoke  Runs one short validation workload. This is the default.
full   Runs configured repeated workloads from config.env.
EOF
}

cleanup() {
    exit_code=$?
    set +e

    if [ "${CONTAINER_STARTED}" = "1" ]; then
        docker rm -f "${SERVER_CONTAINER_NAME}" >/dev/null 2>&1
    fi

    "${CHECK_SCRIPT}" --check
    check_code=$?

    if [ "${exit_code}" -eq 0 ] && [ "${check_code}" -ne 0 ]; then
        exit "${check_code}"
    fi

    exit "${exit_code}"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        exit 1
    fi
}

resolve_wrk2() {
    local candidate="${ANALYTICS_DIR}/${WRK2_BIN}"

    if [ -x "${candidate}" ]; then
        echo "${candidate}"
        return
    fi

    if command -v wrk >/dev/null 2>&1; then
        candidate="$(command -v wrk)"
        if "${candidate}" --help 2>&1 | grep -q -- "-R"; then
            echo "${candidate}"
            return
        fi
    fi

    echo "wrk2 was not found. Run ./loadtest/setup_wrk2.sh first." >&2
    exit 1
}

wait_for_server() {
    local attempts=40
    local i

    for i in $(seq 1 "${attempts}"); do
        if curl --fail --silent --show-error --max-time 2 "${TARGET_URL}" >/dev/null; then
            return 0
        fi
        sleep 0.5
    done

    echo "Server did not respond at ${TARGET_URL}" >&2
    docker logs "${SERVER_CONTAINER_NAME}" >&2 || true
    return 1
}

write_metadata() {
    local file="$1"
    local run_id="$2"
    local rate="$3"
    local repeat="$4"
    local duration="$5"
    local start_time="$6"
    local end_time="$7"
    local wrk_exit_code="$8"
    local server_commit="$9"

    {
        printf 'run_id=%s\n' "${run_id}"
        printf 'mode=%s\n' "${MODE}"
        printf 'workload_name=%s\n' "${WORKLOAD_NAME}"
        printf 'requested_rate=%s\n' "${rate}"
        printf 'repeat=%s\n' "${repeat}"
        printf 'duration_seconds=%s\n' "${duration}"
        printf 'wrk_threads=%s\n' "${WRK_THREADS}"
        printf 'wrk_connections=%s\n' "${WRK_CONNECTIONS}"
        printf 'server_workers=%s\n' "${SERVER_WORKERS}"
        printf 'target_url=%s\n' "${TARGET_URL}"
        printf 'started_at=%s\n' "${start_time}"
        printf 'ended_at=%s\n' "${end_time}"
        printf 'wrk_exit_code=%s\n' "${wrk_exit_code}"
        printf 'server_commit=%s\n' "${server_commit}"
        printf 'server_image=%s\n' "${SERVER_IMAGE}"
        printf 'container_name=%s\n' "${SERVER_CONTAINER_NAME}"
    } > "${file}"
}

sample_resources() {
    local run_id="$1"
    local output_file="$2"

    printf 'run_id,timestamp,cpu_percent,mem_usage,mem_limit\n' > "${output_file}"

    while true; do
        local timestamp
        local stats
        local cpu
        local mem
        local mem_usage
        local mem_limit

        timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        stats="$(docker stats "${SERVER_CONTAINER_NAME}" --no-stream --format '{{.CPUPerc}},{{.MemUsage}}' 2>/dev/null || true)"

        if [ -n "${stats}" ]; then
            cpu="${stats%%,*}"
            mem="${stats#*,}"
            mem_usage="${mem%% / *}"
            mem_limit="${mem##* / }"
            printf '%s,%s,%s,%s,%s\n' "${run_id}" "${timestamp}" "${cpu%%%}" "${mem_usage}" "${mem_limit}" >> "${output_file}"
        fi

        sleep "${RESOURCE_SAMPLE_INTERVAL_SECONDS}"
    done
}

run_one() {
    local wrk2="$1"
    local rate="$2"
    local repeat="$3"
    local duration="$4"
    local server_commit="$5"
    local timestamp
    local run_id
    local run_dir
    local start_time
    local end_time
    local wrk_exit_code
    local sampler_pid

    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    run_id="${timestamp}_${MODE}_rate${rate}_rep${repeat}"
    run_dir="${RAW_DIR}/${run_id}"
    mkdir -p "${run_dir}"

    echo "Running ${run_id} against ${TARGET_URL}"
    start_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    sample_resources "${run_id}" "${run_dir}/resources.csv" &
    sampler_pid=$!

    set +e
    timeout "$((duration + 30))s" "${wrk2}" \
        -t"${WRK_THREADS}" \
        -c"${WRK_CONNECTIONS}" \
        -d"${duration}s" \
        -R"${rate}" \
        --latency \
        "${TARGET_URL}" > "${run_dir}/wrk.txt" 2>&1
    wrk_exit_code=$?
    set -e

    kill "${sampler_pid}" >/dev/null 2>&1 || true
    wait "${sampler_pid}" >/dev/null 2>&1 || true

    end_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    write_metadata "${run_dir}/metadata.env" "${run_id}" "${rate}" "${repeat}" "${duration}" "${start_time}" "${end_time}" "${wrk_exit_code}" "${server_commit}"

    if [ "${wrk_exit_code}" -ne 0 ]; then
        echo "wrk2 exited with ${wrk_exit_code}; raw output kept in ${run_dir}/wrk.txt" >&2
        RUN_FAILURES=$((RUN_FAILURES + 1))
    fi
}

case "${MODE}" in
    smoke)
        SELECTED_RATES="${SMOKE_RATE}"
        SELECTED_REPEATS="1"
        SELECTED_DURATION="${SMOKE_DURATION_SECONDS}"
        ;;
    full)
        SELECTED_RATES="${RATES}"
        SELECTED_REPEATS="${REPEATS}"
        SELECTED_DURATION="${FULL_DURATION_SECONDS}"
        ;;
    -h|--help|help)
        usage
        exit 0
        ;;
    *)
        usage
        exit 2
        ;;
esac

require_command docker
require_command curl
require_command timeout
WRK2_PATH="$(resolve_wrk2)"

mkdir -p "${RAW_DIR}"
"${CHECK_SCRIPT}" --init
SERVER_COMMIT="$(git -C "${SERVER_DIR_ABS}" rev-parse HEAD)"

echo "Building server image ${SERVER_IMAGE} from read-only named context ${SERVER_DIR_ABS}"
DOCKER_BUILDKIT=1 docker build \
    --file "${ANALYTICS_DIR}/docker/Dockerfile" \
    --build-context "server=${SERVER_DIR_ABS}" \
    --tag "${SERVER_IMAGE}" \
    "${ANALYTICS_DIR}"

docker rm -f "${SERVER_CONTAINER_NAME}" >/dev/null 2>&1 || true
docker run \
    --rm \
    --detach \
    --name "${SERVER_CONTAINER_NAME}" \
    --publish "127.0.0.1:${HOST_PORT}:${SERVER_PORT}" \
    "${SERVER_IMAGE}" \
    "${SERVER_PORT}" \
    "${SERVER_ROOT}" \
    "${SERVER_WORKERS}" >/dev/null
CONTAINER_STARTED="1"

wait_for_server

for rate in ${SELECTED_RATES}; do
    repeat=1
    while [ "${repeat}" -le "${SELECTED_REPEATS}" ]; do
        run_one "${WRK2_PATH}" "${rate}" "${repeat}" "${SELECTED_DURATION}" "${SERVER_COMMIT}"
        repeat=$((repeat + 1))
    done
done

echo "Raw results are in ${RAW_DIR}"
echo "Next: python3 analysis/parse_results.py && python3 analysis/explore_data.py && python3 analysis/performance_analysis.py"

if [ "${RUN_FAILURES}" -ne 0 ]; then
    echo "${RUN_FAILURES} wrk2 run(s) exited nonzero; parse raw output before trusting the experiment." >&2
    exit 1
fi

