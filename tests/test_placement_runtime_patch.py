import pytest


from scripts.linux.patch_mcp_reborn_placement import OLD_METHOD, OLD_SETUP, OLD_WARMUP, transform


def source():
    return "prefix\n" + OLD_SETUP + "\n" + OLD_WARMUP + "\n" + OLD_METHOD + "\nsuffix\n"


def test_patch_preserves_warmup_and_surrounding_source():
    result = transform(source())
    assert result.startswith("prefix\n") and result.endswith("\nsuffix\n")
    assert result.count(OLD_WARMUP) == 1
    assert result.count('execActions("camera 0 0.0", 0)') == 1
    assert "serverPlayer.connection.setPlayerLocation" in result
    assert "verifyAgentPosition(mc.player, missionInit);" in result
    # Waiting must happen on the socket path, after it unblocks replay warmup.
    assert result.index("placementReady.get(") > result.index(OLD_WARMUP)
    assert "server.runAsync" in result and "whenComplete" in result
    assert "player.setPosition(startPos" not in result


@pytest.mark.parametrize("text", [source().replace(OLD_SETUP, ""), source()+OLD_METHOD, transform(source())])
def test_missing_duplicate_or_already_patched_source_fails(text):
    with pytest.raises(ValueError, match="anchor"):
        transform(text)
