# 旧原生运行、随机重放与源身份边界

DOC_STATUS: ARCHIVED_READ_ONLY

冻结日期：2026-10-16。返回[项目入口](../../README.md)。

本快照归档旧探索、原始负结果、raw 场借用/clone 与被取代的 GUI 方案；它不是活动运行日志或当前 PASS。
后续工作从冻结 GEM 新建私有场。旧源身份问题未被本快照宣布修复；新阶段另立证据，不回写本文或原始运行。
运行身份以完整 run ID 为准，表内 r04/r17 等只是已列身份的简称。
原始证据位于仓库同级 `artifacts/projects/dual_pressure_rectilinear_ion_processor/runs/`，不复制日志或 PA 到 history。

## 几何修订与早期探索

原研究依据 Stewart 等 2023 装置论文 Figure 2/3：HP/LP 长度100/80 mm、r0=2 mm、8×0.8 mm狭缝；
HP 辅助楔形对角间距4→7 mm对应径向2→3.5 mm，有文献依据，不能再称无依据尺寸。
入口“2 mm钢孔”采用直径2 mm圆孔这一模型解释，独立于末端4.4 mm方孔假设。
LP 外板间隙是离子侧内表面间距，中心4 mm、端部3.7 mm；有限厚度必须向外长。
将其误当板中心距的旧投影曾侵入离子体积。本模型内辅助板轴向全长2.5 mm，不能误记成半长。
后续改用0.1 mm网格、辅助结构60段中点阶梯；早期0.2 mm族及不同间隙几何不验证修订模型。
平板宽厚、浮动屏蔽、LP中心位置和透镜/内辅助板细节仍为项目假设，未取得厂家CAD。

| 完整运行身份 | 原始记录及限制 |
|---|---|
| `20261015_153000__sim__simion__ion-processor-functional-r04` | 引出测量面 local y=8 mm时存在残余电势；早期部分粒子约3.3 keV不能直接与到地电势的4 keV预期混同。部分终态不构成N100统计；保留failed。 |
| `20261015_152400__sim__simion__ion-processor-exploration-r05` | 旧几何N10探索及y=8/9.8/10 mm电位审计；保留exploration_incomplete，不能跨几何复用。 |
| `20261015_155100__sim__simion__ion-processor-exploration-r06` | 旧几何N10记录exploration_pass：捕获10/10、引出9/10、引出均能3945.525 eV、引出前轴向σ=0.637889 mm。不是当前几何、N100功能、GUI或Formal资格。 |
| `20261015_170000__sim__simion__ion-processor-literature-geometry__r07` | 修订几何N10负结果：捕获10/10、引出8/10、引出均能3927.873 eV、全母群引出前慢轴σ=15.234 mm，未达聚集目标。不能用LP条件子群替换全体分母。 |
| `20261015_180000__sim__simion__ion-processor-mrtof-frame__r10` | N10原始summary记exploration_pass：捕获10/10、引出9/10、捕获均能0.03840967267 eV、引出前9粒子位于LP、σy=0.331102781675 mm、出口均能3927.990922904 eV。旧HS1赋值及源身份边界使其不能升级成已验证N2/N100证据。 |

早期15组响应Refine耗时15.47 s只描述当时场求解，不能代表当前修订几何或未来运行耗时。
测量面后来采用 local y=9.8 mm（world z=0），靠近local y=10 mm数值地边界，仍不是真实质量分析器。
这是一项有物理原因的观察面变更，不是降低能量阈值；旧y=8 mm数据不能混作新测量面数据。

## 原始ID1终止事实

r10的ID1在 `t=4178.520896471 μs` 记录 `solver_stop`，
world位置约 `(1.396556922,169.013338753,9.818843578) mm`，
local位置 `(169.013338753,-0.018843578,-1.396556922) mm`，local法向速度约−1.59526 mm/μs。
E11负侧内辅助板为local x=168.75…171.25、y=±0.15、z=−1.6…−1.4 mm。
终点距解析真空侧面约3.443 μm，小于100 μm的PA网格；即使最近PA#网格标记为E11，也只支持E11邻近终止，
不能无条件称精确击中实体。原始solver_stop记录不回写为已确认碰撞电极。

