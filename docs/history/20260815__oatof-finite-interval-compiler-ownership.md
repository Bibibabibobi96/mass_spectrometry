# oaTOF finite-interval 原子编译器所有权迁移（2026-08-15）

> `DOC_STATUS: CURRENT_IMPLEMENTATION_RECORD`

## 目标与边界

本轮把RF→oaTOF integration中误置的finite-interval器件设计实现迁回
`single_reflection_oa_tof_mass_analyzer`项目。只改变代码所有权，不改变resolved合同role、输出路径、
数值语义、布局profile、GEM/PA、场、时间步、资源、执行入口或Formal资产，且未启动SIMION。

## 单一编译边界

项目公共`analysis/finite_interval_design_compiler.py`的
`compile_finite_interval_oatof_design`是以下事实的原子权威：

- 两区加速器电压和canonical轴向平移；
- 源中心、宽度及线性`z-vz`时间导数；
- 加速器—双级反射器一、二阶耦合、电压和能量包络；
- shield边界及frontend/flight-tube/reflectron rebuild plan。

integration只组装四个物理相空间量、source full width和stage-1 length后调用该API；profile路径及
run/checkpoint/cohort/粒子数只写入integration自己的layout审计元数据，不进入项目request或项目
resolved理论树。原先位于integration的理论函数调用、反射器求解和
`midgrid/backplate`逐字段写入均已删除。现有数值算法政策以项目模块内具名
`FINITE_INTERVAL_COMPILER_POLICY`为单一事实：电压降边界`100–1200 V`、1001采样点、`1e-8 V`电压容差。

## Characterization

迁移前先冻结全部9个活动finite profile的
`(resolved geometry, derived port, layout values)` canonical JSON SHA-256。首次迁移的9项逐项完全相同；
独立审查随后要求把provenance移出项目派生树，因此外层SHA显式换版。测试把新结构反向重构为旧结构后，
9项仍逐项命中原SHA，证明物理geometry、port、derived values和数值均未改变。项目API直连测试覆盖
原子闭合、严格物理字段白名单、integration provenance失败关闭和项目数值政策身份。

外层审计SHA换版如下；旧SHA只用于反向重构等价检查，新SHA是当前integration收据结构权威：

| layout profile | 旧SHA前缀 | 新SHA前缀 |
|---|---|---|
| `symmetric_10ev_source_z22_finite_interval_theory` | `0825D932` | `DB29B9ED` |
| `theory_source_z10_d1_3` | `7978E3EE` | `8C0677E1` |
| `zero_match_short_1mm` | `98FC3BBA` | `96810251` |
| `theory_source_z10_d1_4` | `9BAFEE37` | `D2E81D81` |
| `theory_source_z10_d1_5` | `93F85D16` | `7C514894` |
| `theory_source_z22_d1_3` | `428728EB` | `17547A56` |
| `zero_match_long_2p2mm` | `AE1E74FC` | `C826AA4D` |
| `theory_source_z22_d1_4` | `92B7FB67` | `B86135CB` |
| `theory_source_z22_d1_5` | `68245FB7` | `064C32DA` |

## 独立审查P1闭合

活动`accelerator_phase_space_match.json`删除了已由项目政策取代的`voltage_drop_bounds_V`、
`finite_interval_design.sample_count`和`voltage_tolerance_V`。全仓消费者审计同时修正了layout、
counterfactual和theory-order路径，电压边界、采样数和容差只读取项目
`FINITE_INTERVAL_COMPILER_POLICY`。旧`zero_match_long_all_ideal_theory_order_stage`属于已归档的
provisional证据，文件及冻结输入SHA保持逐字不变；新的活动诊断使用规范命名的`v2_successor`，同时
绑定去重后的活动phase-space配置和项目编译器政策文件。

## 验证收据

- oaTOF项目analysis全量：`206/206 PASS`，含Formal validation `PASS`；
- integration全量：`337/337 PASS`；campaign binding writer定向：`17/17 PASS`；
- P1定向测试：project compiler `4/4`、layout `8/8`、counterfactual `22/22`、theory-order
  `7/7`、family-source `17/17`，合计`58/58 PASS`；
- 运行时依赖官方刷新：更新7个派生绑定文件，随后`--check PASS`；
- `git diff --check`：`PASS`；
- documentation gate：`PASS`；runtime dependency binding `--check PASS`；
- repository text bytes：`PASS`；L1 `common/verify_changed.ps1`：`CHANGED_GATE=PASS`，28个
  changed paths；
- CLOC（相对`9b9ec39802f04362f3887e7e67f0ec654b847df5`，含同轮官方campaign binding writer修复）：
  Python生产代码净增130行、测试净增234行；JSON生产净增3476行，主要来自官方展开runtime binding
  及新增successor campaign，不能与手写Python代码混同。

本轮未启动SIMION，未修改GEM、PA、场、时间步、资源、执行入口或Formal资产，也未提交。
