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
    RUN_STEPS="${TRAIN_STEPS}"
    LATEST_CHECKPOINT=""
    for checkpoint in "${NS_MODELS}"/step-*.ckpt; do
      [[ -e "${checkpoint}" ]] || continue
      if [[ -z "${LATEST_CHECKPOINT}" || "${checkpoint}" > "${LATEST_CHECKPOINT}" ]]; then
        LATEST_CHECKPOINT="${checkpoint}"
      fi
    done

    if [[ -n "${LATEST_CHECKPOINT}" ]]; then
      CHECKPOINT_STEP="$(checkpoint_step_from_path "${LATEST_CHECKPOINT}")" \
        || fail "Cannot parse checkpoint step: ${LATEST_CHECKPOINT}"
      RUN_STEPS="$(remaining_training_steps "${TRAIN_STEPS}" "${CHECKPOINT_STEP}")"
      if (( RUN_STEPS == 0 )); then
        log "Splatfacto target ${TRAIN_STEPS} already reached by checkpoint step ${CHECKPOINT_STEP}"
        exit 0
      fi
      log "Resuming Splatfacto from step ${CHECKPOINT_STEP}; ${RUN_STEPS} steps remain to target ${TRAIN_STEPS}"
    fi

    SAVE_EVERY=2000
    if (( RUN_STEPS < SAVE_EVERY )); then
      SAVE_EVERY="${RUN_STEPS}"
    fi
    TRAIN_ARGS=(
      ns-train splatfacto
      --output-dir "${NS_OUTPUT_ROOT}"
      --experiment-name "${SEQUENCE_NAME}"
      --timestamp "${PROFILE}"
      --max-num-iterations "${RUN_STEPS}"
      --steps-per-save "${SAVE_EVERY}"
      --steps-per-eval-all-images "${RUN_STEPS}"
      --vis tensorboard
    )
    if [[ -n "${LATEST_CHECKPOINT}" ]]; then
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
    log "Training Splatfacto for ${RUN_STEPS} invocation steps (target: ${TRAIN_STEPS} total)"
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
