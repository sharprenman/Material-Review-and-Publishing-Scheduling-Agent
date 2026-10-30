# 上下文工程执行对比

模式：live；模型：deepseek-flash；批次：20261030T095915738103Z（UTC）。
同一输入各跑一次，模型有随机性；输入token来自API usage，非大小代理估算。
引用基线批次：20261030T095009Z；本批实际新增调用：23（含前置请求）。
缺资料历史案例来自各自真实前置请求，不复制Mock结果；案例不授予当前请求任何权限。

| 场景 | 基线/优化版结果 | 输入token：基线→优化 | 输入减少比例 | 模型调用：基线→优化 |
| --- | --- | --- | --- | --- |
| normal | completed / completed | 4875 → 7271 | -49.15% | 4 → 4 |
| missing | blocked / blocked | 3413 → 5741 | -68.21% | 3 → 3 |
| conflict | completed / completed | 10064 → 23565 | -134.15% | 8 → 9 |
| long_metadata | completed / completed | 15433 → 8281 | 46.34% | 4 → 4 |

负数表示输入增加。短路径的结构化状态与来源信息可能增加输入，不能预先承诺收益。
完整输出、数据库草稿事实、模型响应ID、usage与上下文筛选记录均在同目录。

[基线normal过程](baseline/normal.md) · [优化版normal过程](optimized/normal.md)
耗时：3942→4194ms；工具调用：4→4。

[基线missing过程](baseline/missing.md) · [优化版missing过程](optimized/missing.md)
耗时：3124→3111ms；工具调用：3→3。

[基线conflict过程](baseline/conflict.md) · [优化版conflict过程](optimized/conflict.md)
耗时：7575→10638ms；工具调用：8→9。

[基线long_metadata过程](baseline/long_metadata.md) · [优化版long_metadata过程](optimized/long_metadata.md)
耗时：4401→4915ms；工具调用：4→4。
