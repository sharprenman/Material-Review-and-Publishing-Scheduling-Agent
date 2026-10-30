# 素材审核与发布排期 Agent

题号 **1** · Python 3.12 · LangGraph · DeepSeek · SQLite · CLI

帮助内容团队读取素材、审核规则、查询时段并保存排期草稿。**只保存草稿，绝不发布。**
真实模型选择每一步工具，应用代码守住审核、确认、预算和事务约束。

## 评审入口

先按本文运行，再依次查看需求、设计、评估、AI使用与复盘。实际输入、输出、Trace和测试结果统一由评估文档索引。
当前加固回归为95项通过、1项跳过，独立wheel环境结果相同；本轮没有调用真实API。
已有真实模型材料属于此前版本，不能代替本轮真实回归。

- [需求与业务规则](docs/01-requirements.md)
- [架构、确认恢复和幂等设计](docs/02-solution.md)
- [评估与运行证据索引](docs/03-evaluation.md)
- [AI 使用记录](docs/04-ai-usage.md)、[复盘](docs/05-retrospective.md)
- [真实 DeepSeek 执行汇总](examples/outputs/live/manifest.json)
- [正常路径 Trace](examples/traces/live/normal.jsonl)、[冲突及重启确认 Trace](examples/traces/live/conflict.jsonl)

