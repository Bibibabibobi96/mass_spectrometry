# Paper 2：Analytical Chemistry 研究与证据计划

> `TARGET: ANALYTICAL_CHEMISTRY`
>
> `STATUS: LONG_TERM_PLAN / METHOD_AND_PROTOTYPE_NOT_YET_ESTABLISHED`

## 独立科学问题

Paper 1冻结给定source distribution，回答分析器能控制什么。Paper 2必须主动改变source distribution，
回答：

> 能否通过可实现的phase-space conditioner及其与OA、reflectron的联合稳健设计，在真实波形、制造误差、
> 空间电荷和探测器条件下，实验性移动resolution—transmission—acceptance—duty-cycle—sensitivity
> 前沿，并改善一个预定义分析终点？

它不是Paper 1的“实验完整版”，也不能把Paper 1的focusability重新称为新理论。

## 题目候选

只有实测结果支持相应动词时才选用：

- **Active Phase-Space Matching Expands the Acceptance–Resolution Frontier of Orthogonal-Acceleration Time-of-Flight Mass Spectrometry**
- **Joint Ion-Source Conditioning and Analyzer Design for High-Acceptance Orthogonal-Acceleration TOF Mass Spectrometry**
- **Phase-Space-Matched Ion Injection Improves Sensitivity at Fixed Resolving Power in Orthogonal-Acceleration TOF Mass Spectrometry**

只有模拟时不得在题目中提前使用`expands`或`improves`。

## 候选新方法

先行工作风险与允许措辞只查[claim 注册表](../prior_art_claim_registry.md)。
具体拓扑、波形或控制律须先完成既定公开审查；候选变换写为：

$$
\mathcal C_{\boldsymbol\alpha}:
p_{\mathrm{in}}(\mathbf u)
\longrightarrow
p_{\mathrm{out}}(\mathbf u;\boldsymbol\alpha),
$$

其中`α`可包含RF、DC、几何、终止波形和相位。目标不是单独最小化`σ_z`或`σ_vz`，而是改变：

- 条件均值流形；
- 条件协方差、尾部和主导模态；
- source modes与分析器可行控制子空间的对齐；
- 传输、接受度和占空比。

可能结构在IP审查前只以功能类别记录，不在公开计划中保存最终电极、尺寸、电压、波形或自动控制。
科学新意必须落在具体机制及其相对于充分重优化既有conditioner/分析器基线的可重复前沿移动，不能落在
“改变source distribution”这个已知目标。

## 与Paper 1的理论接口

Paper 1给出source-conditioned残差代价和可控性诊断。Paper 2的联合设计对象为：

$$
\min_{\boldsymbol\alpha,\boldsymbol\theta}
\left[
J_\perp(\boldsymbol\theta;p_{\mathrm{out}}(\boldsymbol\alpha)),
\Delta t_{\mathrm{FWHM}},P_{\mathrm{tail}},
1-\eta,1-D,\mathcal R_{\mathrm{eng}}
\right].
$$

最终目标必须直接使用有限粒子峰、尾部、传输、接受度、占空比、工程良率和测量链，而不是仅优化局部
协方差或导数。

## Paper 2必须新增的理论和模拟

1. conditioner的真实三维时变动力学，包括RF相位、分段DC、非绝热边缘和横向耦合；
2. `mu_out`、`Sigma_out`、尾部和多模态的source transformation；
3. conditioner—OA—reflectron联合有限分布目标；
4. measured tolerance下的期望值、分位风险或CVaR稳健优化；
5. ion load与空间电荷边界；
6. pulse、detector、TDC和处理链对可测峰的卷积；
7. fully reoptimized baseline与新方案的盲化Pareto比较。

最低模拟架构：

```text
A. fully reoptimized two-zone OA baseline
B. fully reoptimized three-zone OA
C. conditioner + two-zone OA
D. conditioner + three-zone OA
```

四臂使用相同真实输入源、工程边界、优化预算、粒子ID、detector和峰算法。

## 必须新增的工程与实验

### 实测波形

在实际电极、馈通、电缆和负载条件下测量OA各电极、conditioner termination、触发对齐、过冲、振铃、
shot-to-shot jitter、warm-up和长期漂移。

### As-built几何

将电极间距、平行度、孔偏心、栅平整度、reflectron倾斜、detector位置和重装变化写入可追溯模型。

### 同平台A/B

优先在同一平台切换baseline和new configuration，并冻结上游源、真空、detector/readout、数据处理、
输入离子通量、采集时间和优化投入。若使用两台样机，必须额外排除平台差异这一混杂因素。

### 全性能向量

至少报告：

- 多质量分辨率、质量准确度、尾部和旁峰；
- transmission、accepted phase space和duty cycle；
- sensitivity和dynamic range；
- ion-count dependence与空间电荷；
- 日内/日间稳定性、重启与重装重复性；
- 电压和温度漂移。

## 实验性Pareto前沿

强主张至少满足一种：

$$
R_{\mathrm{new}}>R_{\mathrm{base}}
\quad\text{at fixed transmission},
$$

