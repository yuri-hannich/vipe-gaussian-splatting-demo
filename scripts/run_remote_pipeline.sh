#!/usr/bin/env bash
set -u

PROJECT_ROOT="$1"
PROFILE="$2"
JOB_DIR="$3"

mkdir -p "${JOB_DIR}"
cd "${PROJECT_ROOT}"

set +e
make pipeline PROFILE="${PROFILE}"
exit_code=$?
set -e

printf '%s\n' "${exit_code}" > "${JOB_DIR}/exit-code.tmp"
mv "${JOB_DIR}/exit-code.tmp" "${JOB_DIR}/exit-code"
exit "${exit_code}"
