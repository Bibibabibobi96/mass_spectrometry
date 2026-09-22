# 正交脉冲加速器项目状态

本文件维护独立器件的当前边界、资格与开放任务。操作和理论由[项目入口](../README.md)导航。

## 项目边界

本项目拥有独立正交脉冲加速器的理论、计算、参数化器件几何和验证。二区／三区是
[component_contract.json](../config/component_contract.json) 声明的结构变体，各自保持输入、几何
和证据身份。仪器拥有系统装配、源到检测器时间与联合聚焦；本项目不继承 oa-TOF 或 MR-TOF 的资格。

## 当前能力

- 领域源码、活动消费者和依赖清单已从 oa-TOF 与原公共层迁入；仪器适配器负责参数投影和装配。
- 提供二区时间焦距、带位置—速度相关的时间导数、三区局部精确时间及几何生成。
- 提供固定净增益下首区压降对有符号理想焦距的解析灵敏度；该 API 不决定仪器位姿，也不授予真实
  三维焦点资格。其导数通过非对称释放位置的独立差分与电压齐次尺度律回归。
- SIMION 实现包括矩形环／屏蔽、二区／三区方圆截面、显式参数的原生 PA 构建；COMSOL 提供器件几何构建。
- 提供者身份、API、单位、结构变体和源路径通过 `analysis/component_contract.py` 校验。
  消费者冻结其实际闭包；不能据此宣称整个 Python 环境均已脱离工作树。
- `api_version=2` 提供二区封闭端需求编译接口：消费者只能提交圆柱源、焦点、y/z 紧凑化、
  数值包络/网格和刚体装配需求。组件固定生成实心正 z repeller、实心接地后盖与负 z 出口栅，
  并自行派生首/二区间隙、支撑栅、二区环和外壳；消费者不能通过请求改写电极拓扑或相对几何。
  该 profile 的物理尺寸唯一写在 `config/component_contract.json` 的 `geometry_profiles`，并随提供者合同冻结；
  编译结果的 `layout.to_dict()` 是供消费者冻结的唯一已解析几何投影，包含 profile 身份、局部出口/repeller、
  源完整 z 包络、环面、孔径及静态外包络；消费者不得重新用低层 CSG 或尺寸映射重建该拓扑。
  当前 `closed_two_zone_compact_mr_axial_r2` profile 固定首区 6.0 mm、二区 30.0 mm；以 MR 的
  `4371.2351565 eV/q` 轴向目标，理论种子为 repeller `4970.1626568 V`、grid1
  `3772.3076562 V`、exit `0 V`，其一维一阶时间焦位于出口面。对半径 1 mm、高度 1 mm 的圆柱源，
  静态验证首区完整 z 向容纳；孔径 y 高 16 mm、电极外高 20 mm、接地壳外高 24 mm，出口面至封闭后盖
  的轴向长度为 40 mm。它们是该固定拓扑及已声明间隙/壁厚的静态包络：真实三维 SIMION 场聚焦、数值收敛
  和全局紧凑最优性仍须独立验证。
- `config/two_zone_component_focus_campaign.json` 冻结封闭二区候选的组件级首轮 N=100 验收定义：半径
 1 mm、高 1 mm 圆柱源、全九电极候选电压、-z 焦面、轨迹数值设置、100%硬传输门槛和
 1.5 ns 峰峰到达时间展宽告警阈值。验收要求全部粒子以负 z 方向穿过声明焦面且事件身份一致；超过时间阈值
 仍发布候选并在 receipt 中记录 warning 与实测值；横向 RMS 仅记录
  圆柱释放的束团诊断，不是加速器横向聚焦门槛。`analysis/component_focus_pa_plan.py` 从焦面和两侧数值 padding
  派生局部出口及最小 z 域；`simion/run_component_focus_pa.ps1`只发布一套`PA# + PA0..PA9`原生 Fast Adjust family，不创建 detached response-bank。`analysis/component_focus_analysis.py` 只验证共享层产生的 canonical
  particle-state 与 SIMION 事件日志的身份、全粒子终态、负 z 穿越、传输和纵向时间聚焦。原生场未通过时，OA 自动在同一 PA、release、电压和数值设置上追加“仅一区理想化、仅二区理想化、全理想化”三臂，以各臂峰峰展宽直接定位有限场贡献；理想化只在 runtime efield 回调替换对应区域，绝不改变 PA。它不产生源；运行器只读已发布 `.pa0` 并执行内存 Fast Adjust，不复制、Refine、重建或发布 PA，也不把组件证据扩展为系统分辨率资格。
