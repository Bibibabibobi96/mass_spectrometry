# 单次反射正交加速飞行时间质量分析器当前状态

本文件是项目当前事实、资格与开放任务的唯一权威。机器精确值分别由`../config/`中的物理、数值、
resolved、分析和资产合同管理；实现细节见[`COMSOL.md`](COMSOL.md)、[`SIMION.md`](SIMION.md)与
[`CAD.md`](CAD.md)。2026-07-28以前的完整状态和时间线冻结在
[`history/20260728__pre-document-consolidation-project.md`](history/20260728__pre-document-consolidation-project.md)。

## 当前状态

- 当前批准设计为524 Da、+1正交加速TOF，双级环栈反射镜，一级10环、二级5环；粒子初始能量
  `5±0.4 eV`。
- 统一坐标以检测器有效面中心和精确一阶时间焦点为`z=0`，`+z`从加速器指向反射器。SIMION局部PA
  必须通过IOB变换映射到同一坐标。
- 2026-07-20的耦合纵向baseline是拆层前的历史Formal记录；它仍可追溯，但不再是当前资产身份。
- 科学合同、solver numerics和run instance拆层后，2026-07-29已以零物理变化的同源N=1000输入完成
  vNext验证与原子发布。`../config/project.json`、`formal_assets.json`、`formal_validation.json`和
  `simion_stable_entry.json`共同冻结当前Formal release；COMSOL GUI、SIMION GUI与SolidWorks CAD
  evidence均由独立evidence run及SHA绑定。一次性请求已
  [`归档`](history/20260729__formal-vnext-zero-change-requests.md)，不再是活动入口。
- 当前Formal加速器为闭合屏蔽结构，没有RF注入侧孔。RF项目的S2/S3候选链没有修改本项目baseline、
  MPH、SIMION包或CAD，也不构成整机Formal连接。
- RF四极杆离子光学到本分析器的0 mm与1 mm连接profile已以冻结N=100源完成真实COMSOL→SIMION重跑，
  并对只读oracle实现源身份、五级census和四组离散粒子事件集合精确一致。该结论只关闭零物理变化的
  功能迁移；本项目Formal资产保持只读且未被连接运行修改，连续相空间和整机资格仍未评价。

当前生命周期、capability与Formal asset状态均为`formal`。历史资产和旧结论只按其原始manifest
身份保留，不能替代或改写当前release。

## 物理与几何基线

精确参数、公式和舍入规则只认`../config/baseline.json`、`../config/resolved_geometry.json`及
`theory/`。用于识别设计的摘要为：

| 对象 | 当前设计 |
|---|---|
| 三栅加速器间距 | `d1=3.0 mm`、`d2=16.8 mm` |
| 反射器 | 一级120 mm；二级工程长度96.1563 mm |
| 反射器电位 | 一级压降1628.8001 V；背板2531.1999 V |
| 屏蔽罩 | 内半径350 mm；侧壁和端盖厚10 mm |
| 检测有效面 | 全局`z=0`、半径40 mm |
| SIMION日常加速器网格 | `xy=0.25 mm`、`z=0.05 mm`；`z=0.025 mm`仅为收敛参考 |

这些摘要不能用于重建求解器模型。修改焦点、电压或长度前必须重算理论并同步COMSOL、SIMION和CAD。

## 冻结验证记录

`../config/formal_validation.json`冻结的当前vNext同源N=1000结果为：

| 指标 | COMSOL | SIMION |
|---|---:|---:|
| 命中 | 1000/1000 | 1000/1000 |
| 平均TOF (us) | 71.35281164 | 71.35361153 |
| 直接质量FWHM (Da) | 0.01312031696 | 0.01099407843 |
| 质量分辨率R | 39938.06 | 47662.02 |

两端平均TOF差`0.79989 ns`，逐粒子TOF RMS差`1.06557 ns`，落点RMS差`0.30225 mm`。该release
通过冻结的Formal验证合同与独立GUI/CAD evidence；它是当前拆层合同下的可信Formal参考点，
不把单一分辨率差异解释为需要通过单独调网格、时间步或quality追平的目标。

质量分辨率统一定义为`R=m/FWHM_m`；窄峰时间域等价式为`R=T/(2·FWHM_t)`。近似高斯时才允许以
`2.3548×sigma`代替直接半高宽。

## 当前能力与边界

