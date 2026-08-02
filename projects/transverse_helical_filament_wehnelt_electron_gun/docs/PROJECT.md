# 横置螺旋灯丝Wehnelt电子枪当前状态

本文件是项目当前事实、资格与开放任务的唯一权威。COMSOL实现见[`COMSOL.md`](COMSOL.md)；选型依据
和旧实验见[`history/PROJECT_HISTORY.md`](history/PROJECT_HISTORY.md)；2026-07-28以前的完整runner
故障与修复时间线冻结在
[`history/20260728__pre-document-consolidation-project.md`](history/20260728__pre-document-consolidation-project.md)。

## 当前基线

当前物理基线为5匝横置螺旋钨丝、2700 K热发射的Wehnelt电子枪，面向EI离子源的电子利用率，不声明
成像级轴对称束斑。活动源码链为：

1. `../phase1_geometry_coil_transverse.m`；
2. `../phase2_electrostatics_coil_transverse.m`；
3. `../phase4_thermal_emission_coil_transverse.m`。

机器参数链为`config/baseline.json + config/numerical_modes.json → analysis/resolve_contract.py →
config/resolved_model.json`。MATLAB只消费resolved并绑定GUI参数，不从源码、环境或旧MPH回退物理值。
实心阴极与轴向线圈源码已冻结到
[`history/20260713__pre-transverse-wehnelt-lineages.md`](history/20260713__pre-transverse-wehnelt-lineages.md)。

## 资格状态

| 层级 | 当前证据 | 状态 |
|---|---|---|
| Static | 合同、resolver、MATLAB绑定和项目门禁 | PASS |
| build-only | 真实R2025b/COMSOL 6.4三阶段构建，冻结输入与manifest闭合 | PASS |
| 功能粒子求解 | `functional_reference`尚未注册或运行 | NOT RUN |
| Candidate | 无受治理N≥100功能证据 | BLOCKED |
| Formal | 旧MPH早于现行合同，最终CPT未完成现行GUI Compute | BLOCKED |

当前闭合build-only证据只证明几何、网格、静电/CPT模型树、电子质量/电荷、`Freeze`壁面和GUI参数
绑定；没有运行静电或粒子求解器。旧34.18%收集效率是历史结果，不能作为当前性能结论。

## 当前物理与实现限制

- baseline是电子species、质量、电荷、发射分布、材料身份和终态语义的唯一权威。
- 钨只表示材料身份；尚未建立Richardson发射率或真实束流，测试粒子不支持`beam_current`声明。
- COMSOL默认随机采样seed尚未冻结，当前单次粒子实现不可复现。
- 非有限末态只能报告为未分类，不得推断为灯丝或Wehnelt自吸收。
- 横置Wehnelt参数扫描尚未建立；旧phase5属于轴向灯丝，只支持非单调性的历史假设。

## 开放任务

1. 为`functional_reference`建立受治理的N=100运行器，冻结可复现母样本、seed、逐粒子身份、终态和
   完备损失分类；建立真实收集面/穿越事件后才允许定义收集效率。
2. 在功能run中形成完整run config、summary、manifest与资产SHA，并重开最终CPT模型完成GUI
   Study Compute；通过前不得进入Candidate评审。
3. 只有下游设计明确需要时才建立横置谱系参数扫描或EI源接口合同；不得复用轴向phase5的具体最优值。

已修复的超时终态分类、空manifest、缓存污染、冻结闭包和clean retry不再列为开放任务，完整证据只见
同日history快照。

## 产物边界

新活动产物根为`artifacts/projects/transverse_helical_filament_wehnelt_electron_gun/`。当前没有通过
现行门禁的Formal资产。旧模型、结果与谱系按原manifest身份只读保存在
该根的`archive/20260801_130004__migration-snapshot__repo__wehnelt-electron-gun/legacy-project-root/`，
不改写、不追加新run，也不改变原资格和声明边界；
新运行只进入活动根的`runs/<run_id>/`并遵守根README三件套与manifest合同。
