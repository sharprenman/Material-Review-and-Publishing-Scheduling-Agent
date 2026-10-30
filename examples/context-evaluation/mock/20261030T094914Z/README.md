# 上下文工程执行对比

模式：mock；模型：offline-test-double；批次：20261030T094914Z（UTC）。
同一输入各跑一次，模型有随机性；输入token来自API usage，非大小代理估算。
缺资料历史案例来自各自真实前置请求，不复制Mock结果；案例不授予当前请求任何权限。

| 场景 | 基线/优化版结果 | 输入token：基线→优化 | 输入减少比例 | 模型调用：基线→优化 |
| --- | --- | --- | --- | --- |
| normal | completed / completed | None → None | None% | 4 → 4 |

[基线normal过程](baseline/normal.md) · [优化版normal过程](optimized/normal.md)

| missing | blocked / blocked | None → None | None% | 3 → 3 |

[基线missing过程](baseline/missing.md) · [优化版missing过程](optimized/missing.md)

| conflict | completed / completed | None → None | None% | 8 → 8 |

[基线conflict过程](baseline/conflict.md) · [优化版conflict过程](optimized/conflict.md)

| long_metadata | completed / completed | None → None | None% | 4 → 4 |

[基线long_metadata过程](baseline/long_metadata.md) · [优化版long_metadata过程](optimized/long_metadata.md)


负数表示输入增加。短路径的结构化状态与来源信息可能增加输入，不能预先承诺收益。
完整输出、数据库草稿事实、模型响应ID、usage与上下文筛选记录均在同目录。
