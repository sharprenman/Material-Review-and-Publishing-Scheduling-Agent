# 测试

`uv run pytest` 默认离线；真实API测试默认跳过。
单元测试验证工具保护与预算，集成测试使用临时文件SQLite并重建连接验证恢复与事务，
验收测试检查最终结果和数据库事实。
`RUN_LIVE=1 uv run pytest tests/live -q` 显式使用DEEPSEEK_API_KEY，最多6次模型调用。
实际证据与检查输出见examples/test-results；不要把受控替身结果标为真实模型执行。

可读性增量测试还覆盖中文摘要与--json、复制命令可执行、旧Trace只读与标源、简短依据协议和脱敏。
本次增量验证保存在examples/test-results/readability，第一次交付记录仍保留。
