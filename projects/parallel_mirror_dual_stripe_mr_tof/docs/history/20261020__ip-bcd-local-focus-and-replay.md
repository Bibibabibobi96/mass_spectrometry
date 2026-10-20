# Ion Processor B/C/D局部聚焦、孔口及默认回放里程碑

DOC_STATUS: ARCHIVED_READ_ONLY

冻结日期：2026-10-20。本页保存已完成B/C/D局部研究及其保留、失败与数值边界；后续D三路线改进另由当前PROJECT和独立run记录，不回写本页。

## 已完成研究与交付边界

B／C／D轮廓的理论、局部带场飞行、焦点与接受度对照及独立默认回放已完成；以下明确结论与数值边界。
本轮主要目标为降低x／y角分散并尽可能实现空间聚焦，同时报告时间宽度、能散和收集率的取舍。
仅使用局部IP出口、屏蔽及第一Prism场，不进入镜组或大型联合飞行；未操作GUI，不覆盖用户验收包。
必要时可修改IP几何或增加透镜，但须先有理论预测，再有受控实算支持；上述双透镜已有局部实算及单轴网格对照，仍不授完整数值收敛资格。

完整证据、英文图及七项要求对应关系汇总于[本轮综合报告](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_192806__analysis__python__ip-p1-goal7-synthesis/results/scientific_report.md)。
每设计100母群、96实测出口和4个上游损失全部保留，使用原始ID、六维状态及绝对时钟；没有重采样或缩放速度。
原生来源171512九组Fly全部完成，仅自动诊断失败，原failed身份保留；
[独立记录分析](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_173804__analysis__python__ip-bcd-recorded-focus/results/local_focus_diagnostics/metadata.json)
核验完整原生阶段并输出全部逐母、逐面及相空间结果，不将后处理失败算作离子损失。

| 设计 | 源面σθx／σθy（°） | 完整96群最小σt（ns） | 时焦采样z（mm） | 到P1出口／100母群 |
|---|---|---:|---:|---:|
| B formed | 0.79627／0.17477 | 3.28785 | −22.5 | 83 |
| C continuous aux | 0.81807／0.21326 | 4.12354 | −11.0 | 79 |
| D parabolic inner | 0.64439／0.23986 | 4.60015 | −4.5 | 92 |

源面角宽取全局z=−0.5mm完整96群的人口SD；P1透过率相对96输入为86.458%／82.292%／95.833%。
D相对B的源面x角宽小约19%，收集率较高，但y角宽和最小时宽较大；没有两轴、时间和收集率同时占优的设计。
[空间／时间最小值](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_184918__analysis__python__ip-fine-sampled-minima/results/report.md)
中三设计σx最小均在首面−0.5mm，约0.04382／0.04845／0.04787mm，不能定位内部下游x束腰。
y束宽最小分别在−34／−54／−13mm，σy约0.26616／0.26514／0.29595mm，与时间焦点不同。
0.5mm采样间距不是焦点位置精度；中央68%／90%宽度、参考法向统计及边界标记完整保留。
[全程同时刻束团](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_181638__analysis__python__ip-fine-transport-snapshots/results/report.md)
覆盖三设计至Prism后约z=−97.5mm，2100条母群—时刻状态闭合；绝对及居中XZ／YZ图均为默认自动输出。
居中图保留同active ID和显示均值，终止后不外推；不同幸存群变窄不能称为冷却或聚焦。

[文献逐电极复核](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_052431__analysis__python__ip-bcd-local-validation-plan/results/literature_geometry_review.md)
分别标注文献报告、图示支持和模型假设。LP61.5mm、精确抽气窗、唇边／倒角及D抛物线边缘不作为厂家尺寸或轮廓。
“近似二次DC势阱”约束实际离子占据区的曲率、对称性和非谐项，不能唯一反演金属形状。
[理论先行计划](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_164316__analysis__python__ip-bcd-theory-validation-plan/results/report.md)
保留全部来源和时钟、自由漂移束腰与可证伪预测；[理想透镜预筛](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_165411__analysis__python__ip-ideal-lens-screen/results/report.md)
显示z=−20mm的独立x／y准直强度不能由同面单圆透镜或固定单四极同时实现，柱面x透镜仅为待验证候选。
理想强度不是实际电压；发射度、有限幅度像差、色差和时间—能量相关性不能省略，当前不验证空间电荷。
[P1／屏蔽耦合场的实算响应](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_173418__analysis__python__ip-born-native-pair/results/report.md)
在z=−50mm保持C／D完整96颗，实际x斜率SD较源增加30.682%／30.466%，一阶预测误差小于0.83%。
这支持耦合总场作用，不是独立Prism电极的因果比例；进入强偏转区不能以恒速探针代替轨迹。

