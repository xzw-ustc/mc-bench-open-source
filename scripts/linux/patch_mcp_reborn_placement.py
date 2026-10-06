"""Minecraft benchmark runtime configuration."""

OLD_SETUP = '''        mc.execute(() -> setAgentInventory(mc.player, missionInit));
        mc.execute(() -> setAgentPosition(mc.player, missionInit));
        mc.execute(() -> applyMissionWorldSetup(mc, missionInit));'''


NEW_SETUP = '''        mc.execute(() -> setAgentInventory(mc.player, missionInit));
        mc.execute(() -> applyMissionWorldSetup(mc, missionInit));
        // Keep both game threads free: replay blocks the client until warmup
        // actions arrive. Only the socket thread waits, after those same frames.
        java.util.concurrent.CompletableFuture<Void> placementReady = new java.util.concurrent.CompletableFuture<>();
        mc.execute(() -> setAgentPosition(mc.player, missionInit, placementReady));'''


OLD_WARMUP = '''        for (int i = 0; i < skipFrames; i++) {
            execActions("camera 0 0.0", 0);
            waitForNextObservation();
        }'''


NEW_WARMUP = OLD_WARMUP + '''
        try {
            placementReady.get(30, java.util.concurrent.TimeUnit.SECONDS);
        } catch (ExecutionException | java.util.concurrent.TimeoutException error) {
            throw new IOException("MCBench authoritative Placement failed", error);
        }
        // The existing observation synchronization publishes client state to
        // this socket thread. Reject drift/correction before reset returns.
        verifyAgentPosition(mc.player, missionInit);'''


OLD_METHOD = '''    private void setAgentPosition(ClientPlayerEntity player, MissionInit missionInit) {
        PosAndDirection startPos = getAgentStart(missionInit).getPlacement();
        if (startPos == null) {
            return;
        }
        player.setPosition(startPos.getX(), startPos.getY(), startPos.getZ());
        player.rotationYaw = startPos.getYaw();
        player.rotationPitch = startPos.getPitch();
    }'''


NEW_METHOD = '''    private void setAgentPosition(ClientPlayerEntity player, MissionInit missionInit,
                                  java.util.concurrent.CompletableFuture<Void> ready) {
        PosAndDirection startPos = getAgentStart(missionInit).getPlacement();
        if (startPos == null) {
            ready.complete(null);
            return;
        }
        try {
            MinecraftServer server = Minecraft.getInstance().getIntegratedServer();
            if (server == null || player == null) {
                throw new IllegalStateException("Placement requires an integrated server and a joined client");
            }
            UUID playerId = player.getUniqueID();
            // Do not mutate ServerPlayerEntity from the render/socket thread.
            // The server connection sends the ordinary teleport/ack protocol,
            // so client-only coordinates cannot be corrected to world spawn.
            server.runAsync(() -> {
                net.minecraft.entity.player.ServerPlayerEntity serverPlayer = server.getPlayerList().getPlayerByUUID(playerId);
                if (serverPlayer == null) {
                    throw new IllegalStateException("Placement target has not joined the server");
                }
                serverPlayer.setMotion(0.0, 0.0, 0.0);
                serverPlayer.fallDistance = 0.0F;
                serverPlayer.connection.setPlayerLocation(startPos.getX(), startPos.getY(), startPos.getZ(),
                        startPos.getYaw(), startPos.getPitch());
                serverPlayer.getServerWorld().getChunkProvider().updatePlayerPosition(serverPlayer);
                LOGGER.info("MCBench authoritative Placement applied: " + startPos.getX() + "," + startPos.getY()
                        + "," + startPos.getZ() + " yaw=" + startPos.getYaw() + " pitch=" + startPos.getPitch());
            }).whenComplete((unused, error) -> {
                if (error == null) {
                    ready.complete(null);
                } else {
                    ready.completeExceptionally(error);
                }
            });
        } catch (Exception error) {
            ready.completeExceptionally(error);
        }
    }

    private void verifyAgentPosition(ClientPlayerEntity player, MissionInit missionInit) throws IOException {
        PosAndDirection expected = getAgentStart(missionInit).getPlacement();
        if (expected == null) {
            return; // Natural-spawn profiles retain their original behavior.
        }
        if (player == null) {
            throw new IOException("Placement validation has no client player");
        }
        double dx = player.getPosX() - expected.getX();
        double dy = player.getPosY() - expected.getY();
        double dz = player.getPosZ() - expected.getZ();
        float yawError = net.minecraft.util.math.MathHelper.wrapDegrees(player.rotationYaw - expected.getYaw());
        float pitchError = player.rotationPitch - expected.getPitch();
        // One centimetre is numerical tolerance, not permission to fall or move.
        // A profile without valid terrain support must fail infrastructure QA.
        if (!Double.isFinite(dx + dy + dz) || !Float.isFinite(yawError + pitchError)
                || Math.abs(dx) > 0.01 || Math.abs(dy) > 0.01 || Math.abs(dz) > 0.01
                || Math.abs(yawError) > 0.01 || Math.abs(pitchError) > 0.01) {
            throw new IOException("Placement mismatch after reset warmup: expected=" + expected.getX() + ","
                    + expected.getY() + "," + expected.getZ() + " actual=" + player.getPosX() + ","
                    + player.getPosY() + "," + player.getPosZ() + " yaw_error=" + yawError + " pitch_error=" + pitchError);
        }
        LOGGER.info("MCBench authoritative Placement verified after reset warmup: " + player.getPosX() + ","
                + player.getPosY() + "," + player.getPosZ());
    }'''


def transform(text):
    for old, new in ((OLD_SETUP, NEW_SETUP), (OLD_WARMUP, NEW_WARMUP), (OLD_METHOD, NEW_METHOD)):
        if text.count(old) != 1:
            raise ValueError("unrecognized or already patched EnvServer anchor")
        text = text.replace(old, new, 1)
    return text

