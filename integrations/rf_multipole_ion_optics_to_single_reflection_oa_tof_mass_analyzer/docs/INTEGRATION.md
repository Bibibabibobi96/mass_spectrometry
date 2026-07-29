# RF多极杆离子光学到单次反射oaTOF质量分析器集成

## 当前身份与边界

本目录是四、六、八极杆离子光学到单次反射正交加速TOF质量分析器的唯一连接实例层。
[`connection_profiles.json`](../config/connection_profiles.json)是连接拓扑的唯一机器权威；调用者必须显式提供
`ConnectionProfileId`。解析后的 connection 决定刚性位姿、连接器、公共电位、时钟和场责任区，运行器不得再消费
connector case 或由间隙推断拓扑。

四极杆当前有两个冻结 profile：

- `rf_quadrupole_grounded_connector_gap_1mm`；
- `rf_quadrupole_direct_mating_gap_0mm`。

唯一公开运行入口是[`execute_integration.ps1`](../execute_integration.ps1)。它冻结 resolved connection 和
composition plan；adapter 将二者直接交给
`workflows/rf_to_oatof_integration/run_rf_to_oatof_transfer.ps1`。内部 phase 固定为
`pre_pulse_interface_transport`、`pulse_capture`、`analyzer_transport`，不构成独立公开入口或资格声明。

## 历史证据

[`migration_oracles.json`](../config/migration_oracles.json)是只读的迁移前证据索引，保留当时的术语、路径、
run ID 和 census。它不定义活动 profile、执行步骤或拓扑。两个 profile 经新入口重跑、同源核对及全部 census
比较完成前，`migration_equivalence_preregistration.json`固定为`BLOCKED/NOT_RUN`；不得宣称等价、晋升或
Formal资格。

## 静态门禁

[`verify_integration.ps1`](../verify_integration.ps1)只运行无求解器的合同测试：profile 唯一性、公共解析、
非空 transfer composition step、adapter registry SHA 与显式授权边界。它不运行COMSOL、SIMION、MATLAB、CAD，
也不替代真实迁移等价复验。
