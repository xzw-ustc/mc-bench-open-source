import pytest


from scripts.linux import patch_mcp_reborn_placement_chunks as patcher


def test_prepare_precedes_single_teleport_without_extra_ticks():
    original = """prefix
                serverPlayer.setMotion(0.0, 0.0, 0.0);
                serverPlayer.connection.setPlayerLocation(startPos.getX(), startPos.getY(), startPos.getZ(),
                        startPos.getYaw(), startPos.getPitch());
suffix"""
    result = patcher.transform(original)
    assert result.startswith("prefix\n") and result.endswith("\nsuffix")
    assert result.count("setPlayerLocation(") == 1
    assert result.index("sendChunkLoad(") < result.index("setPlayerLocation(")
    assert result.index("SUpdateChunkPositionPacket(") < result.index("sendChunkLoad(")
    assert "getChunkNow(" in result
    assert "if (chunk == null) throw" in result
    for forbidden in ("setBlockState(", "execActions(", "getChunk(", "forceChunk(", "runSyncTick("):
        assert forbidden not in result


def test_double_application_rejected():
    source = "                serverPlayer.setMotion(0.0, 0.0, 0.0);"
    with pytest.raises(ValueError, match="anchor"):
        patcher.transform(patcher.transform(source))
