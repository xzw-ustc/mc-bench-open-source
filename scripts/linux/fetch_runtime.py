"""Fetch the exact MineRL source revision used by the benchmark."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

LOCK = Path(__file__).resolve().parents[2] / 'environments/linux/runtime-lock.json'


def prepare(destination: Path) -> None:
    lock = json.loads(LOCK.read_text())
    destination.mkdir(parents=True, exist_ok=False)
    subprocess.run(['git', 'init', '--quiet', str(destination)], check=True)
    def git(*args):
        return subprocess.run(['git', '-C', str(destination), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git('remote', 'add', 'origin', lock['minerl']['repository'])
    git('fetch', '--quiet', '--depth', '1', 'origin', lock['minerl']['commit'])
    git('checkout', '--quiet', '--detach', 'FETCH_HEAD')
    if git('rev-parse', 'HEAD') != lock['minerl']['commit']:
        raise ValueError('MineRL revision mismatch.')
    setup = destination / 'scripts/setup_mcp.sh'
    text = setup.read_text()
    old = 'git checkout 1.16.5-20210115'
    if text.count(old) != 1:
        raise ValueError('Unexpected MCP-Reborn setup script.')
    text = text.replace(old, 'git checkout --detach ' + lock['mcp_reborn']['commit'])
    text = text.replace('#!/bin/bash', '#!/bin/bash\nset -euo pipefail', 1)
    text = text.replace('rm -rf MCP-Reborn',
                        'if [ -f MCP-Reborn/gradlew ]; then exit 0; fi\nrm -rf MCP-Reborn', 1)
    setup.write_text(text)
    patch = destination / 'scripts/patch_mcp.sh'
    text = patch.read_text().replace('#!/bin/bash', '#!/bin/bash\nset -euo pipefail', 1)
    marker = 'patch -s -p 1 -i ${DIR}/mcp_patch.diff'
    if text.count(marker) != 1:
        raise ValueError('Unexpected MineRL patch script.')
    text = text.replace(marker,
        'if [ -f src/main/java/com/minerl/multiagent/env/EnvServer.java ]; then exit 0; fi\n' + marker, 1)
    patch.write_text(text)
    print(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    prepare(parser.parse_args().destination)
