# 测试结果、失败记录与已知限制

## 当前验证结论

本轮加固的全量测试为95项通过、1项跳过；独立wheel环境结果相同。
跳过的是需要显式开启的真实网络测试。本轮没有调用真实API，也没有覆盖此前的真实输入、输出或Trace。
下文将本轮离线验证与历史真实模型记录分开说明，运行命令见[README](../README.md)。

## 本轮加固：预期与实际

| 检查 | 预期 | 实际结果与记录 |
| --- | --- | --- |
| 修改前基线 | 确认已有流程可运行 | 本轮开发记录为64通过、1跳过；上下文阶段的[历史输出](../examples/test-results/context/offline-tests.txt)保留 |
| 新增测试修复前 | 暴露缺失的程序保护 | 首批出现7个预期失败；按本轮开发记录说明，修复后的原始输出见下列定向与全量记录 |
| 定向回归 | 新增保护及相关旧行为通过 | [69通过](../examples/test-results/hardening-20261030T231921/directed.txt) |
| 全量回归 | 所有离线测试通过，默认不调用网络 | [95通过、1跳过](../examples/test-results/hardening-20261030T231921/pytest.txt) |
| Ruff与格式 | 无检查错误 | [Ruff](../examples/test-results/hardening-20261030T231921/ruff.txt)、[格式](../examples/test-results/hardening-20261030T231921/format.txt)通过 |
| 类型与语法 | Mypy及源码编译通过 | [Mypy](../examples/test-results/hardening-20261030T231921/mypy.txt)、[语法](../examples/test-results/hardening-20261030T231921/compile.txt)通过 |
| 打包 | sdist和wheel可构建 | [构建输出](../examples/test-results/hardening-20261030T231921/build.txt)通过 |
| 独立wheel环境 | 不依赖源码可运行，测试结果一致 | [95通过、1跳过](../examples/test-results/hardening-20261030T231921/installed-tests.txt) |
| 安装兼容性 | 已安装依赖没有冲突 | [兼容检查](../examples/test-results/hardening-20261030T231921/installed-dependencies.txt)通过，版本见[记录](../examples/test-results/hardening-20261030T231921/installed-versions.txt) |
| 目录外CLI | 输入可运行，状态可查询，草稿实际存在 | [输入](../examples/test-results/hardening-20261030T231921/cli.input.json)、[运行](../examples/test-results/hardening-20261030T231921/installed-run.txt)、[查询](../examples/test-results/hardening-20261030T231921/installed-status.txt)、[数据库事实](../examples/test-results/hardening-20261030T231921/installed-database.json) |

定向测试覆盖工具、预算、上下文、Repository、确认恢复、记忆和CLI。
首批失败暴露了最早候选、结束理由和消息角色的缺口，修复后再执行定向与全量验证。

首次无固定版本的离线安装因本地缓存无法完成依赖解析而失败，保留[原始输出](../examples/test-results/hardening-20261030T231921/install.txt)。
随后按已有锁定版本安装，见[安装输出](../examples/test-results/hardening-20261030T231921/install-pinned.txt)，并单独检查依赖兼容性。
不能据此声称断网且没有缓存时也能完整安装。

### 新增保护的覆盖

| 情况 | 必须观察到的结果 |
| --- | --- |
| 模型调用期间素材或规则改变 | 工具前复查，旧审核不再作为有效证据 |
| 查询过期、发生保存冲突或确认代次变化 | 拒绝旧观察，重新获取后才继续；优化开关两种模式都受保护 |
| 模型跳过最早空位 | 返回可纠正错误，不写草稿；调整为正确候选后保存 |
| 有效确认后更早时段空出 | 保持确认绑定时间，不擅自改排 |
| blocked/missing理由不符 | 返回错误观察，不写错误终态 |
| 无查询或仍有候选时no_slots | 拒绝结束；最新占用变化时要求重查 |
| 主动incomplete | 可有界退出，不误标业务阻断或保存成功 |
| 已保存后Trace写入失败 | 草稿和请求成功状态不变；警告进入标准错误 |
| 未保存或记忆与Trace同时故障 | 可降级处理，不递归写入故障日志，JSON标准输出可解析 |
| 素材或案例中夹带指令文本 | 数据包不进入system角色，工具仍执行业务校验 |
| 持续错误动作 | 累计预算终止执行，不无限循环 |

原有确认版本、并发竞争、事务回滚、重复提交和成功写入后重放继续通过。
具体测试见[tools](../tests/unit/test_tools.py)、[context](../tests/unit/test_context.py)、
[budget](../tests/unit/test_agent_budget.py)、[repository](../tests/integration/test_repository.py)、
[确认恢复](../tests/integration/test_confirmation_resume.py)、[记忆](../tests/integration/test_memory.py)和[CLI](../tests/acceptance/test_cli.py)。

### 受控纠错演示