[无孔网格／步长和损失复核](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_172931__analysis__python__ip-local-loss-mesh-review/results/report.md)
中B／C／D粗细及半步损失ID相同；同ID出口最大差不超过0.01203ns、0.857μm和0.03640mrad。
实际节点与连续CSG截面随求场自动导出；D67碰撞位置仍约0.15mm敏感，不授予普遍连续边界收敛。
上游出口来源仍为0.1mm网格的完整IP运行；局部加密不重新验证捕获／冷却／提取，不能称全IP收敛。

理论筛选后仅执行C的无孔／圆孔／有限y狭缝三项实体对照，不无条件扩成完整12工况。
孔板中心(0,−55,−20)mm、厚0.4mm、接地；圆孔半径0.3mm，狭缝x／y半宽1.5／0.3mm。
[实体／虚拟固定ID比较](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_183500__analysis__python__c-physical-vs-virtual-aperture/results/report.md)
到P1分别为无孔79、实体圆孔51、实体狭缝67；相同位置虚拟选择传到P1为42／61。
实体额外通过的9／6颗仍在连续孔外，同ID轨迹差接近数值噪声；群宽下降主要为筛选，不是已证明的聚焦改善。
[零场隔离](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_185917__test__simion__zero-field-aperture-collision/results/report.md)
复现该异常，粗档半步不改变通过集合；[0.02／0.01mm探针](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_191045__test__simion__zero-field-aperture-fine-collision/results/report.md)
两档圆孔均45／96，而连续几何为42，额外ID15／72／91进入名义金属约4–5μm；狭缝两档均72且逐ID一致。
计数平台不是连续碰撞正确或收敛；不将额外通过称物理收集率改善，不向项目最小0.01mm以下加密。
两次约84分钟的全域细场Refine不具当前判别价值，未执行；纯Lua首接触预检也未冒充集成原生结果。
[探针载荷退役](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_193811__analysis__python__fine-collision-payload-retirement/results/report.md)
仅移除四个可重建零势PA及两个真实surface，释放2,968,967,720B；原success身份、全部小证据和重建输入保留。
这不是用户交付PA；若重放该探针旧IOB须先重建其零势场。

已结束的182357粗网格C孔板对照又经[公共退役审计](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_214921__analysis__python__c-coarse-payload-retirement/results/report.md)
移除其三case的6个可重建PA／surface，共2,262,495,004B；容量账本扣除保留处置收据后净释放2,262,026,092B。
全部原始小证据与重建输入、原success身份及下述183935细网格用户包保留；182357旧IOB需重建场后才能再Fly。

后续[重复B／C细场公共退役](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_223802__analysis__python__bc-fine-duplicate-retirement/results/report.md)
仅移除171512的B_h005／C_h005两份PA及surface，释放11,971,591,048B；账本计入处置收据后净减11,970,927,213B。
其全部九组轨迹、小证据、输入与原failed身份保留，D粗／细及B／C粗场保留；183935独立B／C／D用户细场完全保留。
171512的B／C细档及对应半步IOB重放前须重新物化已退役场，不影响当前D场复用。

[独立可加载包](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_183935__build__simion__ip-bcd-private-local-replay/summary.json)
保留B／C／D三套细场、独立IOB及frontend=0的轨迹显示配置。
[独立默认回放汇总](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_194300__test__python__bcd-default-replay-summary/summary.json)
对应三次全新进程，无Program／Q／粒子覆盖，各96实际源／100母群；events和samples逐记录逐字段零差异且字节一致。
来源及私有控制／PA身份保持，所有损失保留；这验证默认文件回放，不冒充GUI人工验收。
手动Fly会写events／samples，须将所选case完整复制到独立可写目录再打开local.iob，不能在封存来源原位飞行。
前期准备／包装器失败均保留原状态和诊断，不计为离子损失；未放宽公共容量或身份判据以制造成功。

[干净HEAD主题闭包](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_193645__test__python__clean-head-local-ip-bcd-closure/results/report.md)
仅叠加31主题文件，14模块179项测试、0失败／0错误／1历史产物缺失跳过，导入无工作区泄漏。
原生数值／轨迹资格由各具名运行分别证明；最终L1和精确提交代码度量由独立最终校验记录给出。
