# AKernel Standalone RRT Pause/Resume 端到端验证设计

| 字段 | 值 |
|---|---|
| 编号 | AKERNEL-PR-E2E-001 |
| 状态 | 草案 |
| 作者 | ChamberlainJI、Codex |
| SIG / 模块 | AKernel Builder、Standalone、YuanRong Sandbox |
| 评审人 | AKernel 与 YuanRong pause/resume 维护者 |
| 批准人 | AKernel 仓库维护者 |
| 创建日期 | 2026-08-12 |

## 摘要

本方案为 AKernel all-in-one 镜像增加条件式 x86_64 RRT runtime 能力，并在 standalone
模式显式启用 YuanRong pause/resume 数据面，使 `openyuanrong-sandbox` SDK 能从
`Sandbox.pause()` / `Sandbox.resume()` 一路验证到 FunctionSystem、DataSystem、
sandboxd 和 runsc。默认镜像与默认启动行为保持不变；首轮验证固定为单节点、runsc 和
DataSystem，并以 pause 前后台进程在 resume 后继续运行为核心成功证据。

## 背景与动机

AKernel 当前 builder 只生成四套 Python runtime rootfs，service metadata 中没有 RRT；
当前 `src/sandboxd` gitlink也不包含 Checkpoint/Restore RPC。用户已经通过 Buildkite #215
构建出包含 pause/resume 功能的 YuanRong core、RRT 和 Sandbox SDK，但实物核验确认该
core wheel 的 process-mode 脚本没有暴露 feature gate、snapshot backend 和共享
checkpoint root。若只替换 core wheel，standalone 的 pause/resume 仍保持默认关闭，且
默认 checkpoint 路径不在 sandboxd 管理根下。本设计用于补齐这些可验证的集成缺口，
形成从公开 SDK 到恢复后进程连续性的完整闭环。

### 目标

- 在 Linux x86_64 上用 checksum-pinned #215 core 与 RRT 构建 AKernel all-in-one 镜像。
- 默认不广告缺失的 RRT service，也不默认开启 pause/resume feature gate。
- 显式启用后，让 FunctionAgent、RuntimeManager 与 sandboxd 使用同一受控 checkpoint
  root，并用真实 DataSystem SnapshotStorage 完成上传与下载。
- 从 `yr_sandbox.Sandbox` 完成两轮 pause/resume，并证明相同 sandbox ID、文件内容和
  pause 前进程均连续。
- 产出可关联 SDK request/snapshot ID、控制面日志、DataSystem 和 runsc 的脱敏证据。

### 非目标

- 不在首轮验证 Kubernetes/CCE、多节点迁移或跨节点 Resume。
- 不在首轮验证 OBS、进程重启后的持久化恢复或 snapshot GC。
- 不宣称 pause/resume 已达到生产就绪状态。
- 不修改 `akernel_sdk.Sandbox` 公共 API；本轮客户端入口是 YuanRong 的
  `yr_sandbox.Sandbox`。
- 不把 RRT 与 Rust FunctionSystem 混为一谈。控制面继续使用 Buildkite #215 的 C++
  FunctionSystem；RRT 仅指 sandbox 内运行的 Rust runtime daemon。

## 方案概述

Linux x86_64 操作者向现有 `make build` 同时提供 core wheel 与 RRT wheel 的 URL/SHA，
builder 校验并把 RRT 安装进 EROFS rootfs，再选择包含 `rrt` slot 的 service metadata。
node image 对 #215 process 脚本应用上下文严格匹配的兼容 patch。镜像启动时只有
`AKERNEL_ENABLE_PAUSE_RESUME=true` 才向 YuanRong 传 gate、DataSystem backend 和
sandboxd 管理根下的 checkpoint path。宿主机 E2E runner 安装同一 Buildkite 构建的
Sandbox SDK，执行下面的完整数据流：

```text
openyuanrong-sandbox SDK（宿主机）
  -> Frontend HTTP API
  -> FunctionProxy（合并 FunctionAgent/RuntimeManager）
  -> sandboxd Checkpoint/Restore RPC
  -> runsc checkpoint/restore
  -> DataSystem SnapshotStorage
  -> RRT 恢复并重新建立 RuntimeRPC/直连路由
```

该方案遵循 YuanRong `2026-08-10-pause-resume-agent-data-plane-design.md` 的同版本组件、
默认关闭 feature gate、真实 SnapshotStorage、确定性 Resume 和可追踪诊断原则。

