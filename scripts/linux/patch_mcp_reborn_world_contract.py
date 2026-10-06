"""Minecraft benchmark runtime configuration."""

METHODS = r'''
    private void applyMissionWeatherAndSpawning(MinecraftServer server, MissionInit mission) {
        ServerInitialConditions conditions = getServerInit(mission);
        if (conditions == null) return;
        String weather = conditions.getWeather();
        Boolean spawning = conditions.isAllowSpawning();
        if (weather != null && !Arrays.asList("normal", "clear", "rain", "thunder").contains(weather)) {
            throw new IllegalArgumentException("Unsupported Mission weather: " + weather);
        }
        for (ServerWorld world : server.getWorlds()) {
            if (spawning != null) {
                world.getGameRules().get(GameRules.DO_MOB_SPAWNING).set(spawning, server);
                // Natural-spawn permission, not removal of existing entities.
                world.setAllowedSpawnTypes(spawning, spawning);
            }
            if (weather == null) continue;
            boolean normal = "normal".equals(weather);
            world.getGameRules().get(GameRules.DO_WEATHER_CYCLE).set(normal, server);
            if (!normal) {
                boolean rain = "rain".equals(weather) || "thunder".equals(weather);
                boolean thunder = "thunder".equals(weather);
                // Vanilla ServerWorld.setWeather(clearTime, weatherTime, rain, thunder).
                world.func_241113_a_(rain ? 0 : 6000, 6000, rain, thunder);
                world.setRainStrength(rain ? 1.0F : 0.0F);
                world.setThunderStrength(thunder ? 1.0F : 0.0F);
            }
        }
    }

    private boolean isDiagnosticNoop(String actions) {
        // Conservative recognition: unknown commands do not qualify as noop.
        for (String line : actions.split("\n")) {
            if (line.trim().isEmpty()) continue;
            String[] words = line.trim().split("\\s+");
            if (!Arrays.asList("camera", "dwheel", "forward", "back", "left", "right",
                    "jump", "sprint", "sneak", "attack", "use", "pickItem", "inventory",
                    "drop", "swapHands", "ESC", "hotbar.1", "hotbar.2", "hotbar.3", "hotbar.4",
                    "hotbar.5", "hotbar.6", "hotbar.7", "hotbar.8", "hotbar.9").contains(words[0])) return false;
            if (words.length != ("camera".equals(words[0]) ? 3 : 2)) return false;
            for (int i = 1; i < words.length; i++) {
                try { if (Double.parseDouble(words[i]) != 0.0) return false; }
                catch (NumberFormatException error) { return false; }
            }
        }
        return true;
    }

    private void requestWorldContractAudit(String phase, int requestedTick) {
        MinecraftServer server = Minecraft.getInstance().getIntegratedServer();
        final MissionInit mission = this.missionInit;
        if (server == null || mission == null) return;
        server.runAsync(() -> auditWorldContract(server, mission, phase, requestedTick))
                .whenComplete((unused, error) -> {
                    if (error != null) LOGGER.error("MCBench world-contract audit failed", error);
                });
    }

    private void auditWorldContract(MinecraftServer server, MissionInit mission, String phase, int requestedTick) {
        // This method runs only on the integrated-server owner thread. Read only:
        // getChunkNow returns null for unavailable chunks and never requests one.
        ServerWorld world = server.func_241755_D_();
        Map<BlockPos, String> expected = new LinkedHashMap<>();
        int unsupportedShapes = 0;
        if (mission.getMission().getServerSection().getServerHandlers() != null) {
            for (Object decorator : mission.getMission().getServerSection().getServerHandlers().getWorldDecorators()) {
                if (!(decorator instanceof DrawingDecorator)) continue;
                for (JAXBElement<? extends DrawObjectType> element : ((DrawingDecorator) decorator).getDrawObjectType()) {
                    DrawObjectType object = element.getValue();
                    if (object instanceof DrawBlock) {
                        DrawBlock b = (DrawBlock) object;
                        expected.put(new BlockPos(b.getX(), b.getY(), b.getZ()), normalizeBlockName(b.getType().value(),
                                b.getVariant() == null ? null : b.getVariant().getValue()));
                    } else if (object instanceof DrawCuboid) {
                        DrawCuboid b = (DrawCuboid) object;
                        // A later cuboid can overwrite an earlier DrawBlock point.
                        // Examine tracked points only, not a potentially huge volume.
                        for (Map.Entry<BlockPos, String> entry : expected.entrySet()) {
                            BlockPos p = entry.getKey();
                            if (p.getX() >= Math.min(b.getX1(), b.getX2()) && p.getX() <= Math.max(b.getX1(), b.getX2())
                                    && p.getY() >= Math.min(b.getY1(), b.getY2()) && p.getY() <= Math.max(b.getY1(), b.getY2())
                                    && p.getZ() >= Math.min(b.getZ1(), b.getZ2()) && p.getZ() <= Math.max(b.getZ1(), b.getZ2())) {
                                entry.setValue(normalizeBlockName(b.getType().value(), b.getVariant() == null ? null : b.getVariant().getValue()));
                            }
                        }
                    } else { unsupportedShapes++; }
                }
            }
        }
        JsonObject log = new JsonObject();
        log.addProperty("schema", "mcbench-world-contract-sample-v1");
        log.addProperty("phase_requested", phase);
        log.addProperty("requested_client_tick", requestedTick);
        log.addProperty("server_game_time", world.getGameTime());
        log.addProperty("server_day_time", world.getDayTime());
        log.addProperty("dimension", world.getDimensionKey().getLocation().toString());
        log.addProperty("raining", world.getWorldInfo().isRaining());
        log.addProperty("thundering", world.getWorldInfo().isThundering());
        log.addProperty("rain_strength", world.getRainStrength(1.0F));
        log.addProperty("thunder_strength", world.getThunderStrength(1.0F));
        log.addProperty("do_weather_cycle", world.getGameRules().getBoolean(GameRules.DO_WEATHER_CYCLE));
        log.addProperty("do_mob_spawning", world.getGameRules().getBoolean(GameRules.DO_MOB_SPAWNING));
        log.addProperty("unsupported_drawing_shapes", unsupportedShapes);
        log.addProperty("sampling", "async_owner_thread_not_post_action_barrier");
        JsonArray points = new JsonArray();
        for (Map.Entry<BlockPos, String> entry : expected.entrySet()) {
            BlockPos p = entry.getKey();
            JsonObject point = new JsonObject();
            point.addProperty("x", p.getX()); point.addProperty("y", p.getY()); point.addProperty("z", p.getZ());
            point.addProperty("expected_block_id", entry.getValue());
            net.minecraft.world.chunk.Chunk chunk = world.getChunkProvider().getChunkNow(p.getX() >> 4, p.getZ() >> 4);
            point.addProperty("loaded", chunk != null);
            if (chunk != null) {
                BlockState actual = chunk.getBlockState(p);
                point.addProperty("actual_block_id", blockName(actual));
                point.addProperty("actual_block_state", actual.toString());
                if (unsupportedShapes == 0) point.addProperty("block_id_matches", entry.getValue().equals(blockName(actual)));
            }
            points.add(point);
        }
        log.add("draw_block_points", points);
        LOGGER.info("MCBENCH_WORLD_CONTRACT " + log.toString());
    }
'''


