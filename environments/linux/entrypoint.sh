#!/usr/bin/env bash
set -euo pipefail

export MCBENCH_ROOT="${MCBENCH_ROOT:-/workspace/mc-bench}"
export JAVA_HOME="${JAVA_HOME:-/opt/java/openjdk}"
export PATH="${JAVA_HOME}/bin:${PATH}"
export PYTHONPATH="${PYTHONPATH:-${MCBENCH_ROOT}/src}"

if [[ "${MCBENCH_XVFB:-0}" == "1" ]]; then
  exec xvfb-run -a "$@"
fi

exec "$@"