### 用户故事

作为 pause/resume 功能开发者，我希望在一台普通 x86 Linux 服务器上用同一组 Buildkite
artifact 构建并启动 AKernel，然后从 Sandbox SDK 发起 pause/resume，从而判断完整链路
是否保持运行中 agent 工作负载的进程和文件状态。

### 约束与注意事项

- 最终 runsc checkpoint/restore 只能在 privileged Linux x86_64 环境验证；macOS 只做
  builder、wheel 和镜像静态检查。
- RRT wheel 是 Python ABI 无关的原生二进制载体，不属于 cp310/cp311/cp312/cp313 SDK
  wheel 集合。
- #215 先用于 bring-up；若命中其后的 FunctionSystem teardown 修复，必须整组重建，
  不能混用不同顶层提交的二进制。

### 风险与缓解措施

| 风险 | 缓解措施 |
|---|---|
| #215 process 脚本未接线导致 feature 实际未开启 | compatibility patch 上下文不匹配即构建失败；启动后检查真实进程 argv |
| checkpoint path 越过 sandboxd 管理根 | 固定为 `/home/akernel/sandboxd/root/checkpoints`，禁止外部覆盖 |
| 默认镜像误广告 RRT | 只有 RRT wheel URL/SHA 成对存在时选择 RRT services 配置 |
| #215 缺少后续 self-await 修复 | bring-up 记录问题；最终通过前从同一新顶层提交整组重建和复测 |
| 诊断包泄露 token 或云凭据 | 只收集允许列表中的日志和元数据，并在落盘前脱敏 |

## 详细设计

### 已核验基线

#### Buildkite #215 产物

构建链接：<https://buildkite.com/openyuanrong/yuanrong-jcl/builds/215/list>

| 产物 | URL | SHA-256 | 用途 |
| --- | --- | --- | --- |
| `openyuanrong-core` | `https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/daily/20260811190323/linux/amd64/openyuanrong_core-0.7.0%2B6dfa49681774-py3-none-manylinux_2_31_x86_64.whl` | `39ba1cf8323ac4e784117867ecd806ec392da05aa2fd87130f8830eb56310895` | Frontend、C++ FunctionSystem、DataSystem、FaaS 控制面 |
| `openyuanrong-rrt` | `https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/daily/20260811184249/linux/amd64/openyuanrong_rrt-0.7.0%2B6dfa49681774-py3-none-manylinux_2_31_x86_64.whl` | `51e16a48a98ff89497e268e939ae046205c9ba287e8b0b571eec3048e6d38ae7` | rootfs 内的 x86_64 `rrt-runtime` |
| `openyuanrong-sandbox` | `https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/daily/20260811184237/linux/noarch/openyuanrong_sandbox-0.10.1.dev36-py3-none-any.whl` | `ef8985f11d3189fe9d70866614b3a8c3060bc62450bd0a3379e9117599aac190` | 主机侧 E2E 客户端 |

三项产物均来自 YuanRong 顶层提交 `6dfa49681774`。#215 中对应子模块为：

- Frontend `d00ba4b7f9036a299d35850b0a299c8777996afb`
- FunctionSystem `6fac483a20edabb21d0f1e48789d02ec11c7c9bc`
- Sandbox SDK `9176fcfdd11bff4c7c59d408bf7602f6db05c1d7`

RRT wheel 已验证为 `py3-none-manylinux_2_31_x86_64`，内部仅携带 Python 辅助模块和
原生 `rrt-runtime`。它不使用 CPython ABI，因此不需要为 cp310、cp312、cp313 分别
重建 wheel。现有四套 Python runtime 保持不变；RRT 作为第五个独立 service slot 加入。

#### 已发现的 process-mode 缺口

#215 core wheel 内实际打包的是旧式静态链接 `yr` CLI。它把未知参数继续传给
`deploy/process/config.sh`，但 #215 的 process 脚本尚未声明或传递以下配置：

- `enable_sandbox_pause_resume`
- `snapshot_storage_backend`
- 可覆盖的 `checkpoint_dir`

同时，#215 `functionsystem/deploy/install.sh` 只给独立 FunctionAgent/RuntimeManager 传
默认 checkpoint root，没有给 standalone 使用的合并 FunctionProxy 传上述参数。因此，
仅替换 core wheel 和添加 RRT 后，pause/resume 仍会因 feature gate 默认关闭而不可用。