$$
\eta_{\mathrm{new}}>\eta_{\mathrm{base}}
\quad\text{at fixed }R,
$$

或

$$
S_{\mathrm{new}}>S_{\mathrm{base}}
\quad\text{at fixed }R\text{ and acquisition time}.
$$

单独得到更高理论`R`、通过裁束得到窄峰或改变detector/data processing都不构成前沿移动。

## 分析应用

至少预注册一个具有实际复杂度的分析终点，例如：

- 复杂标准混合物中的邻近峰、低丰度峰或同位素包络；
- 肽段/蛋白消化物的低丰度鉴定、谱质量或throughput；
- 公司目标市场样品的LOD/LOQ、interference rejection、动态范围或定量重复性。

真实样品不是装饰性末图。必须建立：

```text
source-mode change
-> analyzer/measured-peak change
-> transmission/sensitivity change
-> predefined analytical endpoint
```

## 候选主结论

只有全部证据闭合后才允许：

> Under identical source-input, physical-envelope, voltage, detector, and acquisition constraints, active phase-space matching reduced the conditional source modes to which the complete analyzer remained timing-sensitive, shifted the experimentally accessible resolving-power–transmission–acceptance frontier, and improved a predefined analytical endpoint relative to a fully reoptimized conventional baseline.


## 验证工作包

本计划本身不授权昂贵模拟、硬件采购、样机或外部披露；每个工作包需要冻结的执行合同。

## Gate A：IP与科学差异

### 动作

- conditioner、RF/DC序列、自动匹配和波形补偿的patentability/FTO；
- 明确可公开、先专利和trade-secret内容；
- 完成与Paper 1的中心假设、方法、数据、图和结论overlap audit。

### 关闭条件

- 可公开范围书面冻结；
- Paper 2不依赖重复Paper 1主claim；
- 主要新方法和主要新数据可以独立说明。

## Gate B：conditioner原理与可实现性

### 动作

- 建立真实三维时变conditioner模型；
- 检查辛相空间交换、非线性、RF phase kick、横向耦合和孔径；
- 输出detector-blind `p_out`，比较条件均值、协方差、尾部和传输；
- 证明不是只通过裁束或损失降低峰宽。

### 关闭条件

- 至少一种结构在真实场和工程边界内改变Paper 1识别的主导残差；
- 输入/输出母cohort与损失完整闭合；
- 结果不依赖把相空间匹配误写成冷却。

## Gate C：联合稳健模拟

### 动作

- 对A–D四种架构分别充分重优化；
- 使用多个source condition、质量、ion load和locked test；
- 加入as-designed tolerance、波形、detector和electronics；
- 计算`R–transmission–acceptance–duty-cycle–sensitivity` Pareto及良率。

### 关闭条件

- 新前沿在相同约束和优化预算下支配或显著扩展baseline；
- 优势在关键公差、jitter和空间电荷下保留；
- 由Paper 1 mode/focusability诊断解释，而不是黑箱优化偶然点；
- 独立求解器或实现复核关键工况。

## Gate D：波形、as-built与样机A/B

### 动作

- 完成电极端实测波形和不确定度；
- 将机械计量转成as-built模型；
- 同平台baseline/new A/B并冻结输入通量、采集时间和数据处理；
- 比较预测、实验和残差来源。

### 关闭条件

- 样机收益可重复并有置信区间；
- 输入通量、detector和采集条件一致；
- 预测—实验差异可由误差预算解释；
- 没有靠后筛选、不同调参投入或不同平台混杂获得优势。

## Gate E：真实分析终点

### 动作

- 在查看最终数据前冻结样品、终点、统计模型和成功阈值；
- 使用独立new dataset比较baseline/new；
- 建立离子光学改善到分析结果的因果链和替代解释检查。

### 关闭条件

- 至少一个预定义endpoint具有统计和实际意义；
- 改善在重复、日间稳定性和合理负载范围内存在；
- 分析结论不是由不同采集时间、样品批次或数据处理制造。

## Gate F：AC投稿

全部满足后才冻结稿件：

1. 新方法不是Paper 1参数扩展；
2. prototype A/B和real-sample数据完全新增；
3. Pareto优势对充分重优化baseline成立；
4. measured tolerance下优势仍存在；
5. 至少一个分析终点改善；
6. Paper 1诊断能够解释方法为何有效；
7. IP和公开范围完成；
8. overlap audit和相关工作披露完成。

任一项不满足时，不以增加质量点、粒子数、样机照片或装饰性样品替代缺失的新测量能力。

## 数据隔离

- Paper 1的locked source和主要峰图不作为Paper 2主要数据；
- Paper 2使用新的最终conditioner locked simulation、prototype和sample dataset；
- 已发表的focusability、pulser或数字孪生方法只引用；
- 所有共享装置、代码、数据来源和相关稿件在cover letter中主动披露。

## 当前状态

Gate A–E均未关闭。当前只允许开展先行工作/IP评估和Paper 1证据闭环；本计划本身不授权启动昂贵模拟、
硬件采购、样机制造或外部披露。
