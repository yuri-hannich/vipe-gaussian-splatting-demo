#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

CONDA_EXE="$(conda_executable)"
TEMP_PARENT="$(mktemp -d "${RUN_ROOT}/.colmap-export.XXXXXX")"
TARGET_PARENT="$(dirname "${COLMAP_ROOT}")"
mkdir -p "${TARGET_PARENT}"

log "Exporting ViPE geometry with its version-matched COLMAP converter"
"${CONDA_EXE}" run --no-capture-output --prefix "${VIPE_CONDA_PREFIX}" \
  uv run --project "${VIPE_DIR}" python "${VIPE_DIR}/scripts/vipe_to_colmap.py" \
  "${VIPE_OUTPUT_DIR}" \
  --sequence "${SEQUENCE_NAME}" \
  --output "${TEMP_PARENT}" \
  --use_slam_map

TEMP_RESULT="${TEMP_PARENT}/${SEQUENCE_NAME}"
[[ -d "${TEMP_RESULT}" ]] || fail "ViPE converter did not create ${TEMP_RESULT}"
if [[ -e "${COLMAP_ROOT}" ]]; then
  REPLACED_PATH="${COLMAP_ROOT}.replaced.$(date +%Y%m%d%H%M%S)"
  log "Preserving the previous generated export at ${REPLACED_PATH}"
  mv "${COLMAP_ROOT}" "${REPLACED_PATH}"
fi
mv "${TEMP_RESULT}" "${COLMAP_ROOT}"
rmdir "${TEMP_PARENT}"
