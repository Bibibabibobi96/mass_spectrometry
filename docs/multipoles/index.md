# 多极杆通用理论

> **知识卡**：`document_id=multipoles.index` · `version=0.1.0` · `maturity=provisional` · `role=cross_project_design_family_knowledge`

本目录保存四极杆、六极杆、八极杆及一般二维多极杆的通用解析理论、统一符号、模型适用范围和参考验证语义。具体项目的当前几何、运行参数、候选状态和正式资产仍以项目 `README.md`、`docs/PROJECT.md` 和 `config/` 为权威。

> **边界**
>
> 本知识包回答“物理理论是什么、在什么条件下成立、应怎样验证”，不回答某个项目当前使用多少伏、哪个候选已通过或正式资产在哪里。

## 成熟度与权威边界

本目录当前整体标记为 `provisional`：正文和主要数值已经过人工审查与独立复算。四极杆L0中的Mathieu稳定区、质量尺度和电压合同已有项目内求解器无关参考实现及自动测试；六极杆和八极杆也已共同验证一般$2n$极理想场、伪势、绝热性尺度及有限长度L1传输实现。真实圆杆、寄生多极、边缘场和求解器交叉验证尚未达到同等覆盖，因此知识包整体仍不提升为`reference`。

解析理论的成熟度与项目产物生命周期是两个独立维度：

- L0–L5描述模型保真度，不自动授予 exploration、candidate 或 formal 资格；
- 项目生命周期资格由目标项目的合同、证据和门禁决定；
- 数值策略或工程经验仍需至少两个不同项目实际复用验证，才能提升为跨项目稳定经验。

根仓库规则高于本目录。本目录不建立多级杆“总项目”。`common/multipole`仅保存已经由六极杆、八极杆两个平级项目共同调用并通过门禁的理想场与L1参考实现；项目参数、真实电极几何和求解器模型仍由各项目维护。

## 文件职责

| 文件 | 内容 | 不保存 |
|---|---|---|
| [共同理论](foundations.md) | 一般 $2n$ 极场、坐标与电压约定、伪势、绝热性、边缘场和模型层级 | 四极质量筛选长推导 |
| [四极杆](quadrupole.md) | Mathieu 方程、稳定区、质量尺度、分辨率和质量过滤验证 | 当前项目参数与状态 |
| [高阶多极杆](higher_multipoles.md) | 六极杆、八极杆及更高阶多极杆的场、伪势、选型和验证 | 四极杆稳定图长推导 |
| [碰撞与模型](collisions.md) | 碰撞、冷却、RF加热、算法层级和碰撞验证 | 未经批准的数据集和项目当前结论 |

文件按物理模型边界拆分，而不是按每个公式拆分。完整的 L0–L5 定义只在[共同理论](foundations.md#模型保真度层级)维护，本入口不复制第二份定义。

## 按任务阅读

| 任务 | 最少阅读集合 |
|---|---|
| 统一坐标、电压、$r_0$ 与多极阶数 | [共同理论](foundations.md) |
| 推导 Mathieu 方程或计算稳定图 | [共同理论](foundations.md) → [四极杆](quadrupole.md) |
| 设计四极质量过滤器 | [四极杆](quadrupole.md) → 目标项目 `docs/PROJECT.md` 与 `config/` |
| 设计 RF-only 四极离子导向器 | [四极杆](quadrupole.md)；有气体时再读[碰撞与模型](collisions.md) |
| 设计六极杆或八极杆 | [共同理论](foundations.md) → [高阶多极杆](higher_multipoles.md) |
| 加入缓冲气体、冷却或反应池 | [碰撞与模型](collisions.md) → 目标项目机器合同 |
| 修改 COMSOL、SIMION 或 CAD 实现 | 目标项目 `docs/PROJECT.md` → 对应软件文档 |

## 全局约定速览

详细定义见[共同理论](foundations.md)：

- 杆轴为 $z$，横向平面为 $x$–$y$；
- 理想 $2n$ 极装置有 $2n$ 根交替极性电极，$n$ 是势函数的径向阶数；
- $r_0$ 是轴线到理想电极边界的特征内切半径，不是圆杆半径；
- $V$ 表示一个相位组相对公共偏置的 RF 零到峰值；公共偏置为零时即相对地，差分峰峰值必须另存字段；
- 电荷写成 $Q=sze$，质荷比为 $\mu=m/(zu)$，数值单位为 Th；
- 正弦理想四极场可使用 Mathieu 方程，非正弦四极驱动使用 Hill/Floquet；六极杆和八极杆的完整运动通常是非线性的。

## 与具体项目的关系

项目通过现有 README、PROJECT 和机器配置引用所需理论，不复制本目录正文，也不要求预建 `PHYSICS.md` 或 `physics_contract.json`。只有实际实现证明现有合同无法清晰表达物理模型选择时，才评估新增机器合同。

当前 [RF四极杆项目](../../projects/rf_quadrupole_collision_cooling/README.md)、[RF六极杆项目](../../projects/rf_hexapole_ion_guide/README.md)和[RF八极杆项目](../../projects/rf_octupole_ion_guide/README.md)共同组成逻辑上的RF多极杆离子光学设计族，但保持平级项目边界。任何项目是否具备 Candidate 或 Formal 资格，只查其 `docs/PROJECT.md` 和机器门禁。

新论文、截面数据或模型在进入项目前，应固定来源和版本，归一化坐标、单位及电压约定，声明适用域和不确定度，并建立与结论相称的独立验证。未经验证的内容保持 `provisional`，不能自动修改 baseline、验收阈值或正式 CAD。

## 图示与复现

图片以普通 Markdown 插入对应正文位置，二进制文件统一放在 `figures/`。其中赝势尺度、四极杆扫描线通带和设计闭环图由[`figures/generate_figures.py`](figures/generate_figures.py)生成；修改公式、颜色或图例后应重新运行脚本并复查图片，避免静态图与正文漂移。

## 相关仓库文档

- [仓库权威与知识路由](../../README.md)
- [通用验证方法](../VALIDATION_METHODS.md)
- [平台长期愿景](../VISION.md)
- [跨项目路线图](../ROADMAP.md)
