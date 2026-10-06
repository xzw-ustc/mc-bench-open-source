#!/usr/bin/env python3
"""Patch MineRL's MCP-Reborn runtime with MC-EvoBench instrumentation.

The MineRL 1.16 MCP-Reborn env server accepts Malmo mission XML containing
Time, ObservationFromGrid, ObservationFromRay, and DrawingDecorator handlers,
but the stock server only wires a small subset of observations into the Gym
info payload.  This patch implements the missing runtime behavior used by the
benchmark reset probes.
"""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_ROOT = (
    "/opt/mcbench-venv/lib/python3.10/site-packages/minerl/MCP-Reborn"
)


IMPORTS = """\
import net.minecraft.block.Block;
import net.minecraft.block.BlockState;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.BlockRayTraceResult;
import net.minecraft.util.math.RayTraceContext;
import net.minecraft.util.math.RayTraceResult;
import net.minecraft.util.math.vector.Vector3d;
import net.minecraft.world.LightType;
import net.minecraft.world.World;
import net.minecraft.world.server.ServerWorld;
import javax.xml.bind.JAXBElement;
"""


HELPERS = r'''
    private void applyMissionWorldSetup(Minecraft mc, MissionInit missionInit) {
        applyMissionTime(mc, missionInit);
        applyDrawingDecorators(mc, missionInit);
    }

    private void applyMissionTime(Minecraft mc, MissionInit missionInit) {
        ServerInitialConditions conditions = getServerInit(missionInit);
        if (conditions == null || conditions.getTime() == null) {
            return;
        }
        Time time = conditions.getTime();
        Integer startTime = time.getStartTime();
        if (startTime == null) {
            return;
        }
        boolean allowTime = time.isAllowPassageOfTime() == null || time.isAllowPassageOfTime();
        MinecraftServer server = mc.getIntegratedServer();
        if (server == null) {
            return;
        }
        for (ServerWorld world : server.getWorlds()) {
            world.setDayTime(startTime.longValue());
            world.getGameRules().get(GameRules.DO_DAYLIGHT_CYCLE).set(allowTime, server);
        }
        if (mc.world != null) {
            mc.world.setDayTime(startTime.longValue());
        }
    }

    private void applyDrawingDecorators(Minecraft mc, MissionInit missionInit) {
        MinecraftServer server = mc.getIntegratedServer();
        if (server == null || missionInit.getMission().getServerSection().getServerHandlers() == null) {
            return;
        }
        ServerWorld world = server.func_241755_D_();
        for (Object decorator : missionInit.getMission().getServerSection().getServerHandlers().getWorldDecorators()) {
            if (!(decorator instanceof DrawingDecorator)) {
                continue;
            }
            DrawingDecorator drawingDecorator = (DrawingDecorator) decorator;
            for (JAXBElement<? extends DrawObjectType> element : drawingDecorator.getDrawObjectType()) {
                DrawObjectType drawObject = element.getValue();
                if (drawObject instanceof DrawBlock) {
                    DrawBlock block = (DrawBlock) drawObject;
                    setWorldBlock(world, block.getX(), block.getY(), block.getZ(), block.getType().value(),
                            block.getVariant() == null ? null : block.getVariant().getValue());
                } else if (drawObject instanceof DrawCuboid) {
                    DrawCuboid cuboid = (DrawCuboid) drawObject;
                    int minX = Math.min(cuboid.getX1(), cuboid.getX2());
                    int maxX = Math.max(cuboid.getX1(), cuboid.getX2());
                    int minY = Math.min(cuboid.getY1(), cuboid.getY2());
                    int maxY = Math.max(cuboid.getY1(), cuboid.getY2());
                    int minZ = Math.min(cuboid.getZ1(), cuboid.getZ2());
                    int maxZ = Math.max(cuboid.getZ1(), cuboid.getZ2());
                    for (int x = minX; x <= maxX; x++) {
                        for (int y = minY; y <= maxY; y++) {
                            for (int z = minZ; z <= maxZ; z++) {
                                setWorldBlock(world, x, y, z, cuboid.getType().value(),
                                        cuboid.getVariant() == null ? null : cuboid.getVariant().getValue());
                            }
                        }
                    }
                }
            }
        }
    }

    private void setWorldBlock(ServerWorld world, int x, int y, int z, String blockName, String variant) {
        Block block = Registry.BLOCK.getOrDefault(new ResourceLocation(normalizeBlockName(blockName, variant)));
        world.setBlockState(new BlockPos(x, y, z), block.getDefaultState(), 3);
    }

    private void addWorldStats(JsonObject infoJson, Minecraft mc) {
        if (mc.world == null || mc.player == null) {
            return;
        }
        World world = mc.world;
        BlockPos pos = mc.player.getPosition();
        int skyLight = world.getLightFor(LightType.SKY, pos);
        int blockLight = world.getLightFor(LightType.BLOCK, pos);
        float sunBrightness = mc.world.getSunBrightness(1.0F);
        int effectiveSkyLight = Math.round(skyLight * sunBrightness);
        int effectiveLight = Math.max(blockLight, effectiveSkyLight);
        infoJson.addProperty("world_time", world.getDayTime() % 24000L);
        infoJson.addProperty("total_time", world.getGameTime());
        infoJson.addProperty("light_level", effectiveLight);
        infoJson.addProperty("effective_light_level", effectiveLight);
        infoJson.addProperty("sky_light_level", skyLight);
        infoJson.addProperty("effective_sky_light_level", effectiveSkyLight);
        infoJson.addProperty("block_light_level", blockLight);
        infoJson.addProperty("skylight_subtracted", world.getSkylightSubtracted());
        infoJson.addProperty("can_see_sky", world.canBlockSeeSky(pos));
        infoJson.addProperty("is_alive", mc.player.isAlive());
        infoJson.addProperty("sun_brightness", sunBrightness);
    }

    private void addGridObservations(JsonObject infoJson, Minecraft mc) {
        if (mc.world == null || mc.player == null) {
            return;
        }
        getAgentHandlers().filter(h -> h instanceof ObservationFromGrid).forEach(h -> {
            ObservationFromGrid observation = (ObservationFromGrid) h;
            for (GridDefinition grid : observation.getGrid()) {
                JsonArray blocks = new JsonArray();
                BlockPos origin = grid.isAbsoluteCoords() ? new BlockPos(0, 0, 0) : mc.player.getPosition();
                int minX = Math.round(grid.getMin().getX());
                int maxX = Math.round(grid.getMax().getX());
                int minY = Math.round(grid.getMin().getY());
                int maxY = Math.round(grid.getMax().getY());
                int minZ = Math.round(grid.getMin().getZ());
                int maxZ = Math.round(grid.getMax().getZ());
                for (int y = Math.min(minY, maxY); y <= Math.max(minY, maxY); y++) {
                    for (int z = Math.min(minZ, maxZ); z <= Math.max(minZ, maxZ); z++) {
                        for (int x = Math.min(minX, maxX); x <= Math.max(minX, maxX); x++) {
                            BlockPos pos = grid.isAbsoluteCoords()
                                    ? new BlockPos(x, y, z)
                                    : origin.add(x, y, z);
                            blocks.add(blockName(mc.world.getBlockState(pos)));
                        }
                    }
                }
                infoJson.add(grid.getName(), blocks);
            }
        });
    }

    private void addRayObservation(JsonObject infoJson, Minecraft mc) {
        if (mc.world == null || mc.player == null) {
            return;
        }
        boolean wantsRay = getAgentHandlers().anyMatch(h -> h instanceof ObservationFromRay);
        if (!wantsRay) {
            return;
        }
        Vector3d start = mc.player.getEyePosition(1.0F);
        Vector3d look = mc.player.getLook(1.0F);
        Vector3d end = start.add(look.x * 64.0D, look.y * 64.0D, look.z * 64.0D);
        BlockRayTraceResult result = mc.world.rayTraceBlocks(
                new RayTraceContext(start, end, RayTraceContext.BlockMode.OUTLINE, RayTraceContext.FluidMode.NONE, mc.player)
        );
        JsonObject lineOfSight = new JsonObject();
        if (result.getType() == RayTraceResult.Type.BLOCK) {
            BlockState state = mc.world.getBlockState(result.getPos());
            lineOfSight.addProperty("type", blockName(state));
            lineOfSight.addProperty("distance", start.distanceTo(result.getHitVec()));
            lineOfSight.addProperty("x", result.getPos().getX());
            lineOfSight.addProperty("y", result.getPos().getY());
            lineOfSight.addProperty("z", result.getPos().getZ());
        }
        infoJson.add("LineOfSight", lineOfSight);
    }

    private String blockName(BlockState state) {
        ResourceLocation key = Registry.BLOCK.getKey(state.getBlock());
        return key == null ? state.getBlock().toString() : key.toString();
    }

    private String normalizeBlockName(String blockName, String variant) {
        if (blockName == null || blockName.isEmpty()) {
            return "minecraft:air";
        }
        if ("log".equals(blockName) && variant != null) {
            return "minecraft:" + variant + "_log";
        }
        if ("log2".equals(blockName) && variant != null) {
            return "minecraft:" + variant + "_log";
        }
        if ("grass".equals(blockName)) {
            return "minecraft:grass_block";
        }
        if ("reeds".equals(blockName)) {
            return "minecraft:sugar_cane";
        }
        return blockName.contains(":") ? blockName : "minecraft:" + blockName;
    }

'''


