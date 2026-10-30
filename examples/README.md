# 实际运行证据

inputs为实际输入，outputs/live与traces/live为最新完整真实DeepSeek批次；mock为明确标记的离线执行。
同名_database.json为实际SQLite查询事实。manifest记录模型、模式、批次、调用量和故障注入方式。
history保留旧批次和失败记录；first-confirmation为首批真实确认结果与从原运行目录复制的原Trace。
生成命令：`uv run python scripts/generate_examples.py --mode mock` 或显式`--mode live`。
每次独立初始化数据库，上一批移到history；失败输出先保存，断言失败返回非零，不冒充全通过。
最新完整批次包含正常、缺失、风险、冲突、变化占用、保存失败，以及重复提交和重启确认。
运行用业务库和检查点在已忽略的var/evidence下；提交的Trace无凭证或模型内部思维过程。