本轮另跑了一次受控离线演示：第一次选择20点，程序根据实际查询发现17点仍可用而拒绝；
下一次改选17点后保存成功。全程经过原有图、工具和SQLite，不预设成功的数据库结果。

- [实际Trace](../examples/test-results/hardening-20261030T231921/demo.trace.jsonl)：5次动作，包含错选、拒绝及纠正。
- [最终输出](../examples/test-results/hardening-20261030T231921/demo.output.json)：请求hardening-demo完成，草稿时间17点。
- [数据库核验](../examples/test-results/hardening-20261030T231921/demo.database.json)：一份草稿、一份请求占位。
- [演示断言](../examples/test-results/hardening-20261030T231921/demo.txt)：执行成功。

Trace明确标记mock。这证明程序保护和纠错路径能够执行，不证明真实模型必然理解错误或会作出同样选择。

## 历史真实模型记录

以下是本轮加固之前实际调用DeepSeek的材料。使用`deepseek-flash`，关闭thinking，
响应ID、模型名、usage、工具参数、实际返回、后续动作和简短依据保留在Trace中。
这批六类场景及重启确认共26次调用，见[汇总](../examples/outputs/live/manifest.json)。
它们证明项目曾实际接入模型，不能替代本轮修改后的真实模型回归。

| 场景 | 实际输入 | 预期与当时实际结果 | 实际输出 | Trace |
| --- | --- | --- | --- | --- |
| 正常 | [normal](../examples/inputs/normal.json) | 17点保存草稿，数据库有记录 | [normal](../examples/outputs/live/normal.json) | [normal](../examples/traces/live/normal.jsonl) |
| 资料不足 | [missing](../examples/inputs/missing.json) | 缺少使用权信息，结束且不保存 | [missing](../examples/outputs/live/missing.json) | [missing](../examples/traces/live/missing.jsonl) |
| 工具失败 | [save_failure](../examples/inputs/save_failure.json) | SQLite写入失败，事务回滚 | [save_failure](../examples/outputs/live/save_failure.json) | [save_failure](../examples/traces/live/save_failure.jsonl) |
| 规则风险 | [risk](../examples/inputs/risk.json) | 命中CONTENT-01，不保存 | [risk](../examples/outputs/live/risk.json) | [risk](../examples/traces/live/risk.jsonl) |
| 时段冲突 | [conflict](../examples/inputs/conflict.json) | 18点占用，建议19点并等待确认 | [conflict](../examples/outputs/live/conflict.json) | [conflict](../examples/traces/live/conflict.jsonl) |
| 重启确认 | 同上conflict | 重建应用、确认并复查后保存19点 | [confirmed](../examples/outputs/live/confirmed_after_restart.json) | 同上conflict后半段 |
| 占用变化 | [changed](../examples/inputs/changed.json) | 增加19点占用后建议20点 | [changed](../examples/outputs/live/changed.json) | [changed](../examples/traces/live/changed.jsonl) |
| 重复提交 | 同上normal | 返回同一草稿ID，只有一份记录 | [duplicate](../examples/outputs/live/duplicate.json) | 不新增模型动作 |

同名`*_database.json`是当时从实际数据库读取的草稿与占位事实。
工具失败使用SQLite触发器受控注入，模型调用是真实的，但没有声称发生真实磁盘故障。
离线材料另存于examples/outputs/mock和examples/traces/mock，不计为真实模型执行。

### 模型如何根据观察调整动作

| 路径 | 工具观察 | 随后的实际动作 |
| --- | --- | --- |
| 正常 | 审核通过，17点可用 | 选择save_draft，参数为17点，保存成功 |
| 资料不足 | 审核返回缺少使用权信息 | 选择finish，不再继续查询或保存 |
| 冲突 | 查询返回18点占用、19点可用 | 改选19点，程序返回待确认方案；确认后重查再保存 |

可用`trace 请求ID --file 文件`阅读逐步记录，命令见README。
模型自述与程序说明分别标记，旧记录没有具体依据时不补写模型原话。

## 上下文真实对比：历史结果与代价

完整数据见[对比批次](../examples/context-evaluation/live/20261030T095915738103Z/README.md)。
基线引用此前实际完成的20261030T095009Z；两边模型、输入、合成资料、初始排期和32000大小代理预算一致，
使用独立数据库，各自真实运行缺资料前置请求后重启。该次优化批次新增23次调用。
长标题为工具实际读取的7000字合成资料，输入token来自API usage，不是字符估算。

| 场景 | 实际输入token：基线→优化 | 模型调用 | 当时业务结果 |
| --- | --- | --- | --- |
| 正常 | 4875→7271 | 4→4 | 两边保存原时段 |
| 缺资料 | 3413→5741 | 3→3 | 两边阻断；优化版检索到此前的真实案例 |
| 冲突及确认 | 10064→23565 | 8→9 | 两边确认后保存19点 |
| 长元数据 | 15433→8281 | 4→4 | 两边保存16点，输入减少46.34% |

