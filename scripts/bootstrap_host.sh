#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

[[ "$(uname -s)" == Linux ]] || fail "The CUDA pipeline requires Linux"
for command in git curl ffmpeg ffprobe nvidia-smi make g++ sha256sum unzip; do
  require_command "${command}"
done

TOOLS_DIR="${PROJECT_ROOT}/.cache/tools"
MARKER="${TOOLS_DIR}/conda-path"
mkdir -p "${TOOLS_DIR}"

if command -v conda >/dev/null 2>&1; then
  command -v conda > "${MARKER}"
  log "Using the Conda installation provided by the RunPod image"
else
  MINIFORGE_PREFIX="${TOOLS_DIR}/miniforge"
  if [[ ! -x "${MINIFORGE_PREFIX}/bin/conda" ]]; then
    INSTALLER="$(mktemp /tmp/vipe-miniforge.XXXXXX.sh)"
    trap 'rm -f "${INSTALLER}"' EXIT
    URL="https://github.com/conda-forge/miniforge/releases/download/${MINIFORGE_VERSION}/Miniforge3-${MINIFORGE_VERSION}-Linux-x86_64.sh"
    log "Downloading pinned Miniforge ${MINIFORGE_VERSION}"
    curl -fsSL "${URL}" --output "${INSTALLER}"
    printf '%s  %s\n' "${MINIFORGE_SHA256}" "${INSTALLER}" | sha256sum --check --status \
      || fail "Miniforge installer checksum mismatch"
    bash "${INSTALLER}" -b -p "${MINIFORGE_PREFIX}"
  fi
  printf '%s\n' "${MINIFORGE_PREFIX}/bin/conda" > "${MARKER}"
fi

CONDA_EXE="$(conda_executable)"
"${CONDA_EXE}" --version

UV_MARKER="${TOOLS_DIR}/uv-path"
if command -v uv >/dev/null 2>&1 && command -v uvx >/dev/null 2>&1; then
  command -v uv > "${UV_MARKER}"
  log "Using the uv installation provided by the host"
else
  UV_PREFIX="${TOOLS_DIR}/uv"
  if [[ ! -x "${UV_PREFIX}/bin/uv" ]]; then
    log "Installing pinned uv ${UV_VERSION} bootstrap tooling"
    "${CONDA_EXE}" create --prefix "${UV_PREFIX}" --channel conda-forge \
      "uv=${UV_VERSION}" --yes
  fi
  printf '%s\n' "${UV_PREFIX}/bin/uv" > "${UV_MARKER}"
fi

"$(uv_executable)" --version
