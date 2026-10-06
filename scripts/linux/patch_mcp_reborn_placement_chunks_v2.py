"""Minecraft benchmark runtime configuration."""

OLD = '''                List<net.minecraft.world.chunk.Chunk> collisionChunks = new ArrayList<>();
                for (int cx = minChunkX; cx <= maxChunkX; cx++) for (int cz = minChunkZ; cz <= maxChunkZ; cz++) {
                    net.minecraft.world.chunk.Chunk chunk = targetWorld.getChunkProvider().getChunkNow(cx, cz);
                    if (chunk == null) throw new IllegalStateException("Placement collision chunk unavailable: " + cx + "," + cz);
                    collisionChunks.add(chunk);
                }'''


NEW = '''                Set<net.minecraft.util.math.ChunkPos> configuredChunks = new LinkedHashSet<>();
                for (int cx = minChunkX; cx <= maxChunkX; cx++) for (int cz = minChunkZ; cz <= maxChunkZ; cz++) {
                    configuredChunks.add(new net.minecraft.util.math.ChunkPos(cx, cz));
                }
                // The arena is explicitly part of Mission setup, not hidden policy
                // knowledge. Synchronize its existing data using vanilla packets.
                if (missionInit.getMission().getServerSection().getServerHandlers() != null) {
                    for (Object decorator : missionInit.getMission().getServerSection().getServerHandlers().getWorldDecorators()) {
                        if (!(decorator instanceof DrawingDecorator)) continue;
                        for (JAXBElement<? extends DrawObjectType> element : ((DrawingDecorator) decorator).getDrawObjectType()) {
                            DrawObjectType object = element.getValue();
                            if (object instanceof DrawBlock) {
                                DrawBlock b = (DrawBlock) object;
                                configuredChunks.add(new net.minecraft.util.math.ChunkPos(b.getX() >> 4, b.getZ() >> 4));
                            } else if (object instanceof DrawCuboid) {
                                DrawCuboid b = (DrawCuboid) object;
                                for (int cx = Math.min(b.getX1(), b.getX2()) >> 4; cx <= (Math.max(b.getX1(), b.getX2()) >> 4); cx++) {
                                    for (int cz = Math.min(b.getZ1(), b.getZ2()) >> 4; cz <= (Math.max(b.getZ1(), b.getZ2()) >> 4); cz++) {
                                        configuredChunks.add(new net.minecraft.util.math.ChunkPos(cx, cz));
                                    }
                                }
                            } else {
                                throw new IllegalStateException("Unsupported arena drawing shape in chunk preparation");
                            }
                        }
                    }
                }
                List<net.minecraft.world.chunk.Chunk> collisionChunks = new ArrayList<>();
                for (net.minecraft.util.math.ChunkPos position : configuredChunks) {
                    net.minecraft.world.chunk.Chunk chunk = targetWorld.getChunkProvider().getChunkNow(position.x, position.z);
                    if (chunk == null) throw new IllegalStateException("Placement configured chunk unavailable: " + position);
                    collisionChunks.add(chunk);
                }'''


CLIENT_AUDIT = '''            Minecraft auditClient = Minecraft.getInstance();
            net.minecraft.world.chunk.Chunk clientChunk = auditClient.world == null ? null : auditClient.world.getChunkProvider().getChunk(
                    p.getX() >> 4, p.getZ() >> 4, net.minecraft.world.chunk.ChunkStatus.FULL, false);
            point.addProperty("client_loaded", clientChunk != null);
            if (clientChunk != null) {
                BlockState clientActual = clientChunk.getBlockState(p);
                point.addProperty("client_actual_block_id", blockName(clientActual));
                point.addProperty("client_actual_block_state", clientActual.toString());
                if (unsupportedShapes == 0) point.addProperty("client_block_id_matches", entry.getValue().equals(blockName(clientActual)));
            }
'''


def transform(text):
    for old, new in ((OLD, NEW), ("            points.add(point);", CLIENT_AUDIT + "            points.add(point);"),
                     ('"MCBENCH_PLACEMENT_CHUNK_PREPARATION chunks="', '"MCBENCH_PLACEMENT_CHUNK_PREPARATION_V2 configured_chunks="')):
        if text.count(old) != 1:
            raise ValueError("unrecognized or already patched v2 anchor")
        text = text.replace(old, new, 1)
    return text