SETUP = '''    private void applyMissionWorldSetup(Minecraft mc, MissionInit missionInit) {
        applyMissionTime(mc, missionInit);
        applyDrawingDecorators(mc, missionInit);
    }'''


NEW_SETUP = '''    private void applyMissionWorldSetup(Minecraft mc, MissionInit missionInit,
                                       java.util.concurrent.CompletableFuture<Void> ready) {
        applyMissionTime(mc, missionInit);
        applyDrawingDecorators(mc, missionInit);
        MinecraftServer server = mc.getIntegratedServer();
        if (server != null) {
            server.runAsync(() -> {
                applyMissionWeatherAndSpawning(server, missionInit);
                auditWorldContract(server, missionInit, "world_setup", -1);
            }).whenComplete((unused, error) -> {
                if (error == null) ready.complete(null);
                else ready.completeExceptionally(error);
            });
        } else {
            ready.completeExceptionally(new IllegalStateException("World contract requires integrated server"));
        }
    }'''


def transform(text):
    warmup = '        for (int i = 0; i < skipFrames; i++) {\n            execActions("camera 0 0.0", 0);'
    step = '        execActions(actions, options);\n        waitForNextObservation();'
    setup_call = '        mc.execute(() -> applyMissionWorldSetup(mc, missionInit));'
    setup_wait = '            placementReady.get(30, java.util.concurrent.TimeUnit.SECONDS);'
    for old, new in ((SETUP, NEW_SETUP + METHODS),
                     (setup_call, '        java.util.concurrent.CompletableFuture<Void> worldContractReady = new java.util.concurrent.CompletableFuture<>();\n        mc.execute(() -> applyMissionWorldSetup(mc, missionInit, worldContractReady));'),
                     (setup_wait, '            worldContractReady.get(30, java.util.concurrent.TimeUnit.SECONDS);\n' + setup_wait),
                     (warmup, warmup.replace('            execActions', '            requestWorldContractAudit("reset_warmup_" + i, envTickCounter);\n            execActions')),
                     (step, '        if (isDiagnosticNoop(actions)) requestWorldContractAudit("noop_step_requested", envTickCounter);\n' + step)):
        if text.count(old) != 1:
            raise ValueError("unrecognized or already patched world-contract anchor")
        text = text.replace(old, new, 1)
    return text

