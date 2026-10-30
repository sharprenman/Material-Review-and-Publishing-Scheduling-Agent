# AI 辅助内容、个人修改及验证

## AI 辅助内容

项目前期，我使用Codex辅助梳理需求、搭建代码、检查框架用法、编写测试和整理运行材料。
运行时的DeepSeek负责选择工具和下一步动作，离线Mock负责测试流程与程序保护。我将这些用途分别记录。

这次文档更新也由Codex协助：核对现有实现和验证文件，把本轮改动写回规定的文档。
整理文档期间没有修改业务代码、重新执行测试或调用真实API；下面的验证结果引用已归档输出。

## 我本轮修改了什么

这轮我集中加固Agent harness，保留原来的三节点图、五个工具和单机CLI。
没有增加依赖、修改数据库表结构或提高预算。修改涉及context、tools、graph、service、repository、
Trace、MockModel、预算异常，以及相关测试。

### 观察有效性只保留一套判断

我让上下文展示和工具保护复用同一套观察有效性检查。
工具执行前重新核对素材、规则版本、确认代次、查询有效期和保存冲突，避免模型调用期间数据变化后继续用旧证据。
工具校验使用完整观察，投影、摘要和历史案例只供展示与参考，原始记录和来源继续保留。

### 把业务要求落实到工具和事务

我补齐最早候选的硬校验，并在保存事务中重新比对查询快照与最新占用。
有效确认绑定的时间仍可用时优先保存，不能因为另一个时间空出来就自动换排。
成功写入后继续保留幂等重放，不能因重查而重复占位。

我也收紧了finish的依据：blocked和missing要匹配当前审核，no_slots要有有效查询并确认最新占用确实无候选。
证据不够时返回可纠正错误；incomplete仍允许模型主动承认未完成。业务拒绝、执行故障和预算耗尽分别处理。

### 日志和记忆故障不改变业务事实

我把Trace写入故障与业务执行分开处理。草稿已保存后，即使日志写不进去，也不能把请求改记失败。
告警写到标准错误，保证`--json`的标准输出还能解析。
记忆与Trace同时故障时继续降级，不在错误处理里反复写入同一份故障日志。

### 明确消息的信任边界

可信行为规则留在system消息，结构化数据包改放user消息。
素材、工具文本和历史案例中的自然语言不因此获得系统指令权限，调用与返回继续成对保留。
这是本轮的程序保护，不表示模型已经完全免疫提示注入。

## 验证记录

修改前基线为64项通过、1项跳过。首批新增测试在修复前暴露7个预期失败，之后再做定向、全量和独立安装验证。

| 检查 | 本轮结果 | 已归档输出 |
| --- | --- | --- |
| 定向回归 | 69项通过 | [directed.txt](../examples/test-results/hardening-20261030T231921/directed.txt) |
| 全量回归 | 95项通过，1项跳过 | [pytest.txt](../examples/test-results/hardening-20261030T231921/pytest.txt) |
| Ruff与格式 | 通过 | [Ruff](../examples/test-results/hardening-20261030T231921/ruff.txt)、[格式](../examples/test-results/hardening-20261030T231921/format.txt) |
| 类型与语法 | 通过 | [Mypy](../examples/test-results/hardening-20261030T231921/mypy.txt)、[语法](../examples/test-results/hardening-20261030T231921/compile.txt) |
| sdist和wheel | 构建通过 | [build.txt](../examples/test-results/hardening-20261030T231921/build.txt) |
| 独立wheel环境 | 95项通过，1项跳过 | [installed-tests.txt](../examples/test-results/hardening-20261030T231921/installed-tests.txt) |
| 依赖兼容 | 通过 | [installed-dependencies.txt](../examples/test-results/hardening-20261030T231921/installed-dependencies.txt) |
| 目录外CLI | 运行与查询通过，数据库一份草稿、一份占位 | [运行](../examples/test-results/hardening-20261030T231921/installed-run.txt)、[查询](../examples/test-results/hardening-20261030T231921/installed-status.txt)、[数据库](../examples/test-results/hardening-20261030T231921/installed-database.json) |

首次离线安装受缓存解析限制而失败，我保留了记录；随后按已锁定版本安装并单独检查兼容性，见[评估文档](03-evaluation.md)。
跳过项是真实网络测试，本轮没有调用真实API。

## 演示与证据边界

本轮演示使用受控离线模型：先错误选择20点，程序依据实际时段查询拒绝；
随后改选17点，最终数据库确认只有一份草稿和一份占位。

[实际Trace](../examples/test-results/hardening-20261030T231921/demo.trace.jsonl)、
[最终输出](../examples/test-results/hardening-20261030T231921/demo.output.json)和
[数据库核验](../examples/test-results/hardening-20261030T231921/demo.database.json)均保留。
这些材料证明程序保护和纠错路径，不证明真实模型会作出同样调整。

前期真实模型的正常、资料不足和工具失败记录仍在examples中，逐项入口见[评估文档](03-evaluation.md)。
前期上下文对比也保留：长元数据输入减少46.34%，短流程输入增加；这不是本轮重新测出的结论。

加固验证阶段未提交或推送GitHub，未覆盖历史证据。JSON与SQLite的跨介质并发窗口、Trace故障造成的审计缺失仍存在。
我没有把离线通过写成真实模型回归通过，也没有将本地结果写成远端CI通过。