该时刻早于5500 μs RF淬灭和5500.135135… μs引出脉冲，但位于4000…5500 μs整体lift期间。
因此可排除抽取脉冲已经触发，不能排除lift梯度、先前碰撞与简化内板接受度贡献。
局部近板步长续飞即使得到相同邻域终止，也不证明全程轨迹重放、完整碰撞状态继承或空间网格收敛。

r10的vendor pose查询支持 local ex→(0,1,0)、ey→(0,0,−1)、ez→(−1,0,0)，
PA原点映射(4,−1,13.8) mm及0.1 mm网格单位。它只验证坐标映射，不验证粒子动力学。

## HS1作用域与旧N100结果

普通Lua赋值不能证明导入HS1内部adjustable采用配置值。独立原生探针
`20261015_203456__test__simion__hs1-adjustable-scope-zero-step` 实际getter显示：普通赋值后仍4 amu/273 K，
显式adjustable赋值为28 amu/300 K。其wrapper误判CSV应有三行，而顶层程序执行两次得到四行；原run保持failed。
后续纯分析 `20261015_205106__analysis__python__hs1-scope-native-readback` 校验原始CSV并完成分析。
该机制证据不等于直接观察历史r10/r13内部值恰为4/273；旧气体参数未验证这一限制必须保留。

| 完整运行身份 | 历史统计与适用边界 |
|---|---|
| `20261015_183000__sim__simion__ion-processor-n100-loss-diagnosis__r11` | 引擎报告100次终止，但后处理缺冻结政策JSON、ID29出PA后未记录程序终态，仅99终态；保持failed，不补造第100条。 |
| `20261015_200000__sim__simion__ion-processor-n100-recorded-exits__r13` | 100源/100终态；捕获100、引出82、16 solver_stop、2 timeout，functional_incomplete。旧HS1赋值未验证。全母群引出前存活95粒子σy=7.368854 mm，与LP条件93粒子σy=0.664393 mm不能混换。 |
| `20261015_210000__sim__simion__ion-processor-n100-hs1-bound__r17` | 内部HS1回读为28 amu、300 K、sigma=2.27e−18 m²、MFP=-1、steps=20、初始化seed参数43、mark=0、trace=0，压力由回调提供。原summary报告捕获100、引出82、15 solver_stop、3 timeout；引出前100存活、σy=8.677685 mm、出口均能3923.379153 eV，functional_incomplete。**只作为HS1内部参数回读参考，不能称源场完全验证的N2物理基线。** |

在PA内、末透镜之后增设local x=211.25 mm数值出口，是为出域前记录精确终态；不是金属电极，也不补造旧r11终点。
`20261015_190000__test__simion__ion-processor-id1-loss-probe__r12`、
`20261015_203000__test__simion__ion-processor-id1-loss-probe__r14`和
`20261015_204000__test__simion__ion-processor-id1-loss-probe__r15`保留各自失败状态；
初始化、manifest结构或PA路径接口错误不能当作物理负结果。

## 两次精确分区重放与可选RNG调查

| 完整运行身份 | 实际结果 |
|---|---|
| `20261015_214258__test__simion__ion-processor-native-partition` | 公共调度实际启动3个worker，A4对B1+B3，共8次积分、4个唯一ID。进程自然exit0、源guard记录未变，但事件/样本不同；保持failed/partition_difference。 |
| `20261015_215345__test__simion__ion-processor-native-partition` | 将HS1重置与赋seed移到实际积分激活后仍分叉；三worker自然结束，事件均28行但数值不同。激活/seed行序正确，4个ID首次记录差异均在约22.14 μs的HP气体入口后。保持failed/partition_difference。 |