def patch_env_server(root: Path) -> None:
    path = root / "src/main/java/com/minerl/multiagent/env/EnvServer.java"
    text = path.read_text(encoding="utf-8")
    if "applyMissionWorldSetup" in text:
        text = text.replace(
            "setWorldBlock(world, block.getX(), block.getY(), block.getZ(), block.getType().value());",
            "setWorldBlock(world, block.getX(), block.getY(), block.getZ(), block.getType().value(),\n"
            "                            block.getVariant() == null ? null : block.getVariant().getValue());",
        )
        text = text.replace(
            "setWorldBlock(world, x, y, z, cuboid.getType().value());",
            "setWorldBlock(world, x, y, z, cuboid.getType().value(),\n"
            "                                        cuboid.getVariant() == null ? null : cuboid.getVariant().getValue());",
        )
        text = text.replace(
            "private void setWorldBlock(ServerWorld world, int x, int y, int z, String blockName) {\n"
            "        Block block = Registry.BLOCK.getOrDefault(new ResourceLocation(normalizeBlockName(blockName)));",
            "private void setWorldBlock(ServerWorld world, int x, int y, int z, String blockName, String variant) {\n"
            "        Block block = Registry.BLOCK.getOrDefault(new ResourceLocation(normalizeBlockName(blockName, variant)));",
        )
        text = text.replace(
            "private String normalizeBlockName(String blockName) {\n"
            "        if (blockName == null || blockName.isEmpty()) {\n"
            "            return \"minecraft:air\";\n"
            "        }\n"
            "        return blockName.contains(\":\") ? blockName : \"minecraft:\" + blockName;\n"
            "    }",
            "private String normalizeBlockName(String blockName, String variant) {\n"
            "        if (blockName == null || blockName.isEmpty()) {\n"
            "            return \"minecraft:air\";\n"
            "        }\n"
            "        if ((\"log\".equals(blockName) || \"log2\".equals(blockName)) && variant != null) {\n"
            "            return \"minecraft:\" + variant + \"_log\";\n"
            "        }\n"
            "        if (\"grass\".equals(blockName)) {\n"
            "            return \"minecraft:grass_block\";\n"
            "        }\n"
            "        if (\"reeds\".equals(blockName)) {\n"
            "            return \"minecraft:sugar_cane\";\n"
            "        }\n"
            "        return blockName.contains(\":\") ? blockName : \"minecraft:\" + blockName;\n"
            "    }",
        )
        text = text.replace(
            "        infoJson.addProperty(\"world_time\", world.getDayTime() % 24000L);\n"
            "        infoJson.addProperty(\"total_time\", world.getGameTime());\n"
            "        infoJson.addProperty(\"light_level\", world.getLightSubtracted(pos, 0));\n"
            "        infoJson.addProperty(\"sky_light_level\", world.getLightFor(LightType.SKY, pos));\n"
            "        infoJson.addProperty(\"block_light_level\", world.getLightFor(LightType.BLOCK, pos));\n"
            "        infoJson.addProperty(\"can_see_sky\", world.canBlockSeeSky(pos));\n"
            "        infoJson.addProperty(\"is_alive\", mc.player.isAlive());\n"
            "        infoJson.addProperty(\"sun_brightness\", world.getBrightness(pos));\n",
            "        int skyLight = world.getLightFor(LightType.SKY, pos);\n"
            "        int blockLight = world.getLightFor(LightType.BLOCK, pos);\n"
            "        float sunBrightness = mc.world.getSunBrightness(1.0F);\n"
            "        int effectiveSkyLight = Math.round(skyLight * sunBrightness);\n"
            "        int effectiveLight = Math.max(blockLight, effectiveSkyLight);\n"
            "        infoJson.addProperty(\"world_time\", world.getDayTime() % 24000L);\n"
            "        infoJson.addProperty(\"total_time\", world.getGameTime());\n"
            "        infoJson.addProperty(\"light_level\", effectiveLight);\n"
            "        infoJson.addProperty(\"effective_light_level\", effectiveLight);\n"
            "        infoJson.addProperty(\"sky_light_level\", skyLight);\n"
            "        infoJson.addProperty(\"effective_sky_light_level\", effectiveSkyLight);\n"
            "        infoJson.addProperty(\"block_light_level\", blockLight);\n"
            "        infoJson.addProperty(\"skylight_subtracted\", world.getSkylightSubtracted());\n"
            "        infoJson.addProperty(\"can_see_sky\", world.canBlockSeeSky(pos));\n"
            "        infoJson.addProperty(\"is_alive\", mc.player.isAlive());\n"
            "        infoJson.addProperty(\"sun_brightness\", sunBrightness);\n",
        )
        path.write_text(text, encoding="utf-8")
        return

    text = text.replace(
        "import java.util.*;\n",
        "import java.util.*;\n" + IMPORTS,
    )
    text = text.replace(
        "        mc.execute(() -> setAgentInventory(mc.player, missionInit));\n"
        "        mc.execute(() -> setAgentPosition(mc.player, missionInit));\n",
        "        mc.execute(() -> setAgentInventory(mc.player, missionInit));\n"
        "        mc.execute(() -> setAgentPosition(mc.player, missionInit));\n"
        "        mc.execute(() -> applyMissionWorldSetup(mc, missionInit));\n",
    )
    text = text.replace(
        "            getAgentHandlers().filter(h -> h instanceof ObservationFromFullStats).limit(1)\n"
        "                    .forEach(h -> {\n"
        "                        JSONWorldDataHelper.buildAllStats(infoJson, mc.player);\n"
        "                    });\n",
        "            getAgentHandlers().filter(h -> h instanceof ObservationFromFullStats).limit(1)\n"
        "                    .forEach(h -> {\n"
        "                        JSONWorldDataHelper.buildAllStats(infoJson, mc.player);\n"
        "                        addWorldStats(infoJson, mc);\n"
        "                    });\n"
        "            addGridObservations(infoJson, mc);\n"
        "            addRayObservation(infoJson, mc);\n",
    )
    text = text.replace(
        "    public static JsonArray getInventoryJson() {\n",
        HELPERS + "    public static JsonArray getInventoryJson() {\n",
    )
    path.write_text(text, encoding="utf-8")


