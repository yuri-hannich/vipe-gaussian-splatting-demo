#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

FILE_MANIFEST="${PROJECT_ROOT}/configs/dataset-files.tsv"
[[ -f "${FILE_MANIFEST}" ]] || fail "Dataset file inventory is missing: ${FILE_MANIFEST}"
ENTRY_COUNT="$(grep -vc '^#' "${FILE_MANIFEST}")"
[[ "${ENTRY_COUNT}" == "${EXPECTED_FRAMES}" ]] \
  || fail "Expected ${EXPECTED_FRAMES} manifest entries, found ${ENTRY_COUNT}"

mkdir -p "${DATASET_DIR}"
if [[ -n "${DATASET_ARCHIVE:-}" ]]; then
  [[ -f "${DATASET_ARCHIVE}" ]] || fail "Dataset archive does not exist: ${DATASET_ARCHIVE}"
  log "Extracting the supplied dataset archive: ${DATASET_ARCHIVE}"
  unzip -q -o "${DATASET_ARCHIVE}" -d "${DATASET_DIR}"
fi

UVX_EXE="$(uvx_executable)"

download_file() {
  local file_id="$1"
  local output="$2"
  local direct_url="https://drive.usercontent.google.com/download?id=${file_id}&export=download&confirm=t"
  if curl --location --fail --silent --show-error \
    --connect-timeout 20 --retry 2 --retry-all-errors --retry-delay 2 \
    "${direct_url}" --output "${output}"; then
    return 0
  fi
  rm -f "${output}"
  log "Direct Drive transport failed; falling back to pinned gdown"
  "${UVX_EXE}" --from "gdown==${GDOWN_VERSION}" \
    gdown "${file_id}" --output "${output}" --quiet --continue
}

matches_inventory() {
  local path="$1"
  local expected_size="$2"
  local expected_sha256="$3"
  [[ -f "${path}" ]] \
    && [[ "$(wc -c < "${path}" | tr -d ' ')" == "${expected_size}" ]] \
    && [[ "$(file_sha256 "${path}")" == "${expected_sha256}" ]]
}

downloaded=0
reused=0
processed=0
while IFS=$'\t' read -r file_id filename expected_size expected_sha256 extra; do
  [[ -z "${file_id}" || "${file_id}" == \#* ]] && continue
  [[ -z "${extra:-}" ]] || fail "Dataset inventory has extra fields for ${filename}"
  [[ "${expected_sha256}" =~ ^[0-9a-f]{64}$ ]] \
    || fail "Dataset inventory has an invalid SHA-256 for ${filename}"
  (( processed >= FRAME_COUNT )) && break
  processed=$((processed + 1))
  target="${DATASET_DIR}/${filename}"
  if matches_inventory "${target}" "${expected_size}" "${expected_sha256}"; then
    reused=$((reused + 1))
    continue
  fi

  temporary="${target}.download"
  log "Downloading ${filename} ($((downloaded + reused + 1))/${EXPECTED_FRAMES})"
  success=false
  for attempt in 1 2 3 4 5; do
    if download_file "${file_id}" "${temporary}"; then
      actual_size="$(wc -c < "${temporary}" | tr -d ' ')"
      actual_sha256="$(file_sha256 "${temporary}")"
      if [[ "${actual_size}" == "${expected_size}" ]] \
        && [[ "${actual_sha256}" == "${expected_sha256}" ]]; then
        success=true
        break
      fi
      log "Integrity mismatch on attempt ${attempt}/5 for ${filename}: expected ${expected_size}/${expected_sha256}, got ${actual_size}/${actual_sha256}"
      rm -f "${temporary}"
    fi
    (( attempt < 5 )) || break
    delay=$((attempt * 15))
    log "Google Drive attempt ${attempt}/5 failed for ${filename}; retrying in ${delay}s"
    sleep "${delay}"
  done
  [[ "${success}" == true ]] || fail "Could not download ${filename} after 5 attempts"
  mv "${temporary}" "${target}"
  downloaded=$((downloaded + 1))
done < "${FILE_MANIFEST}"

log "Dataset transfer complete for ${FRAME_COUNT} required frames: ${reused} reused, ${downloaded} downloaded"