这个缺口只影响 process/standalone 部署接线，不否定 #215 已编译出的 Frontend、
FunctionSystem、RRT 和 SDK 功能。

#### sandboxd 基线

AKernel 当前 `src/sandboxd` gitlink 尚不包含 Checkpoint/Restore RPC。实现阶段应将该
gitlink 更新到已验证的 checkpoint 分支提交，而不是从同级未跟踪的 `sandboxd/` 工作树
复制文件。目标实现必须保留以下契约：

- `CheckpointRequest`: `sandbox_id=1`, `checkpoint_dir=2`
- `RestoreRequest`: `config=1`, `checkpoint_dir=2`
- `RestoreResponse`: `sandbox_id=1`
- 只允许 `runsc` checkpoint/restore
- checkpoint 目录必须位于 sandboxd 管理根之下

### 构建设计

#### 新增构建输入

在 `Makefile`、`deploy/scripts/build-image.sh` 和 Docker build args 中新增成对输入：

- `OPEN_YR_RRT_WHEEL_URL`
- `OPEN_YR_RRT_WHEEL_SHA256`

规则如下：

1. 两者必须同时为空或同时非空。
2. URL 必须解析为 `.whl` 文件名。
3. 下载后先校验 SHA-256，再解包/安装。
4. 当前仅接受 `linux/amd64`；非 amd64 构建在 RRT 输入非空时立即失败。
5. 是否携带 RRT 是镜像构建能力；是否开启 pause/resume 是运行时开关，两者不能合并成
   一个默认开启的行为。

#### runtime rootfs

`builder/runtime.Dockerfile` 在收到 RRT 输入时：

1. 下载并校验 wheel。
2. 将 `rrt-runtime` 安装到稳定路径
   `/opt/openyuanrong-rrt/rrt-runtime`。
3. 校验文件可执行并用 `file`/ELF header 验证目标为 x86_64。
4. 继续用现有 `mkfs.erofs` 生成单一 `yr-runtime-rootfs.img`。

RRT 启动不依赖某个 CPython venv，避免把 RRT 误绑到 py310/py311。Python 仅保留给
现有 Python service slots 和 rootfs 基础工具。

#### service metadata

新增 RRT 版本的 services 配置，保留现有 `yr_services.yaml` 作为无 RRT 默认值。RRT
配置新增：

```yaml
rrt:
  runtime: rust
  rootfs:
    runtime: runsc
    type: local
    path: /home/yuanrong/yr-runtime-rootfs.img
    readonly: false
    mountpoint: /var/task/code
  bootstrap:
    type: erofs
    root: /home/yuanrong/yr-runtime-rootfs.img
    entrypoint: /__yuanrong/usr/bin/tini-static -- /__yuanrong/opt/openyuanrong-rrt/rrt-runtime
```

`builder/node.Dockerfile` 只在 RRT wheel 能力存在时选择该配置，避免普通镜像广告一个实际
不存在的 `default/0-defaultservice-rrt/$latest`。

#### #215 process 接线兼容层

新增版本化 patch 文件，在 node image 安装完 checksum-pinned core wheel 后、仅对 RRT
能力构建应用。patch 必须精确修改并校验两处上游脚本：

1. `deploy/process/config.sh`
   - 声明、解析、校验并 export gate/backend/checkpoint 参数。
2. `functionsystem/deploy/install.sh`
   - checkpoint root 可由 process 配置覆盖；
   - 合并 FunctionProxy 获取 gate、backend、checkpoint root、DataSystem 地址；
   - 非合并模式只把这些配置交给 FunctionAgent/RuntimeManager，不泄露 OBS 凭据给
     FunctionProxy。

patch 上下文不匹配必须让 Docker build 失败，禁止静默构建一个实际未启用 pause/resume
的镜像。后续整组 YuanRong artifact 原生包含这些接线时，删除兼容 patch 及其条件分支。

#### x86 构建入口

实现完成后，Linux x86_64 服务器使用一条显式、可复现的构建命令：

