# Paper 2：Analytical Chemistry范围、候选主张与新增工作

> `TARGET: ANALYTICAL_CHEMISTRY`
>
> `STATUS: LONG_TERM_PLAN / METHOD_AND_PROTOTYPE_NOT_YET_ESTABLISHED`

## 1. 独立科学问题

Paper 1冻结给定source distribution，回答分析器能控制什么。Paper 2必须主动改变source distribution，
回答：

> 能否通过可实现的phase-space conditioner及其与OA、reflectron的联合稳健设计，在真实波形、制造误差、
> 空间电荷和探测器条件下，实验性移动resolution—transmission—acceptance—duty-cycle—sensitivity
> 前沿，并改善一个预定义分析终点？

它不是Paper 1的“实验完整版”，也不能把Paper 1的focusability重新称为新理论。

## 2. 题目候选

只有实测结果支持相应动词时才选用：

- **Active Phase-Space Matching Expands the Acceptance–Resolution Frontier of Orthogonal-Acceleration Time-of-Flight Mass Spectrometry**
- **Joint Ion-Source Conditioning and Analyzer Design for High-Acceptance Orthogonal-Acceleration TOF Mass Spectrometry**
- **Phase-Space-Matched Ion Injection Improves Sensitivity at Fixed Resolving Power in Orthogonal-Acceleration TOF Mass Spectrometry**

只有模拟时不得在题目中提前使用`expands`或`improves`。

## 3. 候选新方法

2026-08-25预审已确认，RF/DC ion guide、碰撞冷却、beam expander、periodic lens、OA内guide mode、
spatial-temporal correlation和upstream conditioner均已有论文、厂商实现或专利。`active phase-space
conditioner`只能是功能类别，不能作为宽泛新颖性主张；证据见
[`prior_art_search_audit_20260825.md`](../prior_art_search_audit_20260825.md)。未来方法必须先通过具体拓扑、
波形或控制律的IP/FTO审查，再讨论以下变换：

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

## 4. 与Paper 1的理论接口

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

## 5. Paper 2必须新增的理论和模拟

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

## 6. 必须新增的工程与实验

### 6.1 实测波形

在实际电极、馈通、电缆和负载条件下测量OA各电极、conditioner termination、触发对齐、过冲、振铃、
shot-to-shot jitter、warm-up和长期漂移。

### 6.2 As-built几何

将电极间距、平行度、孔偏心、栅平整度、reflectron倾斜、detector位置和重装变化写入可追溯模型。

### 6.3 同平台A/B

优先在同一平台切换baseline和new configuration，并冻结上游源、真空、detector/readout、数据处理、
输入离子通量、采集时间和优化投入。若使用两台样机，必须额外排除平台差异这一混杂因素。

### 6.4 全性能向量

至少报告：

- 多质量分辨率、质量准确度、尾部和旁峰；
- transmission、accepted phase space和duty cycle；
- sensitivity和dynamic range；
- ion-count dependence与空间电荷；
- 日内/日间稳定性、重启与重装重复性；
- 电压和温度漂移。

## 7. 实验性Pareto前沿

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

## 8. 分析应用

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

## 9. 候选主结论

只有全部证据闭合后才允许：

> Under identical source-input, physical-envelope, voltage, detector, and acquisition constraints, active phase-space matching reduced the conditional source modes to which the complete analyzer remained timing-sensitive, shifted the experimentally accessible resolving-power–transmission–acceptance frontier, and improved a predefined analytical endpoint relative to a fully reoptimized conventional baseline.

## 10. 当前边界

当前仓库尚没有：

- 已选定且通过IP审查的conditioner；
- 相对于SVCF、RF/DC ion-guide conditioning、spatial-temporal correlation和upstream conditioner专利族
  的逐权利要求差异；
- conditioner—OA—reflectron联合稳健优化；
- 实测电极端波形和as-built闭环；
- prototype baseline/new A/B；
- transmission/duty/sensitivity完整Pareto；
- real-sample endpoint。

因此Paper 2目前只具备科学路线和go/no-go定义，不具备投稿条件或性能claim。
