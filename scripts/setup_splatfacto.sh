#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

require_command git
require_command nvidia-smi
CONDA_EXE="$(conda_executable)"
UV_EXE="$(uv_executable)"
export UV_CACHE_DIR="${PROJECT_ROOT}/.cache/tools/uv-cache"

if [[ -z "${TORCH_CUDA_ARCH_LIST:-}" ]]; then
  TORCH_CUDA_ARCH_LIST="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -n 1 | tr -d '[:space:]')"
  [[ "${TORCH_CUDA_ARCH_LIST}" =~ ^[0-9]+\.[0-9]+$ ]] \
    || fail "Could not determine a CUDA compute capability with nvidia-smi"
  export TORCH_CUDA_ARCH_LIST
fi

ensure_checkout "${NERFSTUDIO_REPOSITORY}" "${NERFSTUDIO_TAG}" "${NERFSTUDIO_COMMIT}" "${NERFSTUDIO_DIR}"

if [[ ! -x "${SPLAT_CONDA_PREFIX}/bin/python" ]]; then
  log "Creating isolated Splatfacto Python ${SPLAT_PYTHON_VERSION} environment"
  "${CONDA_EXE}" create --prefix "${SPLAT_CONDA_PREFIX}" \
    "python=${SPLAT_PYTHON_VERSION}" ninja --yes
fi

log "Installing the minimal CUDA ${SPLAT_CUDA_VERSION} compiler set for gsplat"
"${CONDA_EXE}" install --prefix "${SPLAT_CONDA_PREFIX}" \
  --channel "nvidia/label/cuda-${SPLAT_CUDA_VERSION}.0" \
  --channel conda-forge \
  "cuda-nvcc=${SPLAT_CUDA_VERSION}" \
  "cuda-cudart-dev=${SPLAT_CUDA_VERSION}" \
  "gcc_linux-64=11.4.0" \
  "gxx_linux-64=11.4.0" \
  --yes

export CUDA_HOME="${SPLAT_CONDA_PREFIX}"
export CC="${SPLAT_CONDA_PREFIX}/bin/x86_64-conda-linux-gnu-cc"
export CXX="${SPLAT_CONDA_PREFIX}/bin/x86_64-conda-linux-gnu-c++"
export CUDAHOSTCXX="${CXX}"
export TORCH_EXTENSIONS_DIR="${PROJECT_ROOT}/.cache/torch-extensions/splatfacto"
mkdir -p "${TORCH_EXTENSIONS_DIR}"
[[ -x "${CC}" && -x "${CXX}" ]] \
  || fail "Pinned GCC/G++ 11 compiler wrappers are missing from the Splatfacto environment"
log "Building gsplat CUDA extensions for compute capability ${TORCH_CUDA_ARCH_LIST}"

log "Installing pinned Python compatibility packages from PyPI"
"${UV_EXE}" pip install --python "${SPLAT_CONDA_PREFIX}/bin/python" \
  "numpy==${SPLAT_NUMPY_VERSION}" \
  "setuptools==${SPLAT_SETUPTOOLS_VERSION}"

log "Installing the pinned PyTorch CUDA stack"
"${UV_EXE}" pip install --python "${SPLAT_CONDA_PREFIX}/bin/python" \
  "torch==${SPLAT_TORCH_VERSION}+cu118" \
  "torchvision==${SPLAT_TORCHVISION_VERSION}+cu118" \
  --extra-index-url https://download.pytorch.org/whl/cu118

log "Installing Nerfstudio ${NERFSTUDIO_TAG} and gsplat from the verified checkout"
"${UV_EXE}" pip install --python "${SPLAT_CONDA_PREFIX}/bin/python" \
  --editable "${NERFSTUDIO_DIR}"

"${CONDA_EXE}" run --no-capture-output --prefix "${SPLAT_CONDA_PREFIX}" \
  python -c \
  'import gsplat, nerfstudio, torch; from gsplat.cuda._backend import _C; assert torch.cuda.is_available(); print("Splatfacto CUDA environment ready:", torch.__version__)'
