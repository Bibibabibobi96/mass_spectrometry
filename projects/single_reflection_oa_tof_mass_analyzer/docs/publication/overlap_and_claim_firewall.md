# JASMS与Analytical Chemistry的重叠和claim防火墙

> `DOC_STATUS: ACTIVE_PUBLICATION_GOVERNANCE`

## 1. 分稿原则

先发表JASMS不会因期刊层级本身削弱后续Analytical Chemistry。真正风险是两稿在中心假设、核心方法、
主要数据、主图和结论上实质重复。因此两篇必须回答彼此不能替代的问题：

```text
Paper 1:
given p_source, what can the constrained analyzer control?

Paper 2:
how can p_source and the analyzer be physically co-designed
to create a new analytical measurement regime?
```

Analytical Chemistry当前作者指南明确要求披露相关先前工作，并把routine extension、closely related
work且缺少新insight、数据不足或缺乏广泛意义列为可能不送外审的情况：
<https://researcher-resources.acs.org/publish/author_guidelines?coden=ancham>。

## 2. 共享基础但不得重复声称为创新

两篇都可以引用：

- Wiley–McLaren空间聚焦；
- reflectron和dual-stage reflectron；
- orthogonal acceleration；
- space–velocity correlation及coupled focusing；
- multizone/high-order field-region思想；
- 本项目N=2/N=3/reflectron精确oracle；
- Taylor展开、条件统计、协方差、投影、SVD和Pareto优化；
- 已发布的求解器、峰算法和证据生命周期。

这些内容在任何一篇中都只能作为基础、方法或已发表前序工作。

## 3. Paper 1资产边界

Paper 1可以使用：

- 共同pre-pulse、detector-blind冻结源；
- 条件均值流形、有限厚度和残差模态；
- 完整OA—drift—dual-stage-reflectron到达时间映射；
- 受约束focusability和新增控制方向判据；
- two-zone、three-zone和source-weighted公平模拟；
- 多质量、多源工况、三维求解器与基础鲁棒性。

Paper 1不公开：

- 最终conditioner拓扑、尺寸、电压和波形；
- 产品自动调谐或制造补偿；
- 最终prototype A/B；
- 完整传输、占空比、灵敏度和动态范围Pareto；
- 真实样品分析终点。

## 4. Paper 2必须新增的内容

Analytical Chemistry必须具有：

1. 与Paper 1不同的中心假设；
2. 实际改变条件源分布的新conditioner或调理方法；
3. conditioner—OA—reflectron的联合稳健设计；
4. as-built、实测波形和样机A/B新数据；
5. 传输、接受度、占空比、灵敏度和稳定性；
6. 预定义真实分析终点；
7. Paper 1无法单独推出的新结论。

以下变化不构成一篇新的AC论文：增加粒子数、增加质量点、把SIMION换成COMSOL、把二维换成三维、
把同一分辨率主张做成样机，或在同一数据上增加装饰性样品图。

## 5. 数据和主图分配

| 资产 | Paper 1 | Paper 2 |
|---|---|---|
| 现有N=100 observed-source历史诊断 | 动机/假设生成 | 只引用 |
| 新条件源训练/验证/locked test | 核心 | 使用独立新工况或更完整实验源 |
| focusability、mode map和局部下界 | 核心主图 | 引用Paper 1 |
| two/three/source-weighted 3D比较 | 核心 | 只作为已知baseline方法 |
| final conditioner simulation | 不公开主要结果 | 核心 |
| measured waveform/as-built | 只做必要边界 | 核心 |
| prototype baseline/new谱图 | 不使用 | 核心 |
| transmission/duty/sensitivity | 不作为主要结果 | 核心 |
| real-sample dataset | 不使用 | 核心 |

Paper 2的主要数据、主图和分析必须在Paper 1锁定之后独立产生；不设置机械百分比，但内部审查应能
逐图说明为何它不是Paper 1图的扩展版。

## 6. 投稿前overlap audit

每次投稿前逐项填写：

| 项目 | 与既有工作相同 | 部分重合 | 完全新增 | 证据/说明 |
|---|---:|---:|---:|---|
| 中心假设 |  |  |  |  |
| 核心方法 |  |  |  |  |
| 主要数据 |  |  |  |  |
| 主图 |  |  |  |  |
| 主结论 |  |  |  |  |
| 分析终点 |  |  |  |  |

若Paper 2的中心假设、主要数据和主结论中有两项与Paper 1基本相同，应合并或重新定义研究，而不是
分投。

## 7. 一票否决条件

- Paper 2的主结论只是Paper 1结论前增加“experimentally”；
- 两篇共用同一批主要粒子、谱图或主要性能图；
- Paper 2没有主动source干预，只增加样本量或求解器；
- Paper 1提前公开最终conditioner或样机Pareto；
- 任一稿件以“首次OA+reflectron”“首次`z-v_z`”或“首次三区”为新颖性；
- 相关稿件、预印本或专利没有在投稿材料中披露。

## 8. IP顺序

```text
internal claim review
-> patentability/FTO review
-> patent filing when applicable
-> manuscript disclosure review
-> submission
```

论文重叠防火墙不等于专利自由实施结论。