| 能力 | 当前范围 | 资格 |
|---|---|---|
| Static合同与候选编译 | baseline/science/numerics分层、resolved与源码冻结 | PASS |
| 结构Candidate | 零变化和`reflectron_midgrid_voltage`、N=100、真实COMSOL/SIMION/CAD receipt | Candidate结构合同；无性能声明 |
| 五质量候选 | 固定10/100/500/1000/2000 Da功能比较 | Candidate；不替代524 Da基线 |
| Formal跨求解器诊断 | 当前冻结资产的轴场、同坐标三维场和代表粒子轨迹 | Diagnostic；不改变Formal资格 |
| Formal当前设计 | vNext同源N=1000、COMSOL/SIMION/CAD及GUI证据原子冻结 | Formal |
| RF四极杆离子光学→本项目接口 | 下游只读分析器消费 | 整机Formal BLOCKED |

统一Formal跨求解器诊断入口已由成功run
`20260801_011500__analysis__cross__formal-diagnostics`完成真实只读验收：轴场比较覆盖源区101点、完整
加速段389点和反射器863点，同坐标三维场覆盖当前SIMION加速器PA共同插值域内75点，代表轨迹固定为
18/52/97号粒子。源区、完整加速段和反射器内部轴向场RMS相对差分别为`0.8437%`、`5.1833%`和
`0.000204%`；75点轴向分量RMS相对差为`10.3674%`。这些是无接受阈值的diagnostic结果，`PASS`只
表示导出、坐标配对、分析和manifest执行成功，不表示场或轨迹等价，也不改变Formal资格。

Candidate唯一公开入口为`../workflows/design_candidate/run_candidate.py`；必须提供获批request、run ID和
显式seed，依次执行粒子表、COMSOL、SIMION、CAD和结构验收。成功结果固定为
`candidate_accepted_not_promoted`，不含晋升。晋升必须由独立事务完成。

## 已知兼容边界

- COMSOL 6.4当前模型在极小求解粒子数路径存在非单调原生不稳定；日常使用N=100，逻辑小样本仅在
  无粒子间耦合时由同源N=100承载后分析前缀。该绕行不属于开放调查。
- SIMION透明栅网以`0.0001 mm`数值距离越过一格厚数值层。现有传输与资产门禁接受该实现；只有要求
  更严格逐粒子闭合、PA/栅网改变后出现相位敏感，或误splat时才重启自适应越层研究。
- 当前许可证不能使用SIMION 2026 `.wgem`，Candidate使用已验收的SIMION 2020 legacy-GEM四槽模板；
  许可证升级并完成隔离GUI/结构复验前不迁移路线。

详细失败矩阵与已关闭调查只在history保存，不作为current开放任务。

## 开放任务

1. **完成首次声明式experiment campaign运行。** v1表schema、参数角色、全表预检、单行/全表串行调度、
   campaign→selection→Candidate manifest哈希链和只读status/receipt入口已经实现；五质量点继续是
   `mass_spectrum_candidate`单run的联合内部条件，不展开为campaign行。活动
   `config/experiment_campaign.json`已预登记并授权`reflectron_midgrid_voltage`两行N=100结构比较；
   request、science profile与1600–1650 V窄物理envelope已原子对齐。剩余关闭条件是在保持商业求解器
   并发1、retry=0、无复用与无晋升边界下完成首次全表受控运行并冻结各行三件套与campaign receipt。
2. **复现交付。** 按需从自包含Formal目录生成不含日志和收敛参考的ZIP及独立SHA；ZIP不是第二资产权威。
3. **按需求启动的物理候选。** 轴对称圆形加速器、真实丝网、制造/装配误差预算和二维轴对称混合
   COMSOL模型均暂缓；任何一项启动都须重新闭合理论、三维场、传输、网格、跨求解器与CAD。

开放任务只写未完成动作和关闭条件。已完成的Candidate bootstrap、路径修复、receipt治理、历史失败
run和非零变量复验全部冻结在同日PROJECT history快照。

## 产物与历史

新活动产物根为`artifacts/projects/single_reflection_oa_tof_mass_analyzer/`。重命名前的Formal、
Candidate run及归档已以原manifest项目身份只读迁入该根的
`archive/20260801_130003__migration-snapshot__repo__oa-tof/legacy-project-root/`。保留证据保持原文件名、
SHA、身份、资格和声明边界；迁移后按根README独立裁剪的可重建重型载荷只由pruning manifest追溯，
不得追加新run。current文档不复制完整run ID清单。旧RF投影诊断只见
[`history/20260727__superseded-rf-handoff-diagnostics.md`](history/20260727__superseded-rf-handoff-diagnostics.md)，
不得恢复为活动生产入口。
