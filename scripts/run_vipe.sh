#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

CONDA_EXE="$(conda_executable)"
[[ -f "${VIDEO_PATH}" ]] || fail "Prepared video does not exist: ${VIDEO_PATH}"
[[ -x "${VIPE_DIR}/.venv/bin/python" ]] || fail "ViPE is not installed; run setup_vipe first"
mkdir -p "${VIPE_OUTPUT_DIR}"

log "Running ViPE ${VIPE_TAG} on ${FRAME_COUNT} frames with SLAM buffer ${SLAM_BUFFER}"
"${CONDA_EXE}" run --no-capture-output --prefix "${VIPE_CONDA_PREFIX}" \
  uv run --project "${VIPE_DIR}" python "${VIPE_DIR}/run.py" \
  pipeline=default \
  streams=raw_mp4_stream \
  "streams.base_path=${VIDEO_PATH}" \
  "streams.frame_end=${FRAME_COUNT}" \
  "pipeline.slam.buffer=${SLAM_BUFFER}" \
  pipeline.init.prefetch_queue_size=4 \
  "pipeline.output.path=${VIPE_OUTPUT_DIR}" \
  pipeline.output.skip_exists=false \
  pipeline.output.save_artifacts=true \
  pipeline.output.save_slam_map=true \
  pipeline.output.save_viz=false

find "${VIPE_OUTPUT_DIR}" -type f -print -quit | grep -q . || fail "ViPE produced no files"