```bash
make build \
  IMAGE_REPOSITORY=akernel-all-in-one \
  IMAGE_TAG=pause-resume-215 \
  OPEN_YR_CORE_WHEEL_URL='https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/daily/20260811190323/linux/amd64/openyuanrong_core-0.7.0%2B6dfa49681774-py3-none-manylinux_2_31_x86_64.whl' \
  OPEN_YR_CORE_WHEEL_SHA256='39ba1cf8323ac4e784117867ecd806ec392da05aa2fd87130f8830eb56310895' \
  OPEN_YR_RRT_WHEEL_URL='https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/daily/20260811184249/linux/amd64/openyuanrong_rrt-0.7.0%2B6dfa49681774-py3-none-manylinux_2_31_x86_64.whl' \
  OPEN_YR_RRT_WHEEL_SHA256='51e16a48a98ff89497e268e939ae046205c9ba287e8b0b571eec3048e6d38ae7'
```

构建前必须初始化递归 submodule；构建输出只产生选定的
`akernel-all-in-one:pause-resume-215` 引用，不额外创建隐式 alias。

### 运行时设计

#### 默认关闭

standalone 新增单一外部开关：

```bash
AKERNEL_ENABLE_PAUSE_RESUME=true ./deploy/standalone/start.sh
```

默认值为 `false`。`start.sh` 把该值传入 all-in-one 容器，`yuanrong.service` 明确允许该
环境变量，`yr_node_bootstrap.sh` 仅在值为 `true` 时追加：

```text
--enable_sandbox_pause_resume true
--snapshot_storage_backend datasystem
--checkpoint_dir /home/akernel/sandboxd/root/checkpoints
```

首轮 standalone 不开放任意 backend 或任意 checkpoint path，以缩小配置面。无 RRT
能力的镜像收到 `AKERNEL_ENABLE_PAUSE_RESUME=true` 时应在启动早期给出明确错误，而不是
启动后等待首个 pause 请求失败。

#### 共享 checkpoint root

固定 checkpoint root：

```text
/home/akernel/sandboxd/root/checkpoints
```

理由：standalone 把宿主机 `deploy/standalone/data/` 挂载到容器
`/home/akernel`；sandboxd `rootDir` 是 `/home/akernel/sandboxd/root`，其 checkpoint
artifact manager 只接受该 root 下的路径。FunctionAgent、RuntimeManager 和 sandboxd
必须看到完全相同的绝对路径，不能使用 YuanRong process 默认的
`/home/yuanrong/checkpoints`，也不能用 symlink 绕过路径所有权校验。

#### SnapshotStorage

首轮使用同容器 DataSystem worker：

```text
host = 127.0.0.1（或 process 脚本解析出的本节点 IP）
port = 31501（沿用实际 DS_WORKER_PORT）
backend = datasystem
```

不需要 OBS 凭据。Pause 时 FunctionAgent 读取本地 runsc checkpoint artifact，上传为以
snapshot/request ID 标识的 DataSystem 对象；Resume 时下载到受控 attempt 目录，再由
RuntimeManager 调用 sandboxd Restore。

### E2E 验收设计

#### 客户端环境

E2E runner 在 x86 Linux 宿主机创建独立 venv，下载并校验上表的
`openyuanrong-sandbox` wheel 后安装。它使用 standalone 生成的服务器地址和 token，
不依赖本仓库的 `akernel_sdk` 实现。

#### 主流程

测试一次运行执行以下断言：

1. 创建 `runtime="runsc"` 的 RRT sandbox，记录 sandbox ID，并确认 `get_info()` 为
   `running`。
2. 写入随机 marker 文件并校验内容。
3. 启动一个 `background=True, stdin=True` 的 shell 进程，让它阻塞等待输入；记录 PID。
4. 调用 `pause(ttl_seconds=900)`：
   - SDK 返回相同 sandbox ID；
   - state 为 `paused`；
   - snapshot ID 非空且等于 SDK 内部 lifecycle request ID；
   - size、expiresAt 均为正值；
   - watcher 查询最终为 `paused`。
5. 调用 `resume()`：
   - SDK 返回相同 sandbox ID；
   - state 为 `running`；
   - routeAddress、functionProxyId 非空；
   - watcher 查询最终为 `running`。
6. 向 pause 前创建的 PID 写入 stdin 并等待退出，断言输出正确。这是验证“同一进程树由
   runsc restore 恢复”的核心证据，不只验证重新创建了一个空 sandbox。
7. 重新读取 marker 文件，再执行一条新命令，分别验证文件系统连续性和恢复后的 RRT
   RuntimeRPC/直连数据面。