def patch_launch_client(root: Path) -> None:
    path = root / "launchClient.sh"
    text = path.read_text(encoding="utf-8")
    patched = (
        "java -Xmx$maxMem -cp build/classes/java/main:$fatjar "
        "net.minecraft.client.main.Main --envPort=$port"
    )
    if patched in text:
        return
    text = text.replace(
        "java -Xmx$maxMem -jar $fatjar --envPort=$port",
        patched,
    )
    path.write_text(text, encoding="utf-8")


def patch_block_type(root: Path) -> None:
    """Accept modern profile names in the legacy JAXB block enum.

    Without these entries unmarshalling returns a null block type, aborting
    DrawingDecorator midway (even when a partial reset passes acceptance).
    Keep the frozen profile XML unchanged and extend the runtime protocol.
    """
    path = root / "src/main/java/com/microsoft/Malmo/Schemas/BlockType.java"
    text = path.read_text(encoding="utf-8")
    marker = "public enum BlockType {"
    if marker not in text:
        raise RuntimeError(f"Unrecognized BlockType enum: {path}")
    for name in ("poppy", "melon"):
        if f'@XmlEnumValue("{name}")' not in text:
            text = text.replace(marker, marker + f'\n    @XmlEnumValue("{name}")\n    MCBENCH_{name.upper()}("{name}"),', 1)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    root = Path(os.environ.get("MCP_REBORN_ROOT", DEFAULT_ROOT))
    patch_env_server(root)
    patch_launch_client(root)
    patch_block_type(root)


if __name__ == "__main__":
    main()
