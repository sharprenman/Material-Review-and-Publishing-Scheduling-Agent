# Agent harness 最后一轮加固验证

本目录是独立新批次，全部为离线验证；未调用真实API。历史证据未覆盖。

| 检查 | 实际结果 | 原始输出 |
| --- | --- | --- |
| 定向回归 | 69 passed | [directed.txt](directed.txt) |
| 全量 | 95 passed、1 skipped | [pytest.txt](pytest.txt) |
| Ruff | 通过 | [ruff.txt](ruff.txt)、[format.txt](format.txt) |
| Mypy、语法 | 通过 | [mypy.txt](mypy.txt)、[compile.txt](compile.txt) |
| sdist、wheel | 通过 | [build.txt](build.txt)、dist/ |
| 首次离线安装 | 缓存解析失败，保留 | [install.txt](install.txt) |
| 固定已有版本安装 | 通过；使用no-deps后另做兼容检查 | [install-pinned.txt](install-pinned.txt)、[installed-dependencies.txt](installed-dependencies.txt) |
| 独立wheel环境全量 | 95 passed、1 skipped | [installed-tests.txt](installed-tests.txt) |
| 目录外CLI | 帮助、运行、查询通过 | [installed-help.txt](installed-help.txt)、[installed-run.txt](installed-run.txt)、[installed-status.txt](installed-status.txt) |
| 数据库事实 | 一份草稿、一份请求占位 | [installed-database.json](installed-database.json) |

演示：受控离线模型首次选择20点，工具返回“必须选择最早可用候选”，随后选择真实查询中的17点成功。
[实际Trace](demo.trace.jsonl)、[最终结果](demo.output.json)、[数据库核验](demo.database.json)、[断言输出](demo.txt)。

此演示证明程序拒绝及纠正路径，不代表真实模型理解能力。Trace故障告警在标准错误输出，
不承诺审计完整或消除JSON/SQLite并发窗口。测试中故障均为明确受控注入。