目标仓库：[Material-Review-and-Publishing-Scheduling-Agent](https://github.com/sharprenman/Material-Review-and-Publishing-Scheduling-Agent)。
仓库为公开仓库。评审版本以GitHub实际提交为准；本地可用`git rev-parse HEAD`查看commit SHA，并与远端main核对。
远端CI状态以GitHub Actions记录为准，本地检查结果见评估文档。

## 安装

支持 macOS/Linux（跨进程锁使用 `fcntl`），固定 Python **3.12.13**。已安装 [uv](https://docs.astral.sh/uv/) 后，在项目根目录执行：

```sh
uv python install 3.12.13
uv sync --locked
uv run material-scheduler --help
```

依赖由 `pyproject.toml` 与实际生成的 `uv.lock` 管理；CI 使用相同版本。
`data/` 是合成素材与规则，不代表真实内容审核运营标准。

## 离线运行

```sh
uv run material-scheduler --runtime-dir var/demo run examples/inputs/normal.json
uv run material-scheduler --runtime-dir var/demo status normal
uv run material-scheduler --runtime-dir var/demo draft normal
uv run material-scheduler --runtime-dir var/demo run examples/inputs/conflict.json
```

默认输出中文摘要。最后一个命令等待确认，退出码为 **2**，会直接打印本次可复制的确认、拒绝命令。
也可以手动填写方案ID与版本：

```sh
uv run material-scheduler --runtime-dir var/demo confirm conflict <proposal_id> <version> --accept
# 拒绝用 --reject；默认 confirm 命令表示同意。
```

确认可以在进程重启后执行。若确认后时段已占用，会生成新版本方案，需要再次确认。
草稿会占位：示例先跑 normal 占17点，再跑 conflict 仍建议19点。
`draft` 与 `status` 默认显示中文结果；增加 `--json` 可获取原有完整JSON，`draft` 字段为实际数据库记录或 null。

```sh
uv run material-scheduler --runtime-dir var/demo trace conflict
uv run material-scheduler --runtime-dir var/demo status conflict --json
# 不依赖数据库、密钥或模型调用，直接阅读已保存的真实记录：
uv run material-scheduler trace conflict --file examples/traces/live/conflict.jsonl
```

## 一次流程怎样操作、结果怎样看

上面的conflict请求要求11月1日18点，初始18点已被占用，因此会建议19点并等待确认。
这时检查：`execution=waiting_confirmation`、`save_status=not_saved`、`draft=null`，表示还没有草稿。
终端退出码2是待确认；复制输出中“确认命令”下面的一整行执行即可，不需要自己拼接ID。

确认后重新审核与查询；若19点仍可用，检查`execution=completed`、`save_status=saved`，
并确认`draft`有真实编号及保存时间。若时段变化，会返回新方案，不能沿用旧确认。
想从头重跑请换运行目录，例如`var/demo-next`，同ID同目录重复提交会复用已有结果。

现有真实记录可直接阅读，不需要密钥，不调用模型：

```sh
uv run material-scheduler trace normal --file examples/traces/live/normal.jsonl
uv run material-scheduler trace conflict --file examples/traces/live/conflict.jsonl
uv run material-scheduler trace missing --file examples/traces/live/missing.jsonl
```

每步按“工具及参数→返回摘要→后续动作→模型依据→程序说明”阅读。
`rationale`是模型随动作给出的一句话依据，不是内部思维过程，也不是独立验证的事实；
程序说明来自审核、确认与保存规则。旧记录未提供具体依据时明确标注，不倒填模型原话。
正常、资料不足、工具失败等输入与结果对应关系见[评估文档](docs/03-evaluation.md)。

## 真实模型运行

在本地终端设置 `DEEPSEEK_API_KEY`，不要把凭证写进输入、截图或聊天。可选 `DEEPSEEK_MODEL`，默认 `deepseek-flash`。
也可复制 `.env.example` 为项目根目录的 `.env` 并填写密钥；从项目根目录运行时自动加载，已有环境变量优先。`.env` 已被 Git 忽略。

```sh
uv run material-scheduler --mode live --runtime-dir var/live-demo run examples/inputs/normal.json
uv run material-scheduler --mode live --runtime-dir var/live-demo run examples/inputs/conflict.json
uv run material-scheduler --mode live --runtime-dir var/live-demo confirm conflict <proposal_id> <version> --accept
```

真实与离线运行使用不同目录；禁止在另一模式下恢复同一个请求。
只读查询已有真实结果可用默认模式，无需再次请求模型。
模型通过固定官方 HTTPS 地址调用；响应体和凭证不进入异常日志。

## 输入与业务语义

每个请求对应一项素材；多项素材使用不同 `request_id` 分别提交。

```json
{
  "request_id": "my-request",
  "material_id": "M01",
  "channel": "video",
  "account": "team",
  "requested_time": "2026-11-01T18:00:00+08:00"
}
```

- 必须含日期且为整点；无偏移量时按 `Asia/Shanghai` 解释，有偏移量则转换为上海时间。
- 按渠道＋账号＋整点冲突；草稿占用，待确认方案不占用。
- 新排期必须选择最早可用候选；改变原要求时只生成待确认方案。已确认时间仍可用时优先保存，不自动换时。
- 用户确认绑定方案 ID＋版本；模型提供 `confirmed=true` 无效。
- `data/materials.json` 为素材事实，`rules.json` 为审核规则。缺少标题或权利信息禁止保存；无使用权或命中阻断标签禁止保存。
- `schedules.json` 仅首次导入运行目录的业务库；重复初始化不覆盖已有占用。后续查询以业务库为准。
- 相同请求 ID 和规范化内容返回已有结果；同 ID 不同内容明确拒绝。原始时间永不被建议覆盖。
- 示例日期用于可复现验收；当前没有“禁止历史日期”规则、时间窗口、跨日搜索或区间排期。

## 状态与退出码

默认中文摘要，`--json` 保留原JSON结构和退出码，支持放在命令前或具体命令后。
`trace` 输出逐步过程；它是只读查看，成功读取返回0，不继承被查看请求的业务退出码。
其余全局参数位于命令前。

| 退出码 | 含义 |
| --- | --- |
| 0 | 已保存且可查询草稿 |
| 2 | 等待用户确认，尚未保存草稿 |
| 3 | 审核阻断、信息不足或用户拒绝 |
| 4 | 执行失败、预算未完成、无可用时段、业务ID冲突或应用输入错误 |

命令行语法错误由 Typer 返回2，和待确认状态需结合中文状态或JSON的 `execution` 区分。
`execution`、`review.status`、`proposal.confirmation`、`save_status` 分别表示不同事实；不存在“已发布”状态。
业务理由不符或旧证据会返回可纠正的工具错误；真实存储故障与预算耗尽单独记录。
`finish(incomplete)`允许主动退出，不误标审核阻断或保存成功。
网络/协议失败不自动重试；新建请求可重新运行。未中断完成的失败结果再次提交不会自动花费模型调用。
执行中意外中断可用原始 `run` 命令恢复，累计预算不会清零。

默认每请求最多16次模型调用、20次工具调用、180秒累计活动耗时，单次网络超时25秒；框架另有128步限制。
设置由 `config.Settings` 定义。等待用户的时间不计入活动时间。
网络超时使用 HTTPX 操作超时；不提供独立进程强杀计时器。当前 CLI 为单机串行执行，非生产级调度服务。

## 验证与证据复现

```sh
uv run pytest
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src
uv build
uv run python scripts/generate_examples.py --mode mock
# 下列命令真实调用模型，会产生费用；脚本每批最多36次调用。
uv run python scripts/generate_examples.py --mode live
# 可选的真实网络测试，最多6次模型调用：
RUN_LIVE=1 uv run pytest tests/live -q
```

默认测试无需密钥和网络，真实网络测试默认跳过；真实证据脚本与离线证据明确分目录。
脚本为每个场景创建独立运行目录 `var/evidence/<模式>-<批次>/<场景>/`，生成前将旧证据归档到history，再写入对应模式目录；失败也保留已产生的输出与Trace。
保存失败通过真实 SQLite 触发器注入错误；它不是实际磁盘故障，不伪造工具返回。
macOS 本地可选 `--key-file api_key.rtf`，仅在内存提取凭证；不生成明文文件。

运行数据在 `var/`，包含独立业务库、检查点库和脱敏 Trace，已忽略。请保留整个运行目录用于恢复。
Trace写入失败会向标准错误告警，不回滚草稿或改写已保存状态；`--json`标准输出仍可解析。
这可能留下审计缺口，之后查询状态不能恢复缺失日志。
示例Trace记录模型动作、实际工具观察和简短依据，不采集模型内部思维过程。
新记录的 `rationale_source=model` 为模型自述（不视为独立验证的事实），
`program_policy` 为程序约束说明，`offline_model` 为离线替身说明。旧记录保持原样，缺少具体依据时明确标注。
证据脚本还会生成 `examples/reports/live.md` 或 `mock.md`，集中解释三条路径。

## 上下文与历史案例

默认启用工作记忆、动态筛选、确定性摘要与SQLite历史案例检索。
原始Trace保留，摘要不能授权，保存前仍重新审核与查占用。
`trace`可查看每轮上下文的保留/压缩数量及检索来源；`--baseline-context`仅用于关闭组装优化做对比。
`--context-budget`设置大小估算上限，`--memory-top-k`设置案例条数（0关闭检索）。
估算是UTF-8字节代理，不是精确token；默认16000，案例默认30天过期。

```sh
uv run python scripts/evaluate_context.py --mode mock
# 真实对比会产生费用，每批最多60次调用，结果独立存储，不覆盖旧证据。
uv run python scripts/evaluate_context.py --mode live
```

此前单样本对比中，长元数据输入减少46.34%，短路径输入增加；这是历史结果，本轮没有重新测量。
设计见[02-solution.md](docs/02-solution.md)，实际结果、失败与限制见[03-evaluation.md](docs/03-evaluation.md)。

### 上下文参数、跨请求检索与预算

默认启用优化，不需要增加参数：

```sh
uv run material-scheduler --runtime-dir var/context-demo run examples/inputs/conflict.json
uv run material-scheduler --runtime-dir var/context-demo trace conflict
```

Trace中会出现“上下文组装”，显示保留/压缩交互数、大小估算和案例来源。
待确认时复制输出中的确认命令，命令包含相同上下文设置。
如果想先看到跨请求检索，可在同目录运行两个不同request_id、相同素材的请求；
前一个请求必须已结束。例如先运行缺资料请求，再复制输入并更换请求ID运行，查看检索来源。
不要用相同request_id重复提交来测试记忆，幂等机制会直接返回已有结果。

```sh
# 只为对比：关闭组装优化，保留原消息累积策略与业务约束。
uv run material-scheduler --baseline-context --runtime-dir var/context-baseline run examples/inputs/normal.json
# 调整大小代理预算；关闭历史案例检索。
uv run material-scheduler --context-budget 16000 --memory-top-k 0 --runtime-dir var/context-tuned run examples/inputs/normal.json
```

配置在`config.Settings`中：context_enabled=true、context_max_estimate=16000、context_recent_turns=2、
memory_top_k=3、memory_ttl_days=30。CLI暴露预算、检索条数和对比开关。
模型/工具次数和活动耗时限制继续生效，最大模型调用16次，默认不自动重试。

大小估算使用UTF-8字节代理加固定余量，**不是精确token计数或模型tokenizer**。
API实际输入/输出token来自响应usage；不能用估算数字宣称真实token节省。


## 本轮加固验证

保留decide、tool、confirm三节点和原有五个工具，没有增加依赖、改变表结构或提高预算。
上下文展示和工具保护共用观察有效性判断，工具执行前再次复查；关闭上下文优化也不会关闭业务保护。
可信规则放system消息，结构化数据放user消息；这不是完全免疫提示注入的证明。

本轮[评估与证据](docs/03-evaluation.md)包含定向69项、全量95项及独立wheel环境95项通过的原始输出。
受控离线演示验证了“错选20点被拒绝，再纠正为17点保存”，没有调用真实API。
安装时曾遇到离线缓存解析失败，后续按锁定版本安装并检查兼容性；失败记录也已保留。
