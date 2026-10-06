import pytest


from scripts.linux import patch_mcp_reborn_placement_chunks_v2 as patcher


def source():
    return "\n".join(["prefix", patcher.OLD, "            points.add(point);",
                       '"MCBENCH_PLACEMENT_CHUNK_PREPARATION chunks="', "suffix"])


def test_arena_union_deduplicates_loaded_chunks_without_loading_or_actions():
    result = patcher.transform(source())
    assert "new LinkedHashSet<>()" in result
    assert "object instanceof DrawBlock" in result and "object instanceof DrawCuboid" in result
    assert "getChunkNow(position.x, position.z)" in result
    assert "if (chunk == null) throw" in result
    for forbidden in ("setBlockState(", "execActions(", "forceChunk(", "runSyncTick(", "setPlayerLocation("):
        assert forbidden not in result


def test_client_resource_audit_is_nonloading_readonly():
    audit = patcher.CLIENT_AUDIT
    assert "ChunkStatus.FULL, false)" in audit
    assert '"client_loaded"' in audit
    assert '"client_actual_block_id"' in audit
    assert '"client_block_id_matches"' in audit
    assert "if (unsupportedShapes == 0)" in audit
    assert "infoJson" not in audit and "setBlockState" not in audit


@pytest.mark.parametrize("text", [source() + patcher.OLD, source().replace(patcher.OLD, ""), patcher.transform(source())])
def test_missing_duplicate_or_applied_anchor_rejected(text):
    with pytest.raises(ValueError, match="anchor"):
        patcher.transform(text)
