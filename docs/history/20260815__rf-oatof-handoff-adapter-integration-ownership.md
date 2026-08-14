# RF→oaTOF handoff adapter归属收敛

## 范围与判据

本轮只处理RF多极杆到oaTOF连接专用的粒子状态投影，不改变oaTOF项目Formal、旧pulse扩展、
`build_handoff_pulse_program.py`、PA/GEM、场配置或运行结果。成功判据是：活动integration不再import
oaTOF项目内部`analysis/rf_handoff_adapter.py`；唯一实现由integration冻结；逐粒子ID、位置、速度、
能量、instrument time、输出schema及哈希保持等价。

## 审计与实现

旧adapter的四个API分别负责有序solver-row身份映射、oaTOF全局速度与SIMION加速器局部方向角互转，
以及ION行的速度/能量一致性检查。活动消费者全部位于
`rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer` integration：连续single-flight源、
oaTOF SIMION输入发布、resolution-attribution counterfactual及其测试。它不是独立oaTOF分析器能力。

实现移动到integration `runtime/rf_handoff_adapter.py`，项目旧副本删除；所有活动import改为该稳定API。
运行时依赖改为integration-owned `rf_oatof_handoff_adapter`，继续服务
`pre_pulse_interface_transport`和`analyzer_transport`，并显式加入`single_flight_transport`。pre-pulse
runner实际执行family source publisher，publisher再调用SIMION input writer与该adapter，因此两项
依赖必须继续进入pre-pulse冻结snapshot。历史Formal、
旧pulse及builder仍只由原staged消费者冻结，未改字节也未失去可达性。

## 行为表征

移动前先冻结三组全局速度`(1000,10,-20)`、`(-4000,250,-5)`、`(0,0,0) m/s`的17位方向角与反解结果；
canonical JSON SHA-256为
`554BF5954531D653811715132CFDAE86AB5DB0F384ADF88E69190352F905354C`。同时覆盖有序ID映射、合法ION行、
身份错配与能量错配失败关闭。移动后必须保持该digest与既有single-flight/source-bundle输入输出测试。

位置和instrument time不由adapter本身校验，而由邻接的`write_oatof_simion_input.py`与
`single_flight_source.py`继续承担；既有输入发布和source materialization测试共同冻结这些字段及输出
schema/hash。integration仍可调用oaTOF项目正式发布的理论与设计编译API，本轮只消除同义连接adapter。

## 验证收据

- 移动前characterization 2/2 PASS；移动后同一digest、ID映射和失败关闭2/2 PASS。
- adapter、single-flight source、SIMION input、source bundle、dependency和staged analyzer focused
  40/40 PASS；runtime/legacy characterization另20/20 PASS；Ruff PASS。
- integration full 373/373 PASS；两份schema-v3 successor逐行`ValidateOnly`共29/29 PASS。
- `common/verify_changed.ps1` L1 PASS：integration 373/373、oaTOF Static 206/206。
- repository bindings官方刷新器更新7份派生文件并通过`--check`；活动源码中旧project import、路径和
  dependency ID零命中。
- 独立审查曾建议从pre-pulse移除SIMION input writer与handoff adapter依赖；受控移除后冻结snapshot测试
  立即以`ModuleNotFoundError`失败。源码追踪确认pre-pulse runner实际执行family source publisher，后者
  调用writer及adapter；恢复两项consumer后focused 40/40与full 373/373重新PASS。该失败是依赖真实可达
  的反证收据，不允许以lazy import或复制实现掩盖。
- CLOC 2.10相对`2833f4bf7294df3759dba9aabf69bd0ce5942dff`：total code
  `175527→179026`（+3499），production `127473→130864`（+3391），tests `48024→48132`（+108），
  unclassified保持30。production Python代码保持58140，反映adapter只是跨所有权边界移动；tests新增
  1个Python characterization文件。production增量由官方分类器计入7份刷新后的派生JSON。
- 旧Formal、pulse extension及`build_handoff_pulse_program.py`仍由缺省`staged_three_stage`公开流程可达，
  因此全部保留；Formal与pulse SHA-256分别保持
  `2E15EF94CC5ABEEA4E64E6C93FC9C0077B267C94300D2E6EFEDCCDBF5719B379`和
  `3497ABEFA378DC5D717E3EA7EA383826C09E53A664DBF12624219D4EECBF9CF8`。

本轮未启动SIMION、Fly、refine或其他物理解算，未修改PA、GEM、field、resource或Formal资产。