- 对负 z 封闭二区，组件以出口为坐标原点，但理论的首区位置从 repeller 向出口计量。编译器把半径 1 mm、高 1 mm 圆柱的中点派生为出口上游 `gap_2 + gap_1/2`；SIMION 投影在物化共享 release 前以 provider plan 验证整个 cohort 位于 grid1 与 repeller 之间。它只影响 run-local release/FLY2，不改变已发布 PA 的几何、缓存或 Fast Adjust family。
- `simion/run_component_focus_workflow.ps1` 是组件 N=100 的提供者自动入口：它消费调用方的窄 request 和公共 release spec，在任何 PA 操作前编译/冻结 profile、campaign 与 plan，再复用现有 PA cache runner 和 flight runner 各一次，最后把两个子 manifest 身份与同一冻结 release 写入父 receipt。它没有第二套 PA 构建实现，release 的速度、能量和 particle states 只在 flight child 中物化，不能污染 PA cache。
- 初始理论工作点未同时达到完整 N=100 传输及声明的峰峰时间门槛时，workflow 自动调用
  `simion/run_component_focus_fast_adjust.ps1`。该控制器只在请求给出的首区压降边界内执行 3--5 次串行
  Fast Adjust 飞行，直接最小化已有 `focus_analysis.json` 的峰峰时间；每个 trial 复用同一已发布 native PA
  family，禁止 PA build、copy 和 Refine。只有某 trial 通过完整硬门时才发布其 accepted campaign 和
  MR runtime receipt；搜索耗尽时 workflow 失败并扣留 MR receipt。直接执行入口要求现有 PA build run：
  `simion/run_component_focus_fast_adjust.ps1 -PABuildRunPath <provider-pa-run> -CampaignPath <resolved-campaign> -ReleaseSpecPath <common-release> -Gap1VoltageDropBoundsV <min>,<max>`。
- 组件飞行可接受调用方提供的 repository ion-release JSON；该 JSON 必须使用
  `orthogonal_accelerator_exit_origin_v1`，并作为 run-local source receipt 与 campaign 输入冻结。它可声明
  初始动能和任意三维方向：例如 MR 的约 5 eV `+y` 漂移与加速器独立的 `-z` 静电场同时存在。该 release
  不是 PA 几何输入，也不进入 PA cache identity；改变它只建立新的飞行证据，不复制、Refine 或重建 PA。
- 参考 CLI 的递归预期值比较与 OA 理论入口共用 `common/contracts/expected_values.py`；
  容差仍由输入合同声明。共享模块仅在 CLI 比较阶段加载，器件物理 API、公式和现有诊断文本不变。

## 参数与坐标

当前交付是可调用机制，尚无独立器件 baseline。描述符的 baseline/resolved 为空；旧 OA 电压、MR 孔径
及测试样例均不是本项目默认硬件。各 API 显式声明局部轴、单位和变体，仪器负责刚体映射：位置包含
平移，速度只旋转。第一时间焦面、自由飞行观察面和机械检测器必须分别解释。

## 资格与限制

| 对象 | 已有依据 | 边界 |
|---|---|---|
| 解析与依赖机制 | 迁移时纯分析、消费者与冻结依赖回归通过 | 不证明三维场或传输 |
| 原生 PA 构建与电压 | 迁移样例构建、独立几何／电压抽查已执行 | 使用旧 OA 样例，不是独立 baseline |
| 迁移构建 run | 求解阶段完成，run 整体因容量治理失败 | 不得报告整体验收通过 |
| MR 矩形孔壁修复 | `notin_inside` 保留边界；原生复验由 MR 记录 | 旧 PA 不继承新几何资格 |
| GUI、CAD、数值收敛、Candidate／Formal | 尚未完成独立器件交付证据 | BLOCKED |

迁移时门禁阻塞、测试数量、容量失败、原生抽查和旧焦距少因子 2 的修正过程冻结于
[迁移证据](history/20260911__component-migration-evidence.md)。该记录保留负结果，不把当时的全仓阻塞
描述为永久现状。当前 MR 工作及其在途修复仍由 MR 项目验证，本次文档整理没有复跑或提升资格。

## 开放任务

1. 冻结独立器件 baseline，以及二区／三区各自完整同源几何和数值合同；关闭条件是显式变体身份与重建一致。
2. 分别补充真实求解器、完整源穿越和空间／时间离散证据；解析与迁移样例不能代替。
3. 完成各变体 GUI 重开、CAD 交付和资产身份后再申请相应资格。
4. MR 消费者按修正后的焦距与孔壁语义重新派生并验收；关闭结论写 MR 项目，不复制整机运行进展。

## 产物

独立器件新运行归 `artifacts/projects/orthogonal_accelerator/`。既有 OA/MR run、冻结包和 Formal
资产按原身份保留；本次领域迁移不改写它们。
