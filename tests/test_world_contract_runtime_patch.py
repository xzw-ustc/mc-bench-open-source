import pytest


from scripts.linux import patch_mcp_reborn_world_contract as patcher


def source():
    return "\n".join([
        "prefix", patcher.SETUP,
        "        mc.execute(() -> applyMissionWorldSetup(mc, missionInit));",
        "        for (int i = 0; i < skipFrames; i++) {",
        '            execActions("camera 0 0.0", 0);',
        "            waitForNextObservation();", "        }",
        "            placementReady.get(30, java.util.concurrent.TimeUnit.SECONDS);",
        "        execActions(actions, options);", "        waitForNextObservation();", "suffix",
    ])


def test_patch_preserves_time_drawing_and_action_count():
    before, after = source(), patcher.transform(source())
    assert after.startswith("prefix\n") and after.endswith("\nsuffix")
    assert before.count("execActions(") == after.count("execActions(") == 2
    assert after.count("for (int i = 0; i < skipFrames; i++)") == 1
    assert after.count("applyMissionTime(mc, missionInit);") == 1
    assert after.count("applyDrawingDecorators(mc, missionInit);") == 1
    assert "worldContractReady.get(30" in after
    assert after.index("worldContractReady.get(30") > after.index('execActions("camera 0 0.0", 0)')


@pytest.mark.parametrize("text", [source().replace(patcher.SETUP, ""), source() + patcher.SETUP, patcher.transform(source())])
def test_anchor_mismatch_or_double_application_rejected(text):
    with pytest.raises(ValueError, match="anchor"):
        patcher.transform(text)


def test_readonly_audit_never_requests_chunks_or_changes_world():
    audit = patcher.METHODS.split("    private void auditWorldContract(", 1)[1]
    assert "getChunkNow(" in audit
    for forbidden in ("setBlockState(", "setPosition(", "getChunk(", "forceChunk(", "registerTicket(", "execActions(", "infoJson"):
        assert forbidden not in audit
    assert "MCBENCH_WORLD_CONTRACT " in audit
    assert "async_owner_thread_not_post_action_barrier" in audit
    assert "if (unsupportedShapes == 0)" in audit
    assert "entry.setValue(" in audit  # later cuboid overwrites tracked point


def test_explicit_rules_run_on_owner_thread_and_errors_propagate():
    after = patcher.transform(source())
    assert "server.runAsync(() -> {\n                applyMissionWeatherAndSpawning" in after
    assert "ready.completeExceptionally(error)" in after
    assert "if (spawning != null)" in after
    assert "if (weather == null) continue;" in after
    assert "DO_MOB_SPAWNING).set(spawning, server)" in after
    assert "DO_WEATHER_CYCLE).set(normal, server)" in after
    assert 'world.func_241113_a_(rain ? 0 : 6000, 6000, rain, thunder)' in after


def test_noop_recognition_is_conservative():
    method = patcher.METHODS.split("    private boolean isDiagnosticNoop", 1)[1].split("    private void requestWorldContractAudit", 1)[0]
    assert 'split("\\\\s+")' in method
    assert 'Double.parseDouble(words[i]) != 0.0' in method
    assert 'words.length != ("camera".equals(words[0]) ? 3 : 2)' in method
    assert "catch (NumberFormatException error) { return false; }" in method