8. 再执行一次 pause/resume，断言产生新的 snapshot ID，并重复最小健康检查。
9. 删除 sandbox，确认实例消失；无论中间成功或失败都执行幂等清理。

#### 白盒证据和失败诊断

runner 输出一个不含 token 的 JSON 报告，至少包含：

- 镜像引用、AKernel/sandboxd revision 与 process compatibility patch identity
- SDK、core、RRT artifact 版本和 SHA-256
- sandbox ID、两次 snapshot ID、size、expiresAt
- pause/resume 开始与结束时间、返回 route/node/proxy 信息
- continuity 断言结果

失败时收集但不提交：

- `journalctl -u yuanrong.service -u sandboxd.service`
- FunctionProxy/FunctionAgent/RuntimeManager 日志
- sandboxd 和 runsc 日志
- DataSystem worker 日志
- ETCD 中该 sandbox 的 lifecycle 状态
- checkpoint root 的目录元数据（不复制 checkpoint 内容）

snapshot ID 等于 pause request ID，可作为跨 Frontend、FunctionSystem、DataSystem 和本地
artifact 的关联键。日志收集脚本必须对 token、IAM seed、registry auth 和云凭据做脱敏。

#### 失败与恢复语义

- wheel URL/SHA 不成对、checksum 不符、RRT 不是 x86_64 ELF、compatibility patch
  上下文不匹配时，镜像构建立即失败，不生成可部署 tag。
- `AKERNEL_ENABLE_PAUSE_RESUME=true` 但镜像无 RRT capability 或共享 checkpoint root
  不可写时，standalone 在服务就绪前失败并打印明确原因。
- SDK 对一次 lifecycle 调用的 transport retry 复用同一 request ID；Pause 返回的
  snapshot ID 必须与之相同，从而保证重试不会创建多个逻辑 snapshot。
- Pause 未返回权威 `paused` 终态时，runner 不发 Resume，并以 sandbox ID/request ID
  收集 ETCD、FunctionSystem、DataSystem、sandboxd 与 runsc 证据。
- Resume 未返回权威 `running` 路由时，runner 不创建替代 sandbox 掩盖失败；它保留现场
  直到诊断收集完成，随后执行幂等 Delete。
- 第二轮 pause/resume 或 Delete 失败均判定整次 E2E 失败，避免只验证 happy path 而忽略
  生命周期 worker、checkpoint attempt 或 DataSystem 对象泄漏。

### 测试计划

- 单元测试：隔离验证 URL/SHA 成对规则、amd64 限制、RRT services 选择、feature 默认值、
  bootstrap 参数构造和日志脱敏。删除任一 gate/backend/root 参数都必须使测试失败。
- 集成测试：构建 runtime stage 并检查 wheel SHA、ELF 架构、可执行位和 EROFS 目标路径；
  检查 node image 中 core/RRT revision、唯一 `rrt` slot、process wiring 以及 sandboxd RPC。
- 端到端测试：在 privileged Linux x86_64 standalone 上执行“主流程”的两轮生命周期，重点
  证明 pause 前 PID 和文件在 resume 后连续，而不是只断言 API 返回 200。
- 故障与清理测试：验证 patch 上下文损坏时构建失败、feature 默认关闭、显式开启时真实
  进程 argv 正确；teardown 后检查 sandbox、runtime、checkpoint attempt 和临时对象无
  泄漏。DataSystem 或 runsc 的强制故障注入不进入首轮通过门槛，但必须保留诊断入口。

### 兼容性与已知限制

#### #215 不是当前 FunctionSystem 分支最新提交

#215 的 FunctionSystem 为 `6fac483a`。参考实现工作树在其后还有 snapshot worker
self-await 修复。首轮以 #215 进行 bring-up，若 E2E 在 pause/resume teardown 或重复操作
暴露该问题，不单独替换 FunctionSystem 二进制；应从包含修复的同一 YuanRong 顶层提交
重新运行整组 Buildkite artifact，保持 Frontend、FunctionSystem、RRT、Sandbox SDK
版本一致后重测。

#### macOS 不能完成最终 runsc 验证

本地 macOS 可完成代码、脚本、wheel 和 Docker layer 静态验证，但 runsc checkpoint/restore
最终必须在 Linux x86_64、privileged Docker、内核能力满足的服务器执行。设计和 runner
应把本地可验证阶段与服务器 E2E 阶段分开报告。

