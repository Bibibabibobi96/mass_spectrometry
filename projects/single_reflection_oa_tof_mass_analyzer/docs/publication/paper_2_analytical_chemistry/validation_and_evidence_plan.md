# Paper 2：Analytical Chemistry验证与证据计划

> `STATUS: FUTURE_WORK / NOT_AUTHORIZED_FOR_EXECUTION_BY_THIS_DOCUMENT`

本计划不授权创建conditioner、改变Formal几何、运行样机或公开IP。每个工作包必须另有获批机器合同、
冻结输入和run身份。

## 1. Gate A：IP与科学差异

### 动作

- conditioner、RF/DC序列、自动匹配和波形补偿的patentability/FTO；
- 明确可公开、先专利和trade-secret内容；
- 完成与Paper 1的中心假设、方法、数据、图和结论overlap audit。

### 关闭条件

- 可公开范围书面冻结；
- Paper 2不依赖重复Paper 1主claim；
- 主要新方法和主要新数据可以独立说明。

## 2. Gate B：conditioner原理与可实现性

### 动作

- 建立真实三维时变conditioner模型；
- 检查辛相空间交换、非线性、RF phase kick、横向耦合和孔径；
- 输出detector-blind `p_out`，比较条件均值、协方差、尾部和传输；
- 证明不是只通过裁束或损失降低峰宽。

### 关闭条件

- 至少一种结构在真实场和工程边界内改变Paper 1识别的主导残差；
- 输入/输出母cohort与损失完整闭合；
- 结果不依赖把相空间匹配误写成冷却。

## 3. Gate C：联合稳健模拟

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

## 4. Gate D：波形、as-built与样机A/B

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

## 5. Gate E：真实分析终点

### 动作

- 在查看最终数据前冻结样品、终点、统计模型和成功阈值；
- 使用独立new dataset比较baseline/new；
- 建立离子光学改善到分析结果的因果链和替代解释检查。

### 关闭条件

- 至少一个预定义endpoint具有统计和实际意义；
- 改善在重复、日间稳定性和合理负载范围内存在；
- 分析结论不是由不同采集时间、样品批次或数据处理制造。

## 6. Gate F：AC投稿

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

## 7. 数据隔离

- Paper 1的locked source和主要峰图不作为Paper 2主要数据；
- Paper 2使用新的最终conditioner locked simulation、prototype和sample dataset；
- 已发表的focusability、pulser或数字孪生方法只引用；
- 所有共享装置、代码、数据来源和相关稿件在cover letter中主动披露。

## 8. 当前状态

Gate A–E均未关闭。当前只允许开展先行工作/IP评估和Paper 1证据闭环；本计划本身不授权启动昂贵模拟、
硬件采购、样机制造或外部披露。