短路径输入增加，四个样本合计输入也增加；确认流程多一次前置条件错误后的调整。
每种场景只跑一次，模型有随机性，延迟受网络影响。这个结果不支持普遍节费或加速的结论，
本轮加固也没有重新做成本对比。

| 路径 | 优化版输入 | 优化版输出 | 优化版Trace | 基线Trace |
| --- | --- | --- | --- | --- |
| normal | [输入](../examples/context-evaluation/live/20261030T095915738103Z/optimized/normal.input.json) | [输出](../examples/context-evaluation/live/20261030T095915738103Z/optimized/normal.output.json) | [Trace](../examples/context-evaluation/live/20261030T095915738103Z/optimized/normal.jsonl) | [基线](../examples/context-evaluation/live/20261030T095915738103Z/baseline/normal.jsonl) |
| missing | [输入](../examples/context-evaluation/live/20261030T095915738103Z/optimized/missing.input.json) | [输出](../examples/context-evaluation/live/20261030T095915738103Z/optimized/missing.output.json) | [Trace](../examples/context-evaluation/live/20261030T095915738103Z/optimized/missing.jsonl) | [基线](../examples/context-evaluation/live/20261030T095915738103Z/baseline/missing.jsonl) |
| conflict | [输入](../examples/context-evaluation/live/20261030T095915738103Z/optimized/conflict.input.json) | [输出](../examples/context-evaluation/live/20261030T095915738103Z/optimized/conflict.output.json) | [Trace](../examples/context-evaluation/live/20261030T095915738103Z/optimized/conflict.jsonl) | [基线](../examples/context-evaluation/live/20261030T095915738103Z/baseline/conflict.jsonl) |
| long_metadata | [输入](../examples/context-evaluation/live/20261030T095915738103Z/optimized/long_metadata.input.json) | [输出](../examples/context-evaluation/live/20261030T095915738103Z/optimized/long_metadata.output.json) | [Trace](../examples/context-evaluation/live/20261030T095915738103Z/optimized/long_metadata.jsonl) | [基线](../examples/context-evaluation/live/20261030T095915738103Z/baseline/long_metadata.jsonl) |


来源和输入比对见[核验记录](../examples/test-results/context/security.json)，
上下文阶段包含失败与复验的105次实际调用尝试见[计数](../examples/test-results/context/live-accounting.json)。
这些都是历史批次，本轮未新增真实调用。

## 保留的失败记录

- 早期冲突路径首次调用后未完成：[输出](../examples/outputs/history/live-20261029T092011Z/conflict.json)、
  [Trace](../examples/traces/history/live-20261029T092011Z/conflict.jsonl)。当时错误信息不足，无法确定具体原因，不倒推原因。
- 模型读取缺失项后跳过审核直接结束：[输出](../examples/outputs/history/live-before-20261029T101248Z/missing.json)、
  [Trace](../examples/traces/history/live-before-20261029T101248Z/missing.jsonl)。保留失败后补前置检查和回归。
- 长元数据压缩后模型反复读取，耗尽16次预算：[输出](../examples/context-evaluation/live/20261030T095009Z/optimized/long_metadata.output.json)、
  [Trace](../examples/context-evaluation/live/20261030T095009Z/optimized/long_metadata.jsonl)。明确当前投影与历史摘要后，
  [定向真实复验](../examples/context-evaluation/live/long-fix-verification/output.json)用4次调用完成，再进行完整对比。
- 本轮首次离线安装缓存解析失败已在前文列出，没有从交付记录中删去。

## 已知限制与未完成事项

JSON资料与SQLite之间的并发窗口仍存在，复查不能等同于跨介质事务。
Trace故障可能造成审计缺失；标准错误告警不新增数据库状态，后续查询无法还原丢失日志。
角色分隔和离线注入测试不等于完全免疫提示注入。
离线测试证明程序在受控输入下执行保护，不证明真实模型理解能力；本轮尚未做新的真实API回归。

项目仅处理合成元数据，支持单机macOS/Linux、单项请求、整点同日排期，不包含视频画面理解或真实发布。
HTTPX采用操作超时，没有独立进程强杀计时器；不保证进程强杀前的少量活动耗时全部持久化。
评审以README所列公开仓库的实际commit SHA为准。远端CI状态查看GitHub Actions，本地通过不等于远端CI通过。


## 仓库交付前检查（2026-10-31）

上传前再次执行当前源码的离线全量测试，95项通过、1项真实网络测试跳过。
Ruff、格式、Mypy和语法检查通过。本次上传没有重新调用真实模型，也没有替换已归档的运行证据。
仓库包含README、源码、可执行测试、合成资料、规定的五份文档、依赖锁文件和空密钥配置示例。
实际输入、输出、Trace与测试记录保留在examples中。密钥、本地环境、数据库和缓存不纳入提交。
