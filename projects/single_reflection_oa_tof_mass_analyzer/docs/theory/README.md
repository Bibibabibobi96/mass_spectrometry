# oa-TOF 理论入口

本目录只维护一套项目物理真相：上层统一框架定义共同状态、时钟、观测量和证据边界，下层组件文档
保存精确特例和可执行oracle。项目参数、状态和正式结果仍以`../../config/`、[`PROJECT.md`](../PROJECT.md)
和受manifest管理的运行证据为准。

## 阅读顺序

### 统一框架

1. [`source_to_detector_phase_space_framework.md`](source_to_detector_phase_space_framework.md)：
   从共同pre-pulse条件源到pulse-relative探测时间、有限孔径、三维事件、工程误差和测量链的多变量
   canonical框架；同时规定时变场、波形时钟和有限动态区渡越边界。
2. [`conditional_phase_space_focusability.md`](conditional_phase_space_focusability.md)：
   条件均值流形与有限厚度、source-weighted受约束控制子空间、projector/SVD和新增控制方向判据。

### 组件精确模型

- [`oaaccelerator_time_focus.md`](oaaccelerator_time_focus.md)：静止释放、N=2双区正交加速器和一阶焦面；
- [`z_vz_linear_phase_space_coupling.md`](z_vz_linear_phase_space_coupling.md)：detector-blind affine
  `z-v_z`特例及随机残差入口；
- [`dual_stage_reflectron.md`](dual_stage_reflectron.md)：二级反射镜局部一、二阶能量聚焦；
- [`oatof_oaaccelerator_coupling.md`](oatof_oaaccelerator_coupling.md)：从释放到探测面的整机一维纵向耦合；
- [`three_zone_accelerator_ideal_theory.md`](three_zone_accelerator_ideal_theory.md)：N=3分段均匀场、
  `A1–A4`、`Γ3`与隔离阶段漏斗。

统一框架不复制组件的完整公式；组件文档也不单独定义论文新颖性。局部反射镜闭式解不包含加速器在
一阶焦面处仍存在的二阶时间曲率，不能直接作为整机二阶聚焦结论。`D1/D2/D3=0`和`Γ3`只描述指定
源链上的局部closure，不能替代有限条件厚度、有限焦区、直接峰形、传输或工程稳健性。局部导数阶、
端点等时、时间曲线转折点数和空间轨迹交点数是不同概念；arrival-time envelope也不等于概率峰FWHM。

## 理论标签

| 标签 | 含义 |
|---|---|
| `FOUNDATIONAL` | 经典理论或标准数学，只能引用和实现 |
| `PROJECT_ORACLE` | 本项目精确特例、回归实现或失效关闭条件 |
| `PAPER_1_CANDIDATE` | JASMS候选贡献，必须完成先行工作和证据闭环 |
| `PAPER_2_EXTENSION` | Analytical Chemistry的主动调理与实验扩展 |
| `EVIDENCE_REQUIRED` | 尚不能表述为已验证结论 |

三区文档是100 Th集成问题的求解器无关 `Functional / PROVISIONAL / POST_PILOT` 理论评估，
不改变524 Da当前Formal。它的 `zone1/zone2/zone3` 也不是现有双区COMSOL、SIMION、CAD或
`FULL_DOMAIN_PIECEWISE_IDEAL_FIELD` profile已经实现的工程拓扑。

Paper 1与Paper 2的独立科学问题、证据计划和重叠防火墙只见
[`publication/README.md`](../publication/README.md)，不在理论正文复制。

## 分辨率时钟边界

分辨率公式、飞行时间零点及absolute instrument clock的声明边界只查
[`PROJECT.md`](../PROJECT.md)的分辨率段；本目录不建立第二份权威。

旧 DOCX 保留为 superseded 历史输入，不再作为活跃公式权威：

- [`三栅加速器总长度符号推导.docx`](../history/20260721__superseded-theory-docx/三栅加速器总长度符号推导.docx)；
- [`单次反射TOF二级反射镜等时聚焦推导.docx`](../history/20260721__superseded-theory-docx/单次反射TOF二级反射镜等时聚焦推导.docx)。

原始重写投稿包及 SHA 已冻结在 `../history/20260720__oatof-theory-refactor-review/`；审查清单见
`../history/20260720__oatof-theory-refactor-review.md`。归档不参与活跃程序导入。
