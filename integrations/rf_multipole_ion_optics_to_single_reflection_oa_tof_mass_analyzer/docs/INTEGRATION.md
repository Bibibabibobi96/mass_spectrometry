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
每次prepare还会从[`engineering_budget.json`](../config/engineering_budget.json)冻结当前profile的
`resolved_engineering_budget.json`。三个phase都执行公共进程树内存、墙钟、瞬态目录和compact终态硬帽，
自动重试固定为零。

## 迁移等价结论

[`migration_oracles.json`](../config/migration_oracles.json)是只读的迁移前证据索引，保留当时的术语、路径、
run ID 和 census。它不定义活动 profile、执行步骤或拓扑。
`migration_equivalence_preregistration.json`继续作为读取结果前冻结的`BLOCKED/NOT_RUN`预注册快照，
不得事后改写。

2026-07-29，两个profile均以冻结的同源N=100输入完成真实COMSOL→SIMION重跑。独立analysis run
`20260729_195243__analysis__cross__rf-oatof-migration-equivalence`核对源身份、五级census和四组粒子
事件集合，两个profile均为精确`PASS`，因此零物理变化的功能迁移已经闭合。结果SHA-256为
`4E6D3D2B9DA34B86965AD2B2FA03224ECE5B0311EC379BB78E22A94C965C2851`。

adapter仍只发布轻量integration父运行；大型COMSOL/SIMION资产由三个子运行拥有，并按compact合同保留。
连续相空间保持`NOT_EVALUATED`；本结论不声明场、分辨率、数值收敛、Candidate、Formal或整机资格。

## 静态门禁

[`verify_integration.ps1`](../verify_integration.ps1)只运行无求解器的合同测试：profile 唯一性、公共解析、
非空 transfer composition step、adapter registry SHA、预算冻结SHA、父运行发布fixture、等价PASS/FAIL
fixture与显式授权边界。它不运行COMSOL、SIMION、MATLAB、CAD，也不替代真实迁移等价复验。
