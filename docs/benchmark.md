# Benchmark 定义

V1 的 7 份 JSON 是评测定义的唯一来源。

| 文件 | 内容 |
| --- | --- |
| `tasks.json` | 80 个任务的自然语言目标、步数预算、环境、成功谓词及观测来源 |
| `states.json` | 111 个物品、工具、环境及能力状态 |
| `edges.json` | 369 条关系边及数量、权重 |
| `chains.json` | 19 条官方能力链及初始状态、profile 策略 |
| `profiles.json` | 12 种公开问题实例：seed、时间、天气、初始背包及资源布局 |
| `mission_events.json` | 4 种观测事件、状态效果及终止/失败条件 |
| `splits.json` | 任务与能力链的评测分组 |

## Split

| Split | 任务数 | 链数 | 用途 |
| --- | ---: | ---: | --- |
| `core_progression` | 33 | 5 | 基础能力推进 |
| `transfer` | 31 | 4 | 配方、物品及结构迁移 |
| `supplementary_diversity` | 16 | 3 | 多样性与覆盖范围 |
| `calibration_and_probe` | 0 | 7 | 环境与判定流程校验，复用已有任务 |

三个正式 split 分别报告，校验 split 单列。`benchmark` 会检查全部 19 条链，因此其顶层汇总包含校验链；正式评测请通过 suite 选择前三个 split。

## 图与执行

`requires`、`produces`、`consumes` 是执行关系，参与 WGP；`enables` 表示软依赖假设，`abstracts_to` 表示分类关系，均不计入 WGP。链编译默认执行定性依赖校验；`compile_chain(..., strict_quantities=True)` 可执行额外的数量守恒审计。

Runner 逐阶段读取 observation，使用固定 success predicates 判定。达到成功条件进入下一阶段；失败、超时或环境终止则停止当前链。若初始 observation 已满足谓词，该阶段可在 0 步通过。

`profile_policy: chain` 在整条链中保持同一个世界。其他链在 `per_stage_profiles: true` 时可按任务 profile 重置环境；重置可能改变背包和世界状态。运行配置及此选项保存在报告中，跨设置的结果应分别说明。

## 公开环境条件

确定性资源布局是问题实例的一部分。稀有矿物可由 profile 放在公开定义的有限区域内，使任务聚焦观察、接近、采集、制作与后续复用。资源布局不应被改写成 agent 的隐藏坐标提示，成功必须由交互产生的观测证明。

Profile 的 `metadata` 记录资源与地形装饰、起点、时间控制等信息。环境适配层将配置转换为 MineRL/Malmo mission；具体 Java runtime 是否执行这些配置需单独验证，参见 [runtime.md](runtime.md)。

固定矿石环境在出生点脚下设置 3×3 石质平台，平台在空气清理之后生成，以保持配置的初始位置。平台与矿物布局共同构成公开问题实例。
