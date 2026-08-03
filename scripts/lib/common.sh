#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

set -a
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/configs/versions.env"
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/configs/profiles.env"
set +a

log() {
  printf '[pipeline] %s\n' "$*"
}

fail() {
  printf '[pipeline] error: %s\n' "$*" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command is missing: $1"
}

conda_executable() {
  local marker="${PROJECT_ROOT}/.cache/tools/conda-path"
  if [[ -f "${marker}" ]] && [[ -x "$(<"${marker}")" ]]; then
    cat "${marker}"
  elif command -v conda >/dev/null 2>&1; then
    command -v conda
  elif [[ -x /opt/conda/bin/conda ]]; then
    printf '%s\n' /opt/conda/bin/conda
  else
    fail "Conda was not found. Use the documented RunPod PyTorch image."
  fi
}

uv_executable() {
  local marker="${PROJECT_ROOT}/.cache/tools/uv-path"
  if [[ -f "${marker}" ]] && [[ -x "$(<"${marker}")" ]]; then
    cat "${marker}"
  elif command -v uv >/dev/null 2>&1; then
    command -v uv
  else
    fail "uv was not found. Run scripts/bootstrap_host.sh first."
  fi
}

uvx_executable() {
  local uv_path
  uv_path="$(uv_executable)"
  local uvx_path="$(dirname "${uv_path}")/uvx"
  [[ -x "${uvx_path}" ]] || fail "uvx was not found next to ${uv_path}"
  printf '%s\n' "${uvx_path}"
}

ensure_checkout() {
  local repository="$1"
  local tag="$2"
  local commit="$3"
  local destination="$4"

  if [[ ! -d "${destination}/.git" ]]; then
    mkdir -p "$(dirname "${destination}")"
    log "Cloning ${repository} at ${tag}"
    git clone --branch "${tag}" --depth 1 "${repository}" "${destination}"
  fi

  local actual
  actual="$(git -C "${destination}" rev-parse HEAD)"
  if [[ "${actual}" != "${commit}" ]]; then
    log "Refreshing checkout to exact commit ${commit}"
    git -C "${destination}" fetch --depth 1 origin "${commit}"
    git -C "${destination}" checkout --detach "${commit}"
    actual="$(git -C "${destination}" rev-parse HEAD)"
  fi
  [[ "${actual}" == "${commit}" ]] || fail "Revision verification failed in ${destination}"
}

checkpoint_step_from_path() {
  local filename="${1##*/}"
  [[ "${filename}" =~ ^step-([0-9]+)\.ckpt$ ]] || return 1
  printf '%d\n' "$((10#${BASH_REMATCH[1]}))"
}

remaining_training_steps() {
  local target_steps="$1"
  local checkpoint_steps="$2"
  [[ "${target_steps}" =~ ^[0-9]+$ ]] || fail "Invalid target step count: ${target_steps}"
  [[ "${checkpoint_steps}" =~ ^[0-9]+$ ]] || fail "Invalid checkpoint step count: ${checkpoint_steps}"

  if (( checkpoint_steps >= target_steps )); then
    printf '0\n'
  else
    printf '%d\n' "$((target_steps - checkpoint_steps))"
  fi
}
