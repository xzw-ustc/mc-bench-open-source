# Minecraft 环境

## 版本

| 组件 | 版本 |
| --- | --- |
| Python | 3.10 |
| Java | 8 |
| Minecraft | 1.16.5 |
| MineRL | 1.0.2，revision `e87751e2f5e631d52153cafd6ca3e86190e2672a` |
| MCP-Reborn | revision `1e71be5bd4c49bc4d6ab0ee559c31b298b7697a3` |
| Gym | 0.23.1 |
| NumPy | 1.23.5 |

源码版本与 Java 补丁校验值在 `environments/linux/runtime-lock.json`，Python 依赖在 `environments/linux/requirements.txt`。

## Linux 安装

激活项目的 Python 3.10 虚拟环境，并在系统中安装 Java 8、编译工具、Git、Xvfb 和 OpenGL 库后执行：

```bash
bash scripts/linux/install_runtime.sh
xvfb-run -a mcbench run-config examples/run_minerl.json
```

安装器将固定 revision 的源码下载至 `.runtime/minerl`，安装依赖并编译 benchmark 的 Java 插桩。

## Docker 构建与运行

```bash
docker build -f environments/linux/Dockerfile -t mcbench-minerl:1.0.0 .
docker run --rm mcbench-minerl:1.0.0
mkdir -p runs
docker run --rm -e MCBENCH_XVFB=1 \
  -v "$PWD/runs:/workspace/mc-bench/runs" \
  mcbench-minerl:1.0.0 \
  python -m mcbench.cli run-config examples/run_minerl.json
```

镜像安装固定 revision 的 MineRL 与 MCP-Reborn，应用 benchmark 补丁并编译 Java。MineRL、Minecraft 和 MCP-Reborn 作为独立依赖下载，各自适用其上游许可证。构建需要访问上游源码、Python 包和 Minecraft 构建资源。

`examples/run_minerl.json` 使用 noop 动作运行 5 步，用于检查 reset、step、observation 和报告链路；其任务结果仍由正常 verifier 判定。接入 agent 时按 [Agent 接入](agent-integration.md) 设置 `agent` 字段，并在镜像中安装对应 policy 包。

`MCBENCH_XVFB=1` 启用虚拟显示器。`mcbench doctor` 检查 Python 模块和 Java 可执行文件的可用性。

## 环境语义

Benchmark 补丁实现 profile 的时间、天气、刷怪规则、固定位置、资源绘制、chunk 同步、ray/grid 和光照观测。安装器检查补丁前后的 Java 源码 SHA-256；未知源码版本会直接报错。

固定位置由服务端设置，reset 检查位置和视角。配置资源的 chunk 在初始放置时同步到客户端。环境日志中的 world-contract 记录用于检查资源与世界状态，不作为 agent 的观测输入。

## 核心检查容器

```bash
docker build -f environments/linux/Dockerfile.benchmark -t mcbench-core:1.0.0 .
docker run --rm mcbench-core:1.0.0
docker run --rm mcbench-core:1.0.0 python -m pytest -q
```

核心检查容器运行 catalog 与合成评测流程。
