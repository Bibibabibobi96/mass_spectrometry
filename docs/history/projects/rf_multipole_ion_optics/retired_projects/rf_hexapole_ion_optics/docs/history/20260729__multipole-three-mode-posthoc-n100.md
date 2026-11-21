# 多极杆三模式 N=100 事后描述报告

> DOC_STATUS: ARCHIVED_READ_ONLY
>
> Historical snapshot: statements are interpreted at the document date; current authority is the applicable active contract and current project/integration documentation.

## 声明边界

本报告只读消费2026-07-28至2026-07-29已经完成的四、六、八极杆COMSOL/SIMION baseline run。
分析计划和bootstrap参数没有在这些run之前完整预注册，因此机器结果固定为
`POSTHOC_DESCRIPTIVE`：

- 不计算bootstrap或其他不确定度区间；
- 不应用事后选择的验收阈值；
- 不判定连续量收敛、跨求解器数值等价、最优条件、Candidate或Formal；
- 不替代各项目N=100功能资格记录和资源受限结论。

公共发布器复核三个模式使用相同机械签名、粒子源和solver numerics，并把每个真实run的handoff事件
转换为canonical component particle-state。三个模式均为100/100传输；下表因此没有幸存者集合变化
造成的样本选择差异。

## 统一点估计

`+50 mm RMS半径`是在规范交接面状态上按`vz>0`作50 mm无场弹道投影后的总体RMS束斑，单位mm。

| 项目 | 求解器 | 无加速 | 分段杆加速 | 出口带孔接口板加速 |
|---|---|---:|---:|---:|
| 四极杆 | SIMION | 7.596 | 4.759 | 5.223 |
| 四极杆 | COMSOL | 8.083 | 4.864 | 5.682 |
| 六极杆 | SIMION | 3.670 | 2.627 | 2.570 |
| 六极杆 | COMSOL | 4.926 | 2.896 | 3.399 |
| 八极杆 | SIMION | 3.249 | 2.110 | 2.490 |
| 八极杆 | COMSOL | 3.796 | 2.142 | 2.703 |

规范交接面RMS角发散点估计，单位mrad：

| 项目 | 求解器 | 无加速 | 分段杆加速 | 出口带孔接口板加速 |
|---|---|---:|---:|---:|
| 四极杆 | SIMION | 145.889 | 92.898 | 100.958 |
| 四极杆 | COMSOL | 154.239 | 94.912 | 109.620 |
| 六极杆 | SIMION | 71.096 | 50.394 | 50.607 |
| 六极杆 | COMSOL | 94.917 | 54.808 | 65.836 |
| 八极杆 | SIMION | 62.344 | 37.508 | 51.358 |
| 八极杆 | COMSOL | 72.818 | 41.314 | 55.145 |

为了显示求解器间诊断差异，下面仅计算透明的对称相对差
`2*|COMSOL-SIMION|/(|COMSOL|+|SIMION|)`；它不是验收统计量或PASS阈值。

| 项目 | 无加速 +50 mm RMS半径 | 分段杆加速 | 出口带孔接口板加速 |
|---|---:|---:|---:|
| 四极杆 | 6.21% | 2.19% | 8.42% |
| 六极杆 | 29.21% | 9.73% | 27.77% |
| 八极杆 | 15.54% | 1.48% | 8.21% |

## 可支持与不可支持的判断

两求解器都显示：在当前`0/-1/-2/-3 V`分段杆方案或`-3 V`出口带孔接口板方案下，三种多极杆
50 mm漂移后的RMS束斑均小于无加速模式。分段杆方案在四极杆和八极杆中给出两求解器一致的三模式
最小值；六极杆的两个加速方案相近，且两个求解器对二者排序不同。

因此现有结果可以作为下一轮实验设计的方向性筛选：优先研究分段杆加速，并把六极杆两方案保留为
并列候选。它不能说明当前电压、分段数、段长或板间隙已经最优，也不能证明改善会在真实下游器件、
碰撞冷却、空间电荷、机械公差或不同离子工况下保持。尤其六极杆无加速和出口板模式的求解器间点差
仍大，不应据此做精细排序。

下一轮若要得到“优化条件”，须在运行前冻结真实下游接受度、minimum relevant effect、参数扫描范围、
误差预算、bootstrap设置和工程停止条件，再运行对应的新数据；不得从本事后报告反推阈值。

## 机器结果身份

六份compact分析run均位于各自当前artifact根的`runs/`：

| 项目 | SIMION | COMSOL |
|---|---|---|
| 四极杆 | `20260729_100446__analysis__python__three-mode-posthoc__simion-n100` | `20260729_100446__analysis__python__three-mode-posthoc__comsol-n100` |
| 六极杆 | `20260729_100446__analysis__python__three-mode-posthoc__simion-n100` | `20260729_100446__analysis__python__three-mode-posthoc__comsol-n100` |
| 八极杆 | `20260729_100446__analysis__python__three-mode-posthoc__simion-n100` | `20260729_100446__analysis__python__three-mode-posthoc__comsol-n100` |

每个run包含`run_config.json`、`summary.json`、`run_manifest.json`、三份canonical handoff CSV、
posthoc binding和完整JSON分析结果；manifest终态均为`success`。运行只使用Python读取既有产物，
没有启动COMSOL、SIMION或修改源solver run。
