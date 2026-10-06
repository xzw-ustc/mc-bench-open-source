"""Minecraft benchmark runtime configuration."""

PREPARE = r'''
                // Reset transport preparation, NOT an agent action or world edit.
                // A far-away DrawingDecorator chunk can exist server-side without
                // ChunkHolder.getChunkIfComplete tracking delivery having occurred.
                // Send normal ordered center/chunk/light packets BEFORE the single
                // teleport, so client collision never starts in an empty chunk.
                ServerWorld targetWorld = serverPlayer.getServerWorld();
                double collisionMargin = serverPlayer.getWidth() / 2.0D + 1.0D;
                int minChunkX = net.minecraft.util.math.MathHelper.floor(startPos.getX() - collisionMargin) >> 4;
                int maxChunkX = net.minecraft.util.math.MathHelper.floor(startPos.getX() + collisionMargin) >> 4;
                int minChunkZ = net.minecraft.util.math.MathHelper.floor(startPos.getZ() - collisionMargin) >> 4;
                int maxChunkZ = net.minecraft.util.math.MathHelper.floor(startPos.getZ() + collisionMargin) >> 4;
                List<net.minecraft.world.chunk.Chunk> collisionChunks = new ArrayList<>();
                for (int cx = minChunkX; cx <= maxChunkX; cx++) for (int cz = minChunkZ; cz <= maxChunkZ; cz++) {
                    net.minecraft.world.chunk.Chunk chunk = targetWorld.getChunkProvider().getChunkNow(cx, cz);
                    if (chunk == null) throw new IllegalStateException("Placement collision chunk unavailable: " + cx + "," + cz);
                    collisionChunks.add(chunk);
                }
                serverPlayer.connection.sendPacket(new net.minecraft.network.play.server.SUpdateChunkPositionPacket(
                        net.minecraft.util.math.MathHelper.floor(startPos.getX()) >> 4,
                        net.minecraft.util.math.MathHelper.floor(startPos.getZ()) >> 4));
                for (net.minecraft.world.chunk.Chunk chunk : collisionChunks) {
                    serverPlayer.sendChunkLoad(chunk.getPos(), new net.minecraft.network.play.server.SChunkDataPacket(chunk, 65535),
                            new net.minecraft.network.play.server.SUpdateLightPacket(chunk.getPos(), targetWorld.getChunkProvider().getLightManager(), true));
                }
                LOGGER.info("MCBENCH_PLACEMENT_CHUNK_PREPARATION chunks=" + collisionChunks.size()
                        + " extra_world_ticks=0 extra_agent_actions=0 loaded_new_chunks=0 repeated_teleports=0");
'''


def transform(text):
    anchor = "                serverPlayer.setMotion(0.0, 0.0, 0.0);"
    if text.count(anchor) != 1 or "MCBENCH_PLACEMENT_CHUNK_PREPARATION" in text:
        raise ValueError("unrecognized or already patched chunk preparation anchor")
    return text.replace(anchor, PREPARE + anchor)

