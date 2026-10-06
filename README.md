# MC-EvoBench

MC-EvoBench 是面向 Minecraft agent 的图结构能力链 benchmark，提供任务定义、环境配置、依赖校验、成功判定和评测报告。

**V1：80 个任务 · 19 条能力链 · 111 个状态 · 369 条图边 · 12 个环境配置 · 4 个评测 split。**

## 安装

Python 3.10：

```bash
python3.10 -m venv .venv
. .venv/bin/activate
python -m pip install 'setuptools==65.5.0' 'wheel==0.38.4'
python -m pip install --no-build-isolation -e .
```

## 校验与运行

以下命令在项目根目录执行：

```bash
mcbench validate benchmarks/v1
mcbench dry-run benchmarks/v1 cross_domain_safe_night
mcbench benchmark benchmarks/v1 --output-dir runs/catalog-check
mcbench run-config examples/run_scripted.json
mcbench run-suite-config examples/run_suite_scripted.json
```

`dry-run`、`benchmark` 和 scripted 环境使用合成 observation 检查评测流程，报告中的 `synthetic` 为 `true`。真实环境使用 `environment.kind: minerl`，安装与运行命令见 [环境配置](docs/runtime.md)。

`run-config` 执行一条能力链；`run-suite-config` 按 `chain_ids` 或 `split_ids` 批量执行。输出包含每条链的阶段判定、指标和 suite 的 `summary.json`。任务结果由 `completed` 与阶段 `status` 表示。

## 目录

```text
benchmarks/v1/       任务、状态、图边、能力链、split、环境和事件定义
src/mcbench/        图编译、runner、verifier、指标、报告、CLI 和适配接口
examples/           单链、批量与 MineRL 运行配置
scripts/linux/      固定版本的环境安装与 benchmark 插桩
environments/linux/ 环境依赖版本与 Docker 构建文件
tests/              Benchmark 单元测试
docs/               Benchmark 使用协议
```

- [Benchmark 定义](docs/benchmark.md)
- [评测指标](docs/metrics.md)
- [Agent 接入](docs/agent-integration.md)
- [观测协议](docs/observation-tracks.md)
- [各任务的判定来源](docs/verifier-observation-sources.md)
- [环境安装](docs/runtime.md)

## 开发测试

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q
```

## 许可证

[MIT](LICENSE)。
