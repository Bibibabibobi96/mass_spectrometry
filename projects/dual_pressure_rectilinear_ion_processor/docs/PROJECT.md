# 双压力区矩形射频离子处理器项目状态

## 当前目标与边界

以贴近公开文献的简化实体电极，复现多极引导、HP捕获冷却、LP输运聚集、整体抬升、RF淬灭和正交引出。
当前几何已修订；旧几何的探索结果不能验证当前几何。COMSOL、完整机械CAD和实际仪器性能尚未建立。
旧解析规定场仅作参考，不是生产电场。

## 科学权威与尺寸来源

[baseline](../config/baseline.json)拥有几何、气体、RF与时序；
[native operating point](../config/native_operating_point.json)是原生电极电压唯一权威；
[numerics](../config/numerics.json)拥有离散；[geometry sources](../config/geometry_sources.json)区分文献报告、解释与项目假设，
仅作来源映射，不成为第二份求解输入。

文献依据为Stewart等的[装置论文](https://pubs.acs.org/doi/10.1021/jasms.3c00311)，重点是Figure 2/3及相邻正文。
HP/LP长度100/80 mm、r0=2 mm、8×0.8 mm狭缝提供几何约束。
入口“2 mm钢孔”解释为圆孔直径2 mm（半径1 mm），不能误作2 mm半径或阱内切半径。
LP outer相对内表面间隙在中心为4 mm、端部3.7 mm，即半间隙2/1.85 mm；厚度向离子体积外增长，
修复了把间隙误当板中心距、有限板厚向内侵入的偏差。内辅助DC轴向长度投影为2.5 mm。

当前原生网格0.1 mm，HP/LP辅助结构各以60段中点阶梯近似；阶梯是连续电极形状的数值表达，
不宣称设备存在60段独立电极。平板宽厚、LP中心x=170 mm、引导段尺寸、3/3.5 mm浮动屏蔽半宽、
透镜尺寸和末端透镜50 V均为项目假设或工作种子，不称文献或厂家CAD。
所有场域、电极编号、实体、孔、PA原点由同一native projection派生；15个可调电极包含HP/LP浮动屏蔽，
分别追随对应common-mode。当前几何变更必须重新Refine，旧0.2 mm场族不能直接消费。

## 时序、源与碰撞

原生PA、native projection及source.json保留局部坐标：local x沿guide→HP→LP，local y引出、local z另一径向。
`config/coordinate_transform.json`消费公共刚体合同：world=(-local z, local x, 9.8-local y) mm；
向量只旋转，时间不变。世界x为横向，+y为慢漂移，−z为引出；frame_id为
`ion_processor.xyz.reflection_z.drift_y.transverse_x.local.v2`。这是与MRTOF方向兼容的器件局部frame，
装配port Y尚未注册，不能冒认MRTOF全局frame。同一母群的ID、完整位置速度与绝对时钟连续保持。
canonical快轴为world z；半径和散角相对world z。原生接受域、气体分区与占据仍逆变换到local计算，
`max_rod_radius_mm`是原生接受参数，不是世界原点圆柱门；压缩指标新增`slow_sigma_y_mm`。
旧冻结运行无coordinate_transform时保留原canonical映射。
捕获HP−5 V、LP0 V；当前HP输运偏置2 V。LP整体lift至4 kV，主push/pull及侧电极引出相对电压均为±900 V。
这些是功能工作点，尚未优化。整体抬升不直接增加封闭均匀势阱内动能；出阱电势落差负责主要能量增益。

`schedule.extraction_start_us=5500`表示LP RF淬灭起点；真正引出脉冲在0.5 RF周期后，
3.7 MHz下为5500.135135… μs。图中quench_start+0.1 μs仍在淬灭等待区，不能称脉冲后0.1 μs。
局部测量面local y=9.8 mm（world z=0）仍是靠近local y=10 mm数值地边界的观察面，不是实际分析器；当前0.1 mm网格下两者相距两个网格。
旧y=8 mm只作probe，不能混作最终测量面。

正式source默认524 amu、+1、5 eV、N=100，采用公共Halton薄圆柱入射片；版本化N=10仅供探索。
N2温度/压力和截面为冻结模型输入；2.27e-18 m²截面来自官方HS1示例，未经N2/524 amu标定。
无碎裂、化学反应、气流求解、空间电荷或离子间碰撞。

## 当前证据及资格

旧几何r06：`20261015_155100__sim__simion__ion-processor-exploration-r06`的真实N=10为
`exploration_pass`，捕获10/10、引出9/10、引出子群平均能量3945.525 eV、引出前轴向σx=0.637889 mm。
这些是legacy探索，`functional_baseline_eligible=false`；不是当前0.1 mm/60阶梯、入口与LP gap修订几何的验证，
也不是N=100功能、数值收敛、GUI一致性或实际商业装置性能结论。
早期0.2 mm场族15组响应Refine用时15.47 s，只证明当时场身份已求解，不覆盖新几何。

修订几何r07真实N=10保留负结果：捕获10/10、引出8/10，引出子群平均3927.873 eV，
全母群引出前guide慢轴σ=15.234 mm，未达聚集目标；不能用仅LP条件子群展宽替换全体分母。
旧r07 GUI重复Fly改写了源PA0，旧一致性结论无效，不作PASS。
已从原SHA验证的PA#重新Refine，恢复PA0精确SHA：
`8E68A310E56AEB5603E72973526E8DC9B3F8E40CCF5CFFAAB31DD1BC19ED5A99`。
恢复后的r10已完整结束，真实native Fly在新世界坐标下取得`exploration_pass`：
N=10、捕获10/10、引出9/10、捕获平均动能0.03840967267 eV；引出前9粒子均位于LP，
慢轴σy=0.331102781675 mm，平均出口能量3927.990922904 eV。
损失ID1在t=4178.520896 μs、world=(1.3965569,169.0133388,9.8188436) mm记录`solver_stop`，
具体电极unknown，不能从该终止原因推断金属碰撞位置。这不是N=100正式baseline或Candidate。
r10真实vendor pose验收已通过：
local ex→(0,1,0)、ey→(0,0,−1)、ez→(−1,0,0)，PA原点映射(4,−1,13.8) mm，grid=0.1 mm；
此项仅证明坐标姿态投影，不代表粒子动力学验收。

探索仅发布`exploration_pass/incomplete`；完整N=100才可评价功能目标，仍须区分功能、数值收敛和GUI/CAD资格。
当前[验收合同](../config/acceptance.json)保留捕获/引出率、冷却、位置聚集和出口能量目标；不通过更改阈值制造通过。
全过程诊断和原生场诊断代码存在不代表这些目标已经满足。

## 诊断与复现

[diagnostics配置](../config/diagnostics.json)冻结快照时刻与插值限制，输出几何轨迹、分时离子云、
阶段快轴/横向及慢轴相空间、KE(t)/慢轴位置(t)/σslow(t)、全母群alive/extracted/lost/notborn/unknown闭合和带ID损失CSV。
图形注明电极编号/功能、源哈希、frame、真实bracket及选择；丢失后最后位置另层展示，缺记录为unknown。
`radial_escape`是程序按局部操作接受域|local y|、|local z|≤boundary_radius_mm=2 mm的终止，不是已识别的金属碰撞；
`solver_stop`同样不能反推电极ID，损失表保留unknown。r07已冻结此口径，本轮不暗改比较分母或终止规则。
原生场诊断按冻结电压时序查询PA的电势/电场；旧r05的y=8/9.8/10电势审计只约束旧几何和时刻。

GUI重放精确复制基准runtime、HS1、波形、source与配置，原生PA族（含pa-surf）完整clone为独立18文件，不共享可写场。
builder不再调用Fast Adjust，实际Fly由动态回调驱动；源PA族全部SHA在构建前后复核。
默认一次Fly；验证模式可在同一IOB连续两次Fly，逐次完整事件与已记录samples对比。
headless对比不能冒充手动GUI视觉通过。当前独立GUI准备checkpoint为
`20261015_181000__test__simion__ion-processor-gui-ready__r10`：完整clone 18文件，source/runtime精确一致，
真实IOB姿态构建已通过，未Fly。GUI由用户打开、Fly并确认，本轮只准备文件，不自行追加GUI或repeat。
旧r07无效repeat证据不复用。

## 开放动作

1. 按现有N=10证据规划N=100正式功能评价及空间/时间离散敏感性，探索不能升级为正式baseline。
2. 保留全部母群、LP条件子群和损失诊断，不能用条件子群替换全体分母。
3. GUI准备已完成；打开工作台、Fly和视觉确认由用户进行，不自行追加GUI或重复Fly。
4. 上游实际多极杆端口与MRTOF全局装配port尚未建立；独立integration及COMSOL后续按同源配置实施。

当前全过程图角色为`trajectory_geometry`、`timed_clouds`、`extraction_local_clouds`、
`stage_phase_space`、`cooling_stage_energy`、`population_evolution`。
原生场的局部采样保持原输入身份，另写`native_field_samples_project.csv`展示项目位置与旋转后的电场向量。
