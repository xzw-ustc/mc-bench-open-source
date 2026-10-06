"""Apply the benchmark's pinned Minecraft runtime configuration."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.linux import patch_mcp_reborn_mcbench as base
from scripts.linux import patch_mcp_reborn_placement as placement
from scripts.linux import patch_mcp_reborn_world_contract as world
from scripts.linux import patch_mcp_reborn_placement_chunks as chunks
from scripts.linux import patch_mcp_reborn_placement_chunks_v2 as arena

LOCK = Path(__file__).resolve().parents[2] / 'environments/linux/runtime-lock.json'
SOURCE = Path('src/main/java/com/minerl/multiagent/env/EnvServer.java')


def patch(root: Path) -> None:
    lock = json.loads(LOCK.read_text())
    path = root / SOURCE
    before = path.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    if digest == lock['env_server_after_sha256']:
        base.patch_launch_client(root)
        base.patch_block_type(root)
        return
    if digest != lock['env_server_before_sha256']:
        raise ValueError('EnvServer.java does not match the configured MineRL revision.')
    try:
        base.patch_env_server(root)
        text = path.read_text()
        for transform in (placement.transform, world.transform, chunks.transform, arena.transform):
            text = transform(text)
        if hashlib.sha256(text.encode()).hexdigest() != lock['env_server_after_sha256']:
            raise ValueError('Patched EnvServer.java checksum mismatch.')
        base.patch_launch_client(root)
        base.patch_block_type(root)
        path.write_text(text)
    except Exception:
        path.write_bytes(before)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    patch(parser.parse_args().root)
