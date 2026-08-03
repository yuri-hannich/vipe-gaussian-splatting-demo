#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

CONDA_EXE="$(conda_executable)"
ACTION="${1:-}"
[[ -n "${ACTION}" ]] || fail "Expected action: train, evaluate, export, or render"

run_ns() {
  CUDA_HOME="${SPLAT_CONDA_PREFIX}" \
  CC="${SPLAT_CONDA_PREFIX}/bin/x86_64-conda-linux-gnu-cc" \
  CXX="${SPLAT_CONDA_PREFIX}/bin/x86_64-conda-linux-gnu-c++" \
  CUDAHOSTCXX="${SPLAT_CONDA_PREFIX}/bin/x86_64-conda-linux-gnu-c++" \
  TORCH_EXTENSIONS_DIR="${PROJECT_ROOT}/.cache/torch-extensions/splatfacto" \
  "${CONDA_EXE}" run --no-capture-output --prefix "${SPLAT_CONDA_PREFIX}" "$@"
}

case "${ACTION}" in
  train)
    [[ -f "${COLMAP_ROOT}/validation.json" ]] || fail "COLMAP geometry has not passed validation"
    mkdir -p "${NS_OUTPUT_ROOT}"
    SAVE_EVERY=2000
    if (( TRAIN_STEPS < SAVE_EVERY )); then
      SAVE_EVERY="${TRAIN_STEPS}"
    fi
    TRAIN_ARGS=(
      ns-train splatfacto
      --output-dir "${NS_OUTPUT_ROOT}"
      --experiment-name "${SEQUENCE_NAME}"
      --timestamp "${PROFILE}"
      --max-num-iterations "${TRAIN_STEPS}"
      --steps-per-save "${SAVE_EVERY}"
      --steps-per-eval-all-images "${TRAIN_STEPS}"
      --vis tensorboard
    )
    if compgen -G "${NS_MODELS}/step-*.ckpt" >/dev/null; then
      log "Resuming Splatfacto from the latest checkpoint in ${NS_MODELS}"
      TRAIN_ARGS+=(--load-dir "${NS_MODELS}")
    fi
    TRAIN_ARGS+=(
      colmap
      --data "${COLMAP_ROOT}"
      --colmap-path .
      --images-path .
      --downscale-factor 1
      --eval-mode interval
      --eval-interval "${EVAL_INTERVAL}"
    )
    log "Training Splatfacto for ${TRAIN_STEPS} total steps"
    run_ns "${TRAIN_ARGS[@]}"
    ;;
  evaluate)
    [[ -f "${NS_CONFIG}" ]] || fail "Training config does not exist: ${NS_CONFIG}"
    mkdir -p "$(dirname "${METRICS_PATH}")" "${EVAL_RENDER_DIR}"
    log "Evaluating held-out interval frames"
    run_ns ns-eval \
      --load-config "${NS_CONFIG}" \
      --output-path "${METRICS_PATH}" \
      --render-output-path "${EVAL_RENDER_DIR}"
    ;;
  export)
    [[ -f "${NS_CONFIG}" ]] || fail "Training config does not exist: ${NS_CONFIG}"
    mkdir -p "$(dirname "${SPLAT_PATH}")"
    log "Exporting the trained Gaussian representation"
    run_ns ns-export gaussian-splat \
      --load-config "${NS_CONFIG}" \
      --output-dir "$(dirname "${SPLAT_PATH}")" \
      --output-filename "$(basename "${SPLAT_PATH}")"
    ;;
  render)
    [[ -f "${NS_CONFIG}" ]] || fail "Training config does not exist: ${NS_CONFIG}"
    mkdir -p "$(dirname "${DEMO_PATH}")"
    log "Rendering a conservative path interpolated along observed training cameras"
    run_ns ns-render interpolate \
      --load-config "${NS_CONFIG}" \
      --output-path "${DEMO_PATH}" \
      --pose-source train \
      --interpolation-steps "${RENDER_INTERPOLATION_STEPS}" \
      --frame-rate "${RENDER_FPS}" \
      --rendered-output-names rgb
    ;;
  *)
    fail "Unknown Splatfacto action: ${ACTION}"
    ;;
esac
