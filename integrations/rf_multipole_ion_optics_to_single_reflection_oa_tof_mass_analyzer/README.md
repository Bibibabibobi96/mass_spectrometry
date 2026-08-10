# RF多极杆到单次反射oaTOF集成入口

本目录只负责四、六、八极杆与oaTOF之间的连接合同、执行策略和跨器件资格，不保存上游或下游项目的
第二份参数权威。

- 当前人类可读状态与结论：[`docs/INTEGRATION.md`](docs/INTEGRATION.md)
- 连接profile机器权威：[`config/connection_profiles.json`](config/connection_profiles.json)
- 执行策略机器权威：[`config/execution_adapter_profiles.json`](config/execution_adapter_profiles.json)
- 唯一公开执行入口：[`workflows/family_source_closure/execute.ps1`](workflows/family_source_closure/execute.ps1)
- 集成局部门禁：[`verify_integration.ps1`](verify_integration.ps1)

完整实验数字属于run三件套或日期化history；本README只导航，不维护参数表或运行时间线。
