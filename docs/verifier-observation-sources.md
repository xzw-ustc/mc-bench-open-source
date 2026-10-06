# Verifier 主观测来源

MC-EvoBench V1 区分 agent 可见观测与 evaluator-only verifier 证据。Native Perception Track 可作为 agent 输入；Structured-State Track 用于 verifier、诊断或显式声明的 structured-state baseline。详细协议见 [observation-tracks.md](observation-tracks.md)。

当前 catalog 规模：80 tasks、19 chains、111 states、369 graph edges、4 mission events。

| Task | 主判定来源 | Track | Agent access | Verifier |
|------|------------|-------|--------------|----------|
| `scout_coal_source` | Ray observation, Grid observation, raw_observation | `structured_state` | `evaluator_only` | `any_of(...)` |
| `collect_log` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(oak_log >= 1)` |
| `craft_planks` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(oak_planks >= 4)` |
| `craft_table` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(crafting_table >= 1)` |
| `craft_wooden_pickaxe` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(wooden_pickaxe >= 1)` |
| `collect_coal` | inventory, raw_observation | `native_perception, structured_state` | `agent_visible, evaluator_only` | `inventory_at_least(coal >= 1)` |
| `craft_torch` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(torch >= 1)` |
| `build_lit_shelter` | Grid observation, player stats | `structured_state` | `evaluator_only` | `any_of(...)` |
| `survive_first_night` | player stats, mission flag | `structured_state, native_perception` | `evaluator_only, agent_visible` | `flag_is_true(night_survived)` |
| `mine_cobblestone` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(cobblestone >= 2)` |
| `craft_stone_sword` | inventory, equipped item | `native_perception` | `agent_visible` | `any_of(...)` |
| `defeat_zombie` | counter, raw_observation | `structured_state` | `evaluator_only` | `counter_at_least(zombie_defeated >= 1)` |
| `collect_dirt` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(dirt >= 1)` |
| `collect_sand` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(sand >= 1)` |
| `collect_gravel` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(gravel >= 1)` |
| `collect_flint` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(flint >= 1)` |
| `collect_seeds` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(wheat_seeds >= 1)` |
| `collect_flower` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(poppy >= 1)` |
| `craft_sticks` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(stick >= 4)` |
| `craft_chest` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(chest >= 1)` |
| `craft_oak_boat` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(oak_boat >= 1)` |
| `craft_wooden_axe` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(wooden_axe >= 1)` |
| `craft_wooden_sword` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(wooden_sword >= 1)` |
| `craft_wooden_shovel` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(wooden_shovel >= 1)` |
| `craft_furnace` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(furnace >= 1)` |
| `collect_iron_ore_basic` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(iron_ore >= 1)` |
| `smelt_iron_ingot` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(iron_ingot >= 1)` |
| `collect_birch_log` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(birch_log >= 1)` |
| `craft_birch_planks` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(birch_planks >= 4)` |
| `craft_birch_boat` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(birch_boat >= 1)` |
| `collect_spruce_log` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(spruce_log >= 1)` |
| `craft_spruce_planks` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(spruce_planks >= 4)` |
| `craft_spruce_boat` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(spruce_boat >= 1)` |
| `collect_jungle_log` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(jungle_log >= 1)` |
| `craft_jungle_planks` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(jungle_planks >= 4)` |
| `craft_jungle_boat` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(jungle_boat >= 1)` |
| `collect_acacia_log` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(acacia_log >= 1)` |
| `craft_acacia_planks` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(acacia_planks >= 4)` |
| `craft_acacia_boat` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(acacia_boat >= 1)` |
| `collect_dark_oak_log` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(dark_oak_log >= 1)` |
| `craft_dark_oak_planks` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(dark_oak_planks >= 4)` |
| `craft_dark_oak_boat` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(dark_oak_boat >= 1)` |
| `collect_clay_ball` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(clay_ball >= 1)` |
| `collect_cactus` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(cactus >= 1)` |
| `collect_sugar_cane` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(sugar_cane >= 1)` |
| `collect_apple` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(apple >= 1)` |
| `collect_pumpkin` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(pumpkin >= 1)` |
| `collect_melon_slice` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(melon_slice >= 1)` |
| `collect_red_mushroom` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(red_mushroom >= 1)` |
| `collect_brown_mushroom` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(brown_mushroom >= 1)` |
| `collect_string` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(string >= 1)` |
| `collect_bone` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(bone >= 1)` |
| `collect_iron_ore` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(iron_ore >= 1)` |
| `collect_gold_ore` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(gold_ore >= 1)` |
| `collect_redstone` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(redstone >= 1)` |
| `collect_lapis_lazuli` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(lapis_lazuli >= 1)` |
| `collect_diamond` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(diamond >= 1)` |
| `collect_emerald` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(emerald >= 1)` |
| `craft_bowl` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(bowl >= 1)` |
| `craft_ladder` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(ladder >= 1)` |
| `craft_oak_sign` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(oak_sign >= 1)` |
| `craft_oak_fence` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(oak_fence >= 1)` |
| `craft_oak_door` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(oak_door >= 1)` |
| `craft_oak_trapdoor` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(oak_trapdoor >= 1)` |
| `craft_oak_pressure_plate` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(oak_pressure_plate >= 1)` |
| `craft_stone_pickaxe` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(stone_pickaxe >= 1)` |
| `craft_stone_axe` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(stone_axe >= 1)` |
| `craft_stone_shovel` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(stone_shovel >= 1)` |
| `craft_stone_hoe` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(stone_hoe >= 1)` |
| `smelt_charcoal` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(charcoal >= 1)` |
| `smelt_stone` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(stone >= 1)` |
| `smelt_glass` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(glass >= 1)` |
| `smelt_gold_ingot` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(gold_ingot >= 1)` |
| `craft_iron_pickaxe` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(iron_pickaxe >= 1)` |
| `collect_white_wool` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(white_wool >= 1)` |
| `craft_white_bed` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(white_bed >= 1)` |
| `craft_bow` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(bow >= 1)` |
| `craft_shield` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(shield >= 1)` |
| `craft_bucket` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(bucket >= 1)` |
| `collect_water_bucket` | inventory | `native_perception` | `agent_visible` | `inventory_at_least(water_bucket >= 1)` |

## 保留的派生 Flag

`night_survived` 保留为派生 flag。它要求比较 stage 起止 observation 的存活状态、elapsed ticks 与夜晚时间窗，无法由单帧 snapshot 完整表达。对应规则定义在 `event:night_interval_survived` 中。

`coal_source_known` 与 `lit_shelter` 仍会作为 mission event 产生的图状态出现在报告中，但对应 task 的通过判定已经直接读取真实 observation path，不再依赖 flag。
