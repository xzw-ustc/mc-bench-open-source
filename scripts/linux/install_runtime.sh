#!/usr/bin/env bash
set -euo pipefail
mcbench_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$mcbench_root"
python - <<'PY'
import subprocess
import sys
if sys.version_info[:2] != (3, 10):
    raise SystemExit('Minecraft runtime requires Python 3.10.')
if sys.prefix == sys.base_prefix:
    raise SystemExit('Activate a Python virtual environment before installing the runtime.')
result = subprocess.run(['java', '-version'], capture_output=True, text=True, check=True)
if '"1.8.' not in result.stderr + result.stdout:
    raise SystemExit('Minecraft runtime requires Java 8.')
PY
python -m pip install 'setuptools==65.5.0' 'wheel==0.38.4'
python -m pip install -r environments/linux/requirements.txt
python -m pip install --no-deps --no-build-isolation -e .
mcbench_source_dir="$mcbench_root/.runtime/minerl"
if [[ ! -d "$mcbench_source_dir" ]]; then
    python -m scripts.linux.fetch_runtime "$mcbench_source_dir"
fi
python - "$mcbench_source_dir" <<'PY'
import json
import subprocess
import sys
from pathlib import Path
lock = json.loads(Path('environments/linux/runtime-lock.json').read_text())
actual = subprocess.check_output(['git', '-C', sys.argv[1], 'rev-parse', 'HEAD'], text=True).strip()
if actual != lock['minerl']['commit']:
    raise SystemExit('MineRL source revision mismatch.')
PY
python -m pip install --no-deps --no-build-isolation "$mcbench_source_dir"
mcbench_runtime_root="$(python - <<'PY'
import importlib.util
from pathlib import Path
print(Path(importlib.util.find_spec('minerl').origin).parent / 'MCP-Reborn')
PY
)"
python -m scripts.linux.patch_runtime "$mcbench_runtime_root"
(cd "$mcbench_runtime_root" && ./gradlew --no-daemon compileJava)
python -m mcbench.cli doctor
