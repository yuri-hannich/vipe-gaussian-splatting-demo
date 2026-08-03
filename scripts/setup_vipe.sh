#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

require_command git
require_command nvidia-smi
CONDA_EXE="$(conda_executable)"

ensure_checkout "${VIPE_REPOSITORY}" "${VIPE_TAG}" "${VIPE_COMMIT}" "${VIPE_DIR}"

VIPE_PYTHON_VERSION="$(tr -d '[:space:]' < "${VIPE_DIR}/.python-version")"
[[ -n "${VIPE_PYTHON_VERSION}" ]] || fail "ViPE's .python-version is empty"
export UV_PYTHON_INSTALL_DIR="${PROJECT_ROOT}/.cache/tools/uv-python"
export UV_CACHE_DIR="${PROJECT_ROOT}/.cache/tools/uv-cache"

if [[ -z "${TORCH_CUDA_ARCH_LIST:-}" ]]; then
  TORCH_CUDA_ARCH_LIST="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -n 1 | tr -d '[:space:]')"
  [[ "${TORCH_CUDA_ARCH_LIST}" =~ ^[0-9]+\.[0-9]+$ ]] \
    || fail "Could not determine a CUDA compute capability with nvidia-smi"
  export TORCH_CUDA_ARCH_LIST
fi
log "Building ViPE CUDA extensions for compute capability ${TORCH_CUDA_ARCH_LIST}"

if [[ ! -x "${VIPE_CONDA_PREFIX}/bin/uv" ]]; then
  log "Creating ViPE CUDA 12.8 build environment"
  "${CONDA_EXE}" env create --prefix "${VIPE_CONDA_PREFIX}" --file "${VIPE_DIR}/envs/cu128.yml" --yes
else
  log "Updating the existing ViPE build environment from the pinned upstream specification"
  "${CONDA_EXE}" env update --prefix "${VIPE_CONDA_PREFIX}" --file "${VIPE_DIR}/envs/cu128.yml" --prune
fi

log "Installing ViPE's pinned managed Python ${VIPE_PYTHON_VERSION}"
"${CONDA_EXE}" run --no-capture-output --prefix "${VIPE_CONDA_PREFIX}" \
  uv python install --managed-python --no-bin "${VIPE_PYTHON_VERSION}"

log "Synchronizing ViPE's exact uv lock"
"${CONDA_EXE}" run --no-capture-output --prefix "${VIPE_CONDA_PREFIX}" \
  uv sync --frozen --managed-python --python "${VIPE_PYTHON_VERSION}" --project "${VIPE_DIR}"

log "Verifying ViPE, PyTorch, and CUDA"
"${CONDA_EXE}" run --no-capture-output --prefix "${VIPE_CONDA_PREFIX}" \
  uv run --project "${VIPE_DIR}" python -c \
  'import torch, vipe; assert torch.cuda.is_available(); print("ViPE CUDA environment ready:", torch.__version__)'
