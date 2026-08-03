#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${RUNPOD_ENV_FILE:-${PROJECT_ROOT}/.env.runpod}"

fail() {
  printf '[runpod] error: %s\n' "$*" >&2
  exit 2
}

log() {
  printf '[runpod] %s\n' "$*"
}

for command in git python3 rsync runpodctl ssh; do
  command -v "${command}" >/dev/null 2>&1 || fail "Required command is missing: ${command}"
done

[[ -f "${CONFIG_FILE}" ]] || fail \
  "Missing ${CONFIG_FILE}. Copy .env.runpod.example to .env.runpod and add RUNPOD_API_KEY."
set -a
# shellcheck disable=SC1090
source "${CONFIG_FILE}"
set +a

[[ -n "${RUNPOD_API_KEY:-}" ]] || fail "RUNPOD_API_KEY is empty in ${CONFIG_FILE}"
export RUNPOD_API_KEY

PROFILE="${PROFILE:-quality}"
[[ "${PROFILE}" == smoke || "${PROFILE}" == quality ]] \
  || fail "PROFILE must be smoke or quality"
RUNPOD_GPU_ID="${RUNPOD_GPU_ID:-NVIDIA GeForce RTX 4090}"
RUNPOD_CLOUD_TYPE="${RUNPOD_CLOUD_TYPE:-SECURE}"
RUNPOD_IMAGE="${RUNPOD_IMAGE:-runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404}"
RUNPOD_CONTAINER_DISK_GB="${RUNPOD_CONTAINER_DISK_GB:-20}"
RUNPOD_VOLUME_GB="${RUNPOD_VOLUME_GB:-50}"
RUNPOD_VOLUME_MOUNT_PATH="${RUNPOD_VOLUME_MOUNT_PATH:-/workspace}"
RUNPOD_MAX_HOURS="${RUNPOD_MAX_HOURS:-4}"
RUNPOD_TERMINATE_AFTER_HOURS="${RUNPOD_TERMINATE_AFTER_HOURS:-24}"
RUNPOD_AUTO_CONFIRM="${RUNPOD_AUTO_CONFIRM:-false}"
RUNPOD_KEEP_POD="${RUNPOD_KEEP_POD:-false}"
RUNPOD_DELETE_ON_FAILURE="${RUNPOD_DELETE_ON_FAILURE:-false}"
RUNPOD_DRY_RUN="${RUNPOD_DRY_RUN:-false}"
RUNPOD_POLL_SECONDS="${RUNPOD_POLL_SECONDS:-30}"

for value in RUNPOD_CONTAINER_DISK_GB RUNPOD_VOLUME_GB RUNPOD_MAX_HOURS RUNPOD_TERMINATE_AFTER_HOURS RUNPOD_POLL_SECONDS; do
  [[ "${!value}" =~ ^[1-9][0-9]*$ ]] || fail "${value} must be a positive integer"
done
(( RUNPOD_TERMINATE_AFTER_HOURS > RUNPOD_MAX_HOURS )) \
  || fail "RUNPOD_TERMINATE_AFTER_HOURS must exceed RUNPOD_MAX_HOURS"

cd "${PROJECT_ROOT}"
[[ -z "$(git status --porcelain)" ]] \
  || fail "The worktree must be clean so the remote run matches a published commit"
REVISION="$(git rev-parse HEAD)"
UPSTREAM_REVISION="$(git rev-parse '@{upstream}' 2>/dev/null)" \
  || fail "The current branch has no upstream; push it before launching RunPod"
[[ "${REVISION}" == "${UPSTREAM_REVISION}" ]] \
  || fail "The current commit is not pushed to its upstream branch"
REPOSITORY_URL="$(git remote get-url origin)"
if [[ "${REPOSITORY_URL}" == git@github.com:* ]]; then
  REPOSITORY_URL="https://github.com/${REPOSITORY_URL#git@github.com:}"