SIMION先创建全部离子并调用initialize，然后才逐粒子积分；创建回调的seed表不能单独证明积分随机流。
后续runtime使用实际积分激活重置，但精确重放仍未验证。种子记录只能证明赋种政策，不证明真实随机序列相同或子流独立。
用户明确接受随机碰撞实现不同；上述额外精确重放检验不是物理模型或允许并发的失败判据。
统计复现应另比较捕获/引出比例和位置/能量分布；本阶段没有独立ensemble重复或统计等价检验。

可选短RNG调用仪表 `20261015_222423__test__simion__ion-processor-native-rng-calls` 在准备阶段失败，未商业积分；
`20261015_222840__test__simion__ion-processor-native-rng-calls`在初始化日志中访问受限位置量，0 splats退出。
两者保留failed；未取得有效RNG序列实证。这项可选调查已停止，不再作为N100阻断动作。

## 源身份、恢复尝试与旧GUI

旧r07 GUI重复Fly曾改变被借用的源PA0，旧一致性结论无效。
恢复运行 `20261015_174000__build__simion__ion-processor-pa0-recovery__r09` 从原SHA绑定的PA#重新Refine，
当时PA0重建与复制的目标SHA为
`8E68A310E56AEB5603E72973526E8DC9B3F8E40CCF5CFFAAB31DD1BC19ED5A99`。
这是一项历史重建记录，**不能据此追认后续完整源族身份已恢复**。

随后发现普通读取、无缓冲guard及历史manifest之间的身份差异：r17的PA8输入记录为
`6D90B2B25CEE4DA845C10B21A86B0D2B305C28869CAAE2D29962164F7B1443E9`，
原r07 manifest与guard为 `B1E52681975859E5359A24B0F137400D6287C2ACE987BA803B9059334B1F2664`。
后续读取曾匹配旧记录，但一次匹配不证明历史恢复、飞行时所见内容或硬件持久性。
旧文件未因这项调查获得新的源可信资格；同样不能仅凭读取差异无条件定性为永久损坏。

旧GUI准备包 `20261015_181000__test__simion__ion-processor-gui-ready__r10`曾完整clone 18个PA文件，
原checkpoint记gui_fly_completed=false，未取得手动GUI验收，且只承载N10母群。
随后单次公共身份检查中，其本地PA#原记录
`DA792A1AED0C3C0B424992212A187D8ED0C49129513DB4414FE89506A6C4CBFA`，普通读取为
`66E0AA355CB7F482B2EAC9837D7366574736049D3E76F454E951E89C6D23680C`，大小相同。
这些未决差异不能被新manifest静默重封。旧clone包不等于新的N100 GUI交付，不再作为当前准备完成的依据。

新方案退出旧raw族借用/clone：CLI和未来GUI各自从同一冻结GEM建立私有原生场；
fresh producer关闭后做可写文件落盘再建立身份，不对旧immutable文件flush来宣称恢复。
这一方案变更本身不提供新N100统计、GUI视觉通过或Formal资格。

## 失败与载荷处置仍分开记录

首次“r20”启动申请被TARGET_CAPACITY_EXCEEDED挡在run分配之前，没有对应新run/Fly，不属于N100物理失败。
r11已沿公共owner退役收据删除可重建稠密轨迹 `simion/trjd995.tmp`，3,526,380,000 B；
必要CSV、原始failed三件套和退役收据保留。原manifest描述退役前库存，不应再交普通完整manifest验证器冒称当前磁盘完整，
退役后的历史追溯应使用[公共退役收据](../../../../../artifacts/projects/dual_pressure_rectilinear_ion_processor/runs/20261015_183000__sim__simion__ion-processor-n100-loss-diagnosis__r11/solver_review_retirement_receipt.json)及其专用验证语义。
剩余证据超轻量预算引发的容量收尾问题不等于物理失败，不授权重复删除或降低保留/验收标准。

本文仅冻结被取代阶段的事实与限制；当前运行和未完成动作统一见[项目状态](../PROJECT.md)。
