# 可替换的 openYuanRong 制品下载器

| 字段 | 值 |
|---|---|
| 编号 | AKERNEL-BUILD-20260814 |
| 状态 | 可实施 |
| 作者 | Codex |
| SIG / 模块 | AKernel Builder |
| 评审人 | AKernel 维护者 |
| 批准人 | ChamberlainJI |
| 创建日期 | 2026-08-14 |

## 摘要

将 `openyuanrong_core` wheel 与 RRT runtime 的来源选择、下载、校验和格式转换从 Dockerfile 内联命令迁移到两个路径稳定的下载脚本。公开仓库提供兼容现有 Release 和 URL/SHA 覆盖参数的默认实现；私有流水线可在构建前替换同路径脚本，从 OBS 等来源获取制品，而无需修改 Dockerfile、Makefile 或公共构建参数。

## 背景与动机

`builder/node.Dockerfile` 当前内联构造 Release core wheel URL，并在收到 URL/SHA 参数时切换到 daily wheel。`builder/runtime.Dockerfile` 同时承担 Release 裸 RRT binary 下载和 OBS RRT wheel 解包。两处 Dockerfile 因此了解制品仓库、命名、校验和打包格式，私有流水线也必须持续跟随这些实现细节。

### 目标

- Dockerfile 不再包含 openYuanRong Release 或 OBS 的下载分支；静态契约测试可判定这一点。
- core 下载器在目标目录中产生且仅产生一个 wheel，Dockerfile 验证后安装。
- RRT 下载器产生最终裸 runtime，Dockerfile 独立验证其为可执行 x86-64 ELF。
- 默认下载器保持现有 Release 下载、固定校验和以及 URL/SHA 覆盖行为。
- 流水线仅替换两个稳定路径下的脚本即可接管制品来源，并通过 Docker COPY 缓存边界使替换生效。

### 非目标

- 不改变 openYuanRong 版本、固定校验和、镜像布局或 runtime profile。
- 不引入 BuildKit named context、远程脚本执行或新的凭据传递机制。
- 不移除现有 `OPEN_YR_CORE_WHEEL_*`、`OPEN_YR_RRT_WHEEL_*` 兼容参数。
- 不修改 pause/resume compatibility patch 的选择语义。

## 方案概述

公开构建继续调用 `make build`，默认脚本按当前 Release 规则下载。需要 OBS 制品的流水线在 `docker build` 前用自己的实现覆盖：

```text
builder/downloaders/download-openyuanrong-core.sh
builder/downloaders/download-openyuanrong-rrt.sh
```

core 脚本接收目标目录，必须在目录顶层留下恰好一个 `.whl`。RRT 脚本接收目标文件路径，必须写入可供 Dockerfile 验证的裸 runtime。脚本是构建上下文中的源文件；覆盖脚本会改变 COPY 层摘要，不会命中旧下载层缓存。

### 风险与缓解措施

| 风险 | 缓解措施 |
|---|---|
| 私有脚本产生空目录或多个 wheel | Dockerfile 在安装前严格验证恰好一个普通 `.whl` 文件。 |
| 下载器绕过完整性校验 | 默认脚本保留固定 SHA-256；私有脚本被视为流水线构建代码，测试夹具要求其自行校验来源。 |
| RRT wheel 与裸 binary 格式混淆 | 下载器统一输出裸 runtime，Dockerfile 继续执行权限和 x86-64 ELF 检查。 |
| 脚本替换未使 Docker 缓存失效 | 每个 Dockerfile 在下载 RUN 前单独 COPY 对应脚本。 |

## 详细设计

### core 下载器契约

接口为：

```bash
download-openyuanrong-core.sh DEST_DIR
```

默认实现根据 `TARGETARCH` 或宿主架构选择 `x86_64`/`aarch64` wheel 与固定 Release SHA-256。`OPEN_YR_CORE_WHEEL_URL` 和 `OPEN_YR_CORE_WHEEL_SHA256` 必须同时为空或同时非空；非空时下载任意合法 `.whl` basename。所有下载使用现有 curl 重试策略，并在文件进入目标目录前完成 SHA-256 校验。

`node.Dockerfile` 创建空目标目录、执行脚本、通过 shell glob 验证恰好一个普通 `.whl`，然后保持现有 `pip --no-deps --target` 安装、`yr` 二进制检查和安装目录复制流程。

### RRT 下载器契约

接口为：

```bash
download-openyuanrong-rrt.sh DEST_FILE
```

默认实现未收到 wheel override 时下载 Release 裸 binary 并校验固定 SHA-256；收到成对的 `OPEN_YR_RRT_WHEEL_URL/SHA256` 时下载 wheel、校验并提取 `openyuanrong_rrt/rrt-runtime` 到目标文件。临时文件位于独立临时目录并通过 trap 清理，失败时不保留半成品目标。

`runtime.Dockerfile` 执行脚本后设置可执行权限，并保持现有 x86-64 ELF 检查。下载器负责“来源和格式”，Dockerfile 负责“镜像需要什么物理结果”。

### 兼容性和失败语义

现有 Makefile 与 `deploy/scripts/build-image.sh` 参数保持不变。默认构建生成与当前实现等价的网络请求和制品内容。参数不成对、未知架构、checksum 不匹配、wheel 缺少 RRT member、core 输出数量不为一或 RRT 非 ELF 时，构建立即失败。

私有脚本可定义自己的环境变量，但不能要求公共 Dockerfile 识别这些变量；流水线负责通过已有 Docker build 环境将变量提供给替换脚本。

### 测试计划

- 下载器单元测试使用本地 `file://` Release/OBS 夹具，验证默认 core、core URL override、默认裸 RRT、RRT wheel override 和 checksum 失败，不依赖公网。
- Dockerfile 契约测试验证两个下载器被 COPY 并执行，core 单 wheel 与 RRT ELF 防线存在，同时拒绝重新出现内联 openYuanRong curl 下载分支。
- 既有构建参数测试继续验证 URL/SHA 透传，确保升级不破坏现有流水线。
- Shell 语法检查覆盖新增脚本；最终以精简 Docker build 或等价 stage 构建验证容器内工具差异。

### 升级与回滚策略

升级不改变调用参数，默认构建无需调整。私有流水线可逐条覆盖脚本并独立验证。回滚只需恢复 Dockerfile 内联下载提交；制品版本和镜像运行时数据格式均未改变。

## 备选方案

- 单一 dispatcher 脚本：文件更少，但私有覆盖实现必须同时理解 core wheel 与 RRT 两种结果契约，扩大故障域。
- BuildKit named context：可以从外部注入脚本，但会要求所有构建入口切换到 buildx 特有接口，不符合现有 `docker build` 兼容目标。
- 仅保留 URL/SHA build args：现状已经支持，但流水线仍需跟随 Dockerfile 内部的 Release/OBS 格式分支，不能满足无侵入替换需求。

## 实施历史

- 2026-08-14：方案批准并进入实施。