fi
[[ "${REPOSITORY_URL}" == https://github.com/* ]] \
  || fail "The cloud launcher requires a public GitHub HTTPS origin"

STOP_AFTER="$(python3 -c \
  'from datetime import datetime, timedelta, timezone; import sys; print((datetime.now(timezone.utc) + timedelta(hours=int(sys.argv[1]))).strftime("%Y-%m-%dT%H:%M:%SZ"))' \
  "${RUNPOD_MAX_HOURS}")"
TERMINATE_AFTER="$(python3 -c \
  'from datetime import datetime, timedelta, timezone; import sys; print((datetime.now(timezone.utc) + timedelta(hours=int(sys.argv[1]))).strftime("%Y-%m-%dT%H:%M:%SZ"))' \
  "${RUNPOD_TERMINATE_AFTER_HOURS}")"

log "Profile: ${PROFILE}"
log "Repository revision: ${REVISION}"
log "GPU: ${RUNPOD_GPU_ID} (${RUNPOD_CLOUD_TYPE})"
log "Image: ${RUNPOD_IMAGE}"
log "Storage: ${RUNPOD_CONTAINER_DISK_GB} GB container + ${RUNPOD_VOLUME_GB} GB at ${RUNPOD_VOLUME_MOUNT_PATH}"
log "Hard stop: ${STOP_AFTER}; hard termination: ${TERMINATE_AFTER}"

if [[ "${RUNPOD_DRY_RUN}" == true ]]; then
  log "Dry run complete; no paid resource was created"
  exit 0
fi

ACCOUNT_JSON="$(runpodctl user -o json)"
BALANCE="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("clientBalance", "unknown"))' <<<"${ACCOUNT_JSON}")"
log "Current RunPod balance: ${BALANCE}"
if [[ "${RUNPOD_AUTO_CONFIRM}" != true ]]; then
  [[ -t 0 ]] || fail "Set RUNPOD_AUTO_CONFIRM=true for a non-interactive launch"
  read -r -p "Create this paid RunPod resource? [y/N] " confirmation
  [[ "${confirmation}" == y || "${confirmation}" == Y ]] || fail "Launch cancelled"
fi

CREATE_ARGS=(
  pod create
  --name "vipe-gs-${PROFILE}"
  --image "${RUNPOD_IMAGE}"
  --gpu-id "${RUNPOD_GPU_ID}"
  --gpu-count 1
  --cloud-type "${RUNPOD_CLOUD_TYPE}"
  --container-disk-in-gb "${RUNPOD_CONTAINER_DISK_GB}"
  --volume-in-gb "${RUNPOD_VOLUME_GB}"
  --volume-mount-path "${RUNPOD_VOLUME_MOUNT_PATH}"
  --ports "22/tcp,8888/http"
  --ssh
  --stop-after "${STOP_AFTER}"
  --terminate-after "${TERMINATE_AFTER}"
  -o json
)
[[ -n "${RUNPOD_COUNTRY_CODE:-}" ]] && CREATE_ARGS+=(--country-code "${RUNPOD_COUNTRY_CODE}")
[[ -n "${RUNPOD_DATA_CENTER_IDS:-}" ]] && CREATE_ARGS+=(--data-center-ids "${RUNPOD_DATA_CENTER_IDS}")
[[ "${RUNPOD_CLOUD_TYPE}" == COMMUNITY ]] && CREATE_ARGS+=(--public-ip)

POD_ID=""
RUN_SUCCEEDED=false
CLEANUP_STARTED=false
STATE_DIR="${PROJECT_ROOT}/.runpod"
mkdir -p "${STATE_DIR}"

delete_pod_and_wait() {
  local pod_id="$1"
  local deleted=false
  for attempt in 1 2 3 4 5; do
    if runpodctl pod delete "${pod_id}" >/dev/null 2>&1; then
      deleted=true
      break
    fi
    log "Pod deletion attempt ${attempt}/5 failed for ${pod_id}"
    sleep $((attempt * 2))
  done
  [[ "${deleted}" == true ]] || return 1
  for _ in $(seq 1 30); do
    if ! runpodctl pod get "${pod_id}" -o json >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

cleanup() {
  exit_code=$?
  [[ "${CLEANUP_STARTED}" == false ]] || return
  CLEANUP_STARTED=true
  trap - EXIT INT TERM
  if [[ -n "${POD_ID}" ]]; then
    if [[ "${RUN_SUCCEEDED}" == true && "${RUNPOD_KEEP_POD}" != true ]] \
      || [[ "${RUN_SUCCEEDED}" != true && "${RUNPOD_DELETE_ON_FAILURE}" == true ]]; then
      log "Deleting Pod ${POD_ID} and its Pod volume"
      if delete_pod_and_wait "${POD_ID}"; then
        rm -f "${STATE_DIR}/active.env"
        log "Confirmed Pod ${POD_ID} no longer exists"
      else
        log "Deletion confirmation failed; stopping ${POD_ID}. The provider termination deadline remains active."
        runpodctl pod stop "${POD_ID}" >/dev/null || true
      fi
    else
      log "Stopping Pod ${POD_ID}"
      runpodctl pod stop "${POD_ID}" >/dev/null || true
      log "Retained Pod state: ${STATE_DIR}/active.env"
    fi
  fi
  exit "${exit_code}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

log "Creating RunPod"
CREATE_JSON="$(runpodctl "${CREATE_ARGS[@]}")"
POD_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"${CREATE_JSON}")"
HOURLY_RATE="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("costPerHr", "unknown"))' <<<"${CREATE_JSON}")"
printf 'POD_ID=%q\n' "${POD_ID}" > "${STATE_DIR}/active.env"
printf 'PROFILE=%q\n' "${PROFILE}" >> "${STATE_DIR}/active.env"
log "Created Pod ${POD_ID} at ${HOURLY_RATE}/hour"

POD_JSON=""
SSH_IP=""
SSH_PORT=""
SSH_KEY="${RUNPOD_SSH_KEY:-}"
for attempt in $(seq 1 90); do
  POD_JSON="$(runpodctl pod get "${POD_ID}" -o json 2>/dev/null || true)"
  if [[ -n "${POD_JSON}" ]]; then
    SSH_IP="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("ssh", {}).get("ip", ""))' <<<"${POD_JSON}")"
    SSH_PORT="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("ssh", {}).get("port", ""))' <<<"${POD_JSON}")"
    if [[ -z "${SSH_KEY}" ]]; then
      SSH_KEY="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("ssh", {}).get("ssh_key", {}).get("path", ""))' <<<"${POD_JSON}")"
    fi
  fi
  if [[ -n "${SSH_IP}" && -n "${SSH_PORT}" && -f "${SSH_KEY}" ]]; then
    if ssh -i "${SSH_KEY}" -p "${SSH_PORT}" \
      -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
      "root@${SSH_IP}" true 2>/dev/null; then
      break
    fi
  fi
  (( attempt < 90 )) || fail "Pod did not expose a usable SSH endpoint within 7.5 minutes"
  sleep 5
done

SSH_ARGS=(
  -i "${SSH_KEY}"
  -p "${SSH_PORT}"
  -o BatchMode=yes
  -o StrictHostKeyChecking=accept-new
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=10
)
REMOTE_ROOT="${RUNPOD_VOLUME_MOUNT_PATH}/vipe-gaussian-splatting-demo"
printf -v QUOTED_REPOSITORY '%q' "${REPOSITORY_URL}"
printf -v QUOTED_REVISION '%q' "${REVISION}"
printf -v QUOTED_ROOT '%q' "${REMOTE_ROOT}"
printf -v QUOTED_PROFILE '%q' "${PROFILE}"
REMOTE_JOB_DIR="${REMOTE_ROOT}/.runpod-job"
printf -v QUOTED_JOB_DIR '%q' "${REMOTE_JOB_DIR}"

log "Cloning the public repository and checking out ${REVISION}"
ssh "${SSH_ARGS[@]}" "root@${SSH_IP}" \
  "git clone ${QUOTED_REPOSITORY} ${QUOTED_ROOT} && git -C ${QUOTED_ROOT} checkout --detach ${QUOTED_REVISION}"

LOCAL_LOG_DIR="${PROJECT_ROOT}/artifacts/runpod"
mkdir -p "${LOCAL_LOG_DIR}"
RSYNC_SHELL="ssh -i ${SSH_KEY} -p ${SSH_PORT} -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
log "Starting the documented pipeline as a reconnectable remote job"
ssh "${SSH_ARGS[@]}" "root@${SSH_IP}" \
  "mkdir -p ${QUOTED_JOB_DIR}; nohup bash ${QUOTED_ROOT}/scripts/run_remote_pipeline.sh ${QUOTED_ROOT} ${QUOTED_PROFILE} ${QUOTED_JOB_DIR} > ${QUOTED_JOB_DIR}/pipeline.log 2>&1 < /dev/null & printf '%s\\n' \$! > ${QUOTED_JOB_DIR}/pid"

MAX_POLLS=$((RUNPOD_MAX_HOURS * 3600 / RUNPOD_POLL_SECONDS + 20))
REMOTE_EXIT_CODE=""
LAST_PROGRESS=""
for poll in $(seq 1 "${MAX_POLLS}"); do
  REMOTE_EXIT_CODE="$(ssh "${SSH_ARGS[@]}" "root@${SSH_IP}" \
    "test -f ${QUOTED_JOB_DIR}/exit-code && cat ${QUOTED_JOB_DIR}/exit-code" \
    2>/dev/null || true)"
  PROGRESS="$(ssh "${SSH_ARGS[@]}" "root@${SSH_IP}" \
    "test -f ${QUOTED_JOB_DIR}/pipeline.log && grep -E '^\\[(RUN|RESUME)|^\\[pipeline\\]|^Pipeline complete' ${QUOTED_JOB_DIR}/pipeline.log | tail -n 1" \
    2>/dev/null || true)"
  if [[ -n "${PROGRESS}" && "${PROGRESS}" != "${LAST_PROGRESS}" ]]; then
    log "Remote progress: ${PROGRESS}"
    LAST_PROGRESS="${PROGRESS}"
  fi
  [[ -z "${REMOTE_EXIT_CODE}" ]] || break
  if (( poll % 20 == 0 )); then
    log "Remote pipeline is still running (poll ${poll}/${MAX_POLLS})"
  fi
  sleep "${RUNPOD_POLL_SECONDS}"
done

rsync -az --no-owner --no-group -e "${RSYNC_SHELL}" \
  "root@${SSH_IP}:${REMOTE_JOB_DIR}/pipeline.log" \
  "${LOCAL_LOG_DIR}/${POD_ID}.log" || true
[[ -n "${REMOTE_EXIT_CODE}" ]] || fail "Remote pipeline did not publish an exit code before the compute deadline"
[[ "${REMOTE_EXIT_CODE}" == 0 ]] || fail \
  "Remote pipeline failed with exit code ${REMOTE_EXIT_CODE}; log: ${LOCAL_LOG_DIR}/${POD_ID}.log"

mkdir -p "${PROJECT_ROOT}/artifacts/${PROFILE}" "${PROJECT_ROOT}/runs/${PROFILE}"
log "Downloading deliverables and diagnostic records"
rsync -az --no-owner --no-group -e "${RSYNC_SHELL}" \
  "root@${SSH_IP}:${REMOTE_ROOT}/artifacts/${PROFILE}/" \
  "${PROJECT_ROOT}/artifacts/${PROFILE}/"
rsync -az --no-owner --no-group -e "${RSYNC_SHELL}" \
  "root@${SSH_IP}:${REMOTE_ROOT}/runs/${PROFILE}/logs/" \
  "${PROJECT_ROOT}/runs/${PROFILE}/logs/"
rsync -az --no-owner --no-group -e "${RSYNC_SHELL}" \
  "root@${SSH_IP}:${REMOTE_ROOT}/runs/${PROFILE}/.pipeline/" \
  "${PROJECT_ROOT}/runs/${PROFILE}/.pipeline/"

PYTHONPATH="${PROJECT_ROOT}/src" python3 -m vipe_demo verify-artifacts --profile "${PROFILE}"
RUN_SUCCEEDED=true
log "RunPod pipeline and local artifact verification completed successfully"