#### compatibility patch 生命周期

兼容 patch 只服务于 #215 process-mode 缺口，并受 wheel checksum 和 patch context 双重
约束。不能让它演变成长期 fork；上游产物包含等价配置后必须删除。

### 成熟度标准

只有同时满足以下条件才可声明端到端验证通过：

- x86 all-in-one 镜像由 checksum-pinned core + RRT 构建成功；
- RRT service slot 实际可调度，且 pause feature 只在显式开关下开启；
- sandboxd Checkpoint/Restore、DataSystem upload/download、runsc restore 均有可关联证据；
- pause 前后台 PID 在 resume 后继续完成；
- 文件内容、同一 sandbox ID、恢复路由和新命令均正确；
- 第二轮 pause/resume 通过；
- 删除和 teardown 无资源泄漏或已知 self-await；
- 报告记录全部 artifact/revision，且不包含任何凭据。

### 升级与回滚策略

升级时先构建新 tag，保持旧镜像可用；以默认关闭状态启动并通过静态/健康检查后，再在
专用 standalone 节点显式开启 feature。回滚前停止新的 Pause 请求，并确保已 pause 的
sandbox 已成功 Resume 或 Delete；随后停止 standalone，使用原数据目录启动旧镜像。兼容
patch 只存在于新镜像层，不修改宿主机配置或云资源。已创建但未清理的 checkpoint 和
DataSystem 对象不能由旧镜像解释，必须在回滚前按新版本的清理路径处理。

## 生产就绪评审

- 特性开关和回滚：具备默认关闭的 standalone 开关；尚无按租户或请求粒度的 rollout。
- 指标、日志和告警：首轮提供关联 ID 和诊断包；尚未定义长期 SLO、告警阈值和 dashboard。
- 外部依赖：要求 Linux x86_64、privileged Docker、runsc checkpoint 能力和本地
  DataSystem worker。
- 容量与扩展性：首轮仅验证单 sandbox、单节点；未验证并发 Pause、对象容量和 GC。
- 运维工具：具备启动前检查、失败日志收集和幂等 Delete；不具备生产级 orphan repair。

因此该设计的成熟度上限是实验性 E2E 验证，不满足生产 GA 条件。

## 实施历史

- 2026-08-12：基于 AKernel builder、YuanRong 参考设计和 Buildkite #215 实物核验形成草案。

## 缺点

- 为复用 #215 引入临时 process compatibility patch，增加了一处需要上游收敛的维护点。
- 单一 EROFS rootfs 同时承载四套 Python runtime 和 RRT，镜像尺寸不会因只使用 RRT 而
  缩小。
- 首轮 DataSystem backend 不能证明跨进程重启或跨节点持久化恢复能力。

## 备选方案

### 先补 YuanRong process 脚本并重新跑 Buildkite

在 YuanRong 顶层和 FunctionSystem 仓补齐 process-mode 参数，再构建新的整组 wheel。
该方案归属更干净且不需要 AKernel compatibility patch，但不能直接消费已经完成的 #215。
它是兼容层的最终收敛方向，不作为首轮 bring-up 前置条件。

### 直接使用 YuanRong Kubernetes runtime 镜像

部署 #215 生成的 Kubernetes 镜像和 Helm chart 最接近 YuanRong 原生交付，但会绕过
AKernel `builder/` 和 all-in-one 镜像，无法验证本任务关注的 x86 编译与 standalone
集成，因此不采用。

### 首轮改用 OBS SnapshotStorage

OBS 可以验证进程重启后的持久对象，但会引入 endpoint、bucket、AK/SK、网络和清理策略，
扩大首轮故障面。DataSystem 已是真实 SnapshotStorage，足以验证当前单节点数据面；OBS
留到基础闭环稳定后单独设计。

## 基础设施需求

- 一台 Linux x86_64 服务器，Docker daemon 可用并允许 privileged container。
- 服务器能下载 #215 OBS wheel、基础镜像、gVisor 和 Kata 构建依赖；私网地址应加入
  `NO_PROXY`，不把代理注入 sandbox 内部控制链路。
- 足够存放两阶段 Docker build、224 MiB core wheel、EROFS rootfs、all-in-one image 和
  standalone 数据目录的本地磁盘空间。
- 不需要 Kubernetes、OBS 写入凭据或新增云资源。
