# oa-TOF 理论入口

本目录维护单次反射整机物理：上层统一框架定义共同状态、时钟、观测量和证据边界，下层文档维护
反射器及其与加速器的联合模型。独立加速器局部公式只由
[`orthogonal_accelerator 理论入口`](../../../orthogonal_accelerator/docs/theory/README.md)维护。
项目参数、状态和正式结果仍以`../../config/`、[`PROJECT.md`](../PROJECT.md)
和受manifest管理的运行证据为准。

## 按任务选择阅读路径

先确认 [PROJECT](../PROJECT.md) 的当前资格和本页下方的解释边界，再按任务读取一行；
无需为局部公式查询通读统一框架。涉及共同源、时钟、损失或声明范围时，必须同时读取对应框架章节，
不能只截取公式。完整建立或审查整机理论时才完整阅读统一框架与所用组件模型。

| 任务 | 所需正文 |
|---|---|
| 统一状态、时钟、观测量、三维事件或模型适用域 | [统一相空间框架](source_to_detector_phase_space_framework.md)的章节导航，读取所改对象及其适用边界 |
| 条件厚度、受约束控制方向、projector/SVD | [条件可聚焦性](conditional_phase_space_focusability.md)；先读第1–3节定义，再读目标公式及第7、10–12节限制 |
| 独立加速器的一阶焦面、affine初速、N=3精确时间 | [独立加速器理论入口](../../../orthogonal_accelerator/docs/theory/README.md)，按二区／affine／三区选择 |
| 反射镜局部一、二阶能量聚焦 | [双级反射器](dual_stage_reflectron.md)；若用于整机结论，再读[整机纵向耦合](oatof_oaaccelerator_coupling.md) |
| 从释放到探测面的纵向时间 | [整机纵向耦合](oatof_oaaccelerator_coupling.md)；affine源另读[z-vz耦合](z_vz_linear_phase_space_coupling.md) |
| 三区与反射器联合闭合、Γ3、有限束宽设计 | [三区整机理论](three_zone_accelerator_ideal_theory.md)，先读第1、7、9节边界，再按目录选择推导 |
| 论文实验矩阵、样本量、当前缺口 | [研究计划](../publication/paper_1_jasms/validation_and_evidence_plan.md)与[证据矩阵](../publication/paper_1_jasms/evidence_matrix.md)，无需重复读取全部理论 |

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

历史链接及旧候选合同仍使用[双区理论迁移入口](oaaccelerator_time_focus.md)；它只转向独立加速器正文，
不维护本项目的局部公式副本。
