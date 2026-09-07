# 开放路径平行镜双条带 MR-TOF 项目状态

## 项目定位

本项目面向开放路径多次往返飞行拓扑：离子在一组名义平行的伸长等时镜之间沿反射轴快速往返，同时
沿漂移轴缓慢展开、转折并返回注入端。两套独立偏压、独立形状的漂移条带电极组共同提供两个能量响应
基，用于分别约束空间返回和时间平台；它们是同一分析器的耦合部件，不是两个profile。

当前只建立这条平行镜双条带硬件设计线。原 Astral 的“收敛镜 + 单形状 Stripe/Ion Foil 响应”保留为
理论对照和解析回归，不启动单 Stripe 项目，也不作为本项目mode。长期目标是建立从理论、机器可读
baseline、参数化几何、独立求解器验证到 SolidWorks CAD 和性能优化的受控闭环。本项目与单次反射
正交加速TOF质量分析器平级；只有经两个项目实际复用和验证的TOF方法才可提升到`common/`。

首棱镜现有独立的 solver-neutral L0 Candidate 合同：其物理输入明确为**总**动能
`4000 eV`，其中目标慢漂移动能为`5 eV`，故主分析器目标方向相对项目`-z`向项目`-y`
偏转`2.026133972°`。CAD 三角棱镜 ID 16 的硬边界种子在合同指定的局部角度约定下为
`+141.332940251 V`；这只是有限三维单位场/轨迹射击之前的参考静态初值。首棱镜的目标是
`z=-101 mm`接口面及 grounded-1 的CAD槽接受区，不假造单一出射`y`坐标。路径顺序固定为
ID 16 的 P1、ID 17 的 P2、随后 Stripe；P2 的 `0 V` 只是尚未解决的 pre-Stripe 注入合同的
审查电压，不能解释为 K=25 后的返回器件。因此当前不宣称双棱镜传输、探测率、TOF或分辨率。

2026-09-07 已纠正路径语义：ID 16 是离子沿路径先经过的 Prism 1，ID 17 是其后、进入
Stripe 前经过的 Prism 2；两者都不是 K=25 返回后的器件。新增 solver-neutral 的解析
硬边界种子实现，使用理论精确式
$v=w_0\cos(\alpha+\beta)\sin(\beta-\alpha)$。它要求 `source/focus → P1 → P2 → Stripe`
四个有物理名称的二维交接点，分别从三段几何射线导出入射、中间和 Stripe 入口角，再唯一计算
P1/P2 种子电压。当前冻结合同尚未声明 P1/P2 有效截面和理论 Stripe 入口点，故实现失败关闭；
不得以 P2=0、广域电压扫描或旧“after K=25”语义代替。该 L0 结果也不取代含有限三角电极、接地屏蔽
和边缘场的三维单位场/轨迹校正。

解析入口角现只按项目理论式 \(\vartheta_0=\arcsin[\kappa(1)L/(KW)]\) 由明确声明的
\(\kappa(1),L,W,K\) 计算；公开 Astral 的 `1.784°/335 mm/641 mm` 仅用于函数回归，不能写入本
Candidate 的工作点。当前 `dual_stripe_l0` 尚未给出本机 \(\kappa(1)\) 和命名的 \(L,W\)，因此
Stripe 入口相空间仍为未完成的上游 L0 输出。

镜 L0 的 `reduced_period` 已按完整两镜周期定义为 \(R\,[\mathrm{mm}/\sqrt{\mathrm V}]\)，故理论
\(W=R\sqrt{E/q}\)（本合同以 `E/q` 的 V 单位表示）可直接由解析势积分得到，质量和电荷在转换中抵消。
这仍只在同一 L0/L1 设计通过其镜门禁后才可进入 `dual_stripe_l0` receipt；不以实机端板距离替换它。

双 Stripe L0 已具备与求解器无关的两项基础算子：由 \((\psi,g)\) 到两独立响应贡献的解析
\(2\times2\) 反演，以及使用 \(\eta=1-u^2\) 的端点正则化 \(\kappa(1)\) 积分。它们只接受显式
目标函数与归一化，尚未将现有 CAD 曲线或审查电压伪装成该目标函数；项目工作点仍等待同源的镜周期 receipt、
Stripe 入口、转折点和 \(\psi/g\) 目标。

## 当前状态

2026-09-07 用户指定独立加速器 PA 使用项目 `x/y/z=0.25/0.25/0.1 mm/gu`，
取代下文历史审查包的 `2/2/2`。分析器和探测器继续使用各自的 `1/1/1` 网格。
本次只改变数值合同，不改变环厚、位置、孔径或电压；1-mm轴向环厚对应10个单元，
33.6-mm二区长度对应336个单元。新合同需重新构建加速器PA，旧PA/IOB不会自动更新；
分析器和探测器应按各自内容身份复用。resolved已增加中间栅与出口栅的实体支撑框，
厚度继承第二区环的同一字段，框中心不移动栅平面；只有孔内理想栅保留零厚度。
两个GEM生成入口消费同一resolved支撑框，出口框外缘接到罩内壁。
SIMION 2020原生检查发现普通`notin`移除精确孔壁（790样点中300失败）；提供者开框发射器
改用`notin_inside`后，同一合同与同一790样点全部通过。有效证据为
`runs/20260907_085726__test__simion__accelerator-fine-wall-correction`，已复核manifest。
原生PA为`257×257×641`节点；检查覆盖1-mm环/框厚、25-mm孔壁、孔内单层栅以及出口框接罩。
这是只读材料节点验收，不是离子原生穿越、场收敛或飞行验收。独立细网格PA家族已完成
默认Refine，PA0和9个basis齐全，构建后原始PA字节与已验证几何一致，790点复验再次通过。
当前可检查装配为`runs/20260907_090251__build__simion__mrtof-three-component-iob/`
`simion/mrtof_three_component_candidate.iob`。3张PA重载、原点/网格、28个物理电极的保存电压、
独立探测器零电势及终态manifest均通过；分析器GEM与旧审查包逐字节相同，探测器旧/新合同
生成GEM相同，因此两者直接复用原PA，没有重新Refine。此装配未执行Fly，仍仅为
`prototype_geometry_review_only`，未产生新的TOF、检测率或分辨率。

组件PA缓存身份现以合同生成的本组件canonical GEM为几何范围，并拒绝与其不一致的输入GEM；
不再因另一组件的resolved变化而无谓失效。网格、原点、数组编号、软件和构建代码身份仍受绑定。
这项修复不自动迁移旧缓存；旧PA只有在来源和完整内容复核后才能复用，不能以新构建器身份
冒充旧PA的生成来源。

2026-09-03 用户将首轮粒子改为524 Th、+1、4 kV；该物种只在
`config/simion_candidate_two_zone.json`的`particle_source.species`维护，四类Fly2由同一输入生成。
N=100仍表示小束团粒子数，不是质量。此前100 Th输入/结果保留原身份，不能更名或并入524 Th统计。
该调整不改变机械几何或静电PA；尚未形成524 Th飞行、时间聚焦或分辨率证据。

主分析器现为`x/y/z=1/1/1 mm/gu`，独立加速器当前为`2/2/2 mm/gu`，探测器为`1/1/1 mm/gu`。这是固定机械槽宽的必要条件：30-mm镜束槽的边界为`x=±15 mm`，4-mm Stripe、接地和棱镜屏蔽槽的边界为`x=±2 mm`，二者无法在同一个2-mm网格相位中同时精确表示。`x=1 mm`和`z=1 mm`均不改变连续CAD几何，而是使30/4-mm槽及CAD给定的2-mm grounded-1—镜内开槽盖板净距包含正确原生节点；此前`2/1/2`和`2/1/1`审查PA不得作为这些槽宽的GUI证据。加速器的2-mm各向同性网格只用于几何和已存电压审查；焦点、边缘场、飞行时间及分辨率必须由独立加密运行和至少三档网格收敛给出。
数值网格不改变resolved机械几何；GEM默认值和实际PA构建参数都由`component_mesh_mm_per_gu`派生。
`runs/20260903_170000__build__simion__cad-slots-review-y1z1/simion/mrtof_geometry_review.iob`已完成三PA电压重载，但其分析器`2/1/1 mm/gu`不能精确显示上述30/4-mm槽宽，因此保留为历史审查记录；新的`1/1/1`分析器装配将取代它作为几何GUI审查入口。
SIMION 2020已实际重载3个PA，并验证原点、网格、零旋转/单位缩放、19个分析器与9个加速器电极的
已保存电压节点；探测器所有节点严格零电势且有材料。主分析器20个basis中的ID19仅为零响应空编号，
没有添加物理电极。初次运行在SIMION拒绝对不存在的ID19求解时失败；r02以逐文件SHA复核复用已完成
数组，再补齐零响应与其余数组。新网格Python回归38项通过，稀疏编号的21³原生PA回归也通过。
这只是prototype几何/电压审查包，GUI人工复核待用户完成，尚未飞行，两棱镜仍0V；上游524 Th、2/2/2
准备包和初次失败包保持各自身份，不回写成新证据。

最新合同还修复了独立加速器壳对CAD grounded-2长向棱镜屏蔽的真实交叠：在固定的第一棱镜中心线
`y=55.328 mm`上，旧的`40×40 mm`电极和`48×48 mm`接地壳使壳体下缘落到`y=31.328 mm`，与
grounded-2的`y≤32 mm`实体相交。现行理论候选仅收紧外形的`y`方向至电极`36 mm`、壳`44 mm`，保留
25-mm束孔、2-mm壳内净距、所有二区长度/电压和`z=0`焦面；壳下缘现为`y=33.328 mm`，对CAD屏蔽保留
`1.328 mm`净距，并由resolved合同失败关闭。该新合同已经生成`20260903_170000__build__simion__cad-slots-review-y1z1`的三组件PA/IOB，并以`2/1/1`分析器网格、`2/2/2`独立加速器网格重载检查通过；它在2026-09-03被更严格的30/4-mm槽边界可表示性规则取代，旧r02仍不能作为无干涉装配证据。

完整双棱镜飞行的下一项阻塞是物理输入而非PA构建：CAD只约束三角棱镜与接地屏蔽的几何，并不提供
棱镜电势、入射角、出射角或脉冲时序。理论中的4-keV/\(-153\) V是公开示例，不是本仪器的电压合同，
不得硬编码。主漂移`K`状态机已经能以同向中央Poincaré截面正确计数，但必须由冻结的第一棱镜后入口
和第二棱镜前出口事件界定；在这两个接口和电压/时序被定义前，不能启动并宣称完整的524 Th、K=25、
探测率或分辨率飞行。可继续执行的范围是GUI几何/电压审查和不穿过棱镜的镜内诊断，两者均不替代整机结果。

当前优先状态（取代下列旧几何审查中仍含早期尺寸和路径的叙述）：加速器领域实现迁入独立
`orthogonal_accelerator`，MR通过`../config/accelerator_dependency.json`声明依赖，prototype materializer
把提供者API和实际源文件副本及SHA绑定到run-local输入。独立导数与等场退化测试确认旧MR二区焦距
少了因子2：现行4480/3520/0 V、6/33.6 mm输入的出口后第一焦距为`0.2583736068220337 mm`，
不再是`0.129186803411 mm`。OA原公式不变；MR的exit/grid1/repeller必须从正确公式重新派生，旧IOB
不因源码迁移取得新几何有效性。

几何修复正在验真：只读CAD复核确认中央屏蔽的十字槽应为两矩形并集而非交集、包围盒不能代替
局部外轮廓，Foil实体正端到`y=2 mm`、槽到`y=0`；Foil2短三次曲线与终端窗口也已恢复到整体减槽
表示。2-mm原生PA检查已通过两屏蔽件和Stripe端部；同轮还证实普通`notin`使镜槽之外的`x=±16 mm`
节点被错误移除，因此镜槽扣除也改为官方`notin_inside_or_on`。机械槽宽仍严格30mm，镜参数未改。
完整三组件PA/IOB现已在上述r02重建并通过无飞行重载检查；不得把下述旧IOB当作当前装配或飞行/分辨率证据。
上述原生槽检查加上独立零电压探测器检查共5项通过。此前几何审查输入为
`runs/20260903_155300__build__simion__cad-slots-review-524-th/`，已冻结524 Th四类Fly2、三份GEM、
提供者依赖及同源电压映射，尚无PA/IOB。IOB构建器已实现对两张PA0按同源映射
`fast_adjust → save`，纯Lua调用顺序回归和37项Python回归通过；真实保存后电压尚待SIMION复验。
容量门禁已放行：经用户明确授权清理两个checkpoint实验引用的可重建缓存，并逐文件复核467个SHA，
使用现有容量门禁删除24个已审计缓存目录、74,922,086,315 bytes。所有run树、输入、日志、结果和
manifest保持不动；另两个未获授权的checkpoint提供者缓存也仍受保护。清理后占用484.155 GiB，
新网格装配预登记5 GiB重型载荷预算。清理收据和授权记录保存在早期几何审查run的results中，
缓存恢复需从冻结输入重算，不是回收站恢复；没有申请容量例外或整run删除。

飞行统计审查另确认当前实现不具备完整传输证据：Lua仍在第50次任意`vz`变号主动截停；棱镜16/17
仍为0V，未实现脉冲注入/棱镜事件。Lua检测点现已改为合同指定的`+z`外表面及沿`-z`入射，并修正
第一步和中央面恰好落零的事件归属，纯Lua回归通过；实际探测终止仍须全装配飞行。旧100-splat日志分别仅记录
92或96个终态，splat后备输出也未闭合。统计层已改为从schema2的`prototype_input_manifest.json`
指定source key读取冻结的母粒子ID、Fly2和derived合同身份，精确对账并要求唯一Fly完成记录；不完整
时只保留原始诊断计数，检测率、FWHM与分辨率为null，CLI返回FAIL/1。
SIMION 2020原生N=2对照已确认`sim_segment_global=1`能覆盖PA外终止，现已启用；旧漏记录束团尚未重跑。
另有16项纯Lua周期状态机测试通过，验证第50次镜转折不等于25周期，须同向返回中央面；该模块尚待
绑定显式主漂移入口/退出，不代表完整机器K计数已闭合。以上不消除脉冲、棱镜和完整探测链的开放项。

- 生命周期：`prototype`。
- 2026-09-03 当前合同把数值探测器改为与加速器同 `x/y`站位、位于正侧接地镜内表面前的`5 mm`净距：`detector.z=[95,97] mm`，正侧接地镜内面为`z=102 mm`。它不与加速器屏蔽罩或镜接触。长的第二加速区现有五个`1 mm`厚的开框加速环，中心由`grid1 → exit`的`33.6 mm`区长等距派生为`z=28.129,22.529,16.929,11.329,5.729 mm`，电压由`3520 V → 0 V`线性派生。加速器出口首棱镜的两片接地屏蔽明确冻结为有限`y=[33,77] mm`实体和嵌套三角孔；解析器会拒绝任何`y`向贯通表示。无坐标、无求解器语法的二区环/屏蔽壳派生已移入`common/accelerator/two_zone_geometry.py`，并由 MR-TOF 与 oa-TOF 解析理论共同消费；OA 的 Formal CAD、PA、IOB、数值和电压合同均未修改。该新合同已实际编译为`runs/20260903__detector-clearance-stage2-rings-iob/simion/mrtof_detector_clearance_stage2_rings.iob`：两实例重新加载为分析器`2×2×2 mm/gu`、加速器`1×1×0.4 mm/gu`，并有新的哈希 manifest 和结构报告；它仅用于几何/电压审查，尚无飞行或性能结论。
- 2026-09-03 已生成新的、可由 SIMION 2020 GUI 加载的双实例几何/电压审查 IOB：`runs/20260903__accelerator-rear-gap-iob-complete/simion/mrtof_accelerator_rear_gap_iob_complete.iob`。分析器 PA 为`2×2×2 mm/gu`、原点`(-90,-478,-360) mm`；独立加速器 PA 为`1×1×0.4 mm/gu`、原点`(-32,23.328,-5.870813196589) mm`。读取复验确认两个实例均为预期 PA、网格和原点，且明确记录`PARTICLE_FLY_EXECUTED=false`。加速器的接地罩以`48×48 mm`外包络、`2 mm`壁、`40×40 mm`三电极、repeller 对内壁`2 mm`横向净距、后盖前`5 mm`加速间隙和与 exit grid 相接的内壁派生；这只是 Candidate 数值外形，不是已批准机械 CAD。完整 IOB 和报告由 run-local manifest 哈希绑定，尚无轨迹、时间聚焦、传输或分辨率结论。
- 2026-09-03 几何审查发现并修复三项可复现的派生错误，新的审查 run 是`runs/20260903__accelerator-placement-detector-bridge-review/`：分离加速器 PA 曾将局部`repeller → grid1 → exit`顺序与 project `+z`映射反置，令完整组件落到错误的`z≈38--80 mm`区间；现以 exit 为本地低端，IOB 原点由 exit grid 自动派生为`(-32,23.328,-5.870813196589) mm`，对应的 project 坐标重新为 exit=`0.129186803411`、grid1=`33.729186803411`、repeller=`39.729186803411 mm`。原临时`60/72 mm`电极/罩外形缩至`40/48 mm`；这只是按二维加速器接口收紧的 Candidate 数值外壳，不能声明为实机 CAD。探测器先前虽标为`+z`法向却置于入口棱镜的负`z`侧（罩内），现由同站接地罩正`z`出口边派生为`z=[-25,-23] mm`。Ion-Foil-2 中央接地导体还补发了与四 Stripe 相同的 4-mm 槽端桥：`y=[-390,-385]`和`[-6,-4] mm`。两个 PA、全 Fast-Adjust basis、IOB 及重新加载结构报告均通过；仍未飞行，且结果仅为`prototype_geometry_review_only`。
- 2026-09-03 已重新生成面向 GUI 的双 PA 几何审查 IOB：`20260903__negative-z-accelerator-prism-shield-pa-build/`。分析器 PA 为`2×2×2 mm/gu`，加速器 PA 为`1×1×0.4 mm/gu`，实际 IOB 加载复验了`(-90,-500,-360) mm`的分析器原点与`(-44,-434,31.729186803411) mm`的加速器原点。加速器 exit grid 位于`z=0.129186803411 mm`，grid1/repeller 分别为`z=33.729186803411/39.729186803411 mm`，离子从出口朝`-z`到达`z=0`一阶时间焦面。`grounded 2-1`屏蔽已按 CAD 有限包络恢复为`y=[-3,32], z=[-97,97] mm`。该 IOB 的`iob_structure_report.txt`仅证明实例、PA 和坐标装配正确；未执行飞行，不含传输、焦点、TOF 或分辨率结论，仍须 GUI 人工审查。
- 2026-09-03 的 PA GUI 审查再次否决所有现有 MR-TOF PA/IOB：其 `z=8 mm/gu` 粗网格不能保留五镜间的 5-mm 间隙或约 4--5-mm 的 Stripe/接地净距；更根本地，旧 GEM 将每片镜的 30-mm 槽错误地减成跨整个镜组的 `z` 向大盒，并把实机 `580 x 30 mm` 的有端槽误写为 `600 x 30 mm` 的 `y` 向贯通槽。A/E 端板经 STL 再审计均为 5 mm，A 为有约 `580 x 4 mm` 槽的接地板，E 为无槽、与 E 同电势的闭板。当前合同已修正槽长并要求每一片主电极各自扣除其局部槽；任何新的 PA 仍被失败关闭，直到棱镜和二区加速器完成顶层 CAD 位姿审计及 GUI 几何复核。旧 PA、IOB、飞行和统计全部仅作失败诊断。
- 当前设计选择：平行等时镜 + 两套独立漂移条带；理论模型已完成正文审阅，但尚未绑定机器baseline。
- 当前唯一实物证据：2026-07-21 接收的用户自绘 SolidWorks 工程图迁入快照。
- CAD 快照中的`ion foil`零件名和零件数量不能证明两套独立电势响应、镜平行度或活动拓扑；这些关系
  必须由SolidWorks装配审计和后续机器合同确认。
- 已建立Candidate参数/坐标合同、CAD审计证据、原型GEM/IOB/Lua入口和无求解器事件分析；正在重建统一的`resolved`参数化几何。尚无可接受的完整PA/IOB飞行链、粒子源/数值合同或性能结果。
- 不得把该快照放入 `formal/`，也不得据此声明仓库已经具备 MR-TOF 模拟或自动优化能力。

### 当前 3D SIMION Candidate 证据（2026-09-02）

**最新活动 run（取代下文仍在叙述的早期 default-refine 进度）是**
`runs/20260902__full-3d-prototype-coarse-aperture-flow/`。它由同一
baseline、run-local L0/L1 receipt 和 resolved 几何生成，使用
`2×0.8×8 mm/gu`：`x=2 mm` 在物理 4-mm Ion-Foil/内侧屏蔽通道上保留两个原生
PA 单元，`y=0.8 mm` 使两片 ideal grid 仍各占唯一原生行（583、625）。SIMION 2020
默认 refine 已实际生成 `pa#`、`pa0` 与完整 `pa1`--`pa24` Fast-Adjust 家族；单实例
IOB 以显式 project-to-workbench 平移 `(-110,-890.129186803,-480) mm` 加载 `pa0`。

该 run 的冻结首轮粒子为 `100 Th, +1, 4 keV` 的零能散/零角散小束团；4 keV 表示
新区二区加速器之后、进入分析器的名义注入态，不把尚未实现的脉冲时序伪称为已验证。中心粒子穿过
4-mm 通道并完成 22 次转折/22 次中面交接，随后在 `t=133.906921822 us` 以
`splat=-1` 撞击电极（约 `x=4, y=-263.58, z=-55.57 mm`）；这证明早先
`8×0.8×8 mm/gu` run 的零转折损失是 4-mm 通道未解析造成的体素化假象。相同 PA、IOB、
时钟和口径下的 100 粒子 run 记录为 100 个电极碰撞、0 个数值探测面命中、`K=25` 为 0；
overtone 直方图为 `K=2:92, K=3:5, K=4:2, K=6:1`，故 TOF/FWHM/质量分辨率均明确为
`null`，绝不以 aperture 截束或删尾报告改善。证据分别为 `center_event_analysis.json`、
`bundle_event_analysis.json` 和 `simion_run_manifest.json`。

因此几何--PA--IOB--Fast Adjust--中心粒子--小束团--事件分析功能链已经闭合，但该**负结果**
证明当前 Stripe/注入工作点未实现传输，更不具备焦点、25 圈、分辨率或 Formal 资格。下一轮必须在
保持同一基线与未筛选指标的条件下联合求解注入/Stripe/棱镜相空间接口；随后才做更细网格、步长、
三区和跨求解器比较。

为分离该漂移问题与镜本身的三维横向稳定性，另作了不改变几何、能量或镜电压的`stripe_biases_v=[0,0]`
中心粒子诊断。它保持`y≈-280 mm`，但仍在第24次转折（约12个往返）于`x≈4 mm,z≈-104 mm`
以`splat=-1`撞击开槽内侧屏蔽；结果写在`zero_stripe_center_event_analysis.json`。因此当前失败不能仅
归咎于 Stripe 偏压，实际开槽/端板三维镜场也必须纳入下一阶段的联合电压优化。

同一 PA family 的受控三维有限差分随后发现了一个**镜稳定性诊断点**：从 run-local L0/L1 电压表
派生`nonaccelerator_scale=0.70`、B 电极乘数`1.20`、Stripe=`[0,0]`（其余电压由基准 sidecar
自动继承）。此点的中心粒子到达50次转折；冻结 0.1-mm 半径的100粒子束团也以100/100达到`K=25`
受控末态，0个电极碰撞。目标`K`交接面的时间中位数为`356.795928764 us`，直方图 FWHM 为
`0.0002100566 us`，但它仅是**中面交接时间统计**，不称作探测器 TOF 或质量分辨率；该束团仍在
`y≈-280 mm`，数值探测面命中为0。输入变体、事件分析和哈希 manifest 分别为
`scale070_b120_bundle.variation.json`、`scale070_b120_bundle_event_analysis.json`和
`scale070_b120_bundle_simion_run_manifest.json`。该点证明三维镜电压可稳定25个往返，尚未解决
双 Stripe 返回、两棱镜双程、二区加速器脉冲、探测引出或质量分辨率。

把该镜诊断点恢复到合同 Stripe 偏压`[-40,+60] V`后，轴上粒子仍可到达`K=25`，并从
`y=-280 mm`漂移到约`-158 mm`；这验证了两套物理 Stripe 已实际进入三维场，而不是仅存在于
GEM。其100粒子重跑报告100 splats，却只有92条 Lua terminal event：45条明确达到`K=25`、47条
明确电极碰撞、8条终止原因缺失。分析器据此将`stripe_contract_bundle_event_analysis.json`标为
`candidate_not_formal__incomplete_terminal_event_receipt`，将所有检测率/分辨率结论拒绝；没有探测
面命中，且该运行不得被简化为“45%传输”。这也暴露了下一轮必须修复的事件记录健壮性问题，随后才可
联合优化 Stripe、棱镜和探测引出。

最新、未被几何审查否决的 run 是
`runs/20260902__full-3d-prototype-default-refine/`。它由冻结 baseline、run-local
解析 L0/L1 工作点 receipt 和同一 `resolved_geometry` 生成，**没有**回写 baseline 的镜电压。
SIMION 2020 已在官方默认 refine 条件下真实生成`pa#`与`pa0`：物理电极 ID 1--24 全部有原生
节点，ideal grid 23/24 分别只占 y 行 1166/1250，网格为`4×0.4×4 mm/gu`。数值探测面是冻结
`detector.box_mm`事件 slab，不是 PA 电极，因此不属于 basis family，也不改变该静电场。

该 run 已完成首个物理 Fast-Adjust basis (`pa1`；51,250 次迭代、最终 Δ=0.005 V、177.19 s)，并正在顺序构建余下`pa2`--`pa24`；完整 basis family、IOB GUI 检查、
100 Th 粒子飞行、K=25/overtones、TOF/FWHM/分辨率以及三档网格/步长收敛均仍未完成。此前在显式
`convergence` 参数下创建的 PA 仅作中断诊断，不能作为 Candidate 场数组证据；活动构建器已强制使用
SIMION 的默认收敛设置。所有本节结果仍是`prototype / Candidate`，不构成 CAD-faithful、Formal 或性能声明。

2026-09-02建立了`candidate_theory_derived_cad_constrained` MR-TOF 候选合同：它冻结理论坐标（中央镜面/注入参考面为`z=0`，`z/y/x`依次为反射/漂移/横向聚焦）、五电极镜的镜像ID、四个物理Stripe到两个理论响应的映射，以及二区加速器第一时间焦点的刚体平移规则。该合同采用仓库的单向几何链：理论/参数合同生成`resolved`参数化简化 CAD 几何，再生成各求解器输入；CAD 只提供五电极包络、30 mm镜束槽、4 mm Ion-Foil束槽、Stripe曲线尺度和棱镜机械尺度等约束。它不使用或修改单反射oa-TOF资产。旧单体GEM/PA/IOB已被GUI审查否决，不能用于任何飞行、传输、焦面或分辨率结论。

同日，新的理论解析几何已通过SIMION 2020粗网格 GEM 编译并完成`pa#`、`pa0`、`pa1`--`pa25` basis 家族：所有25个电极和两个节点对齐的 ideal grid 行均已静态验证。headless模板 IOB 构建会进入模板飞行循环，尚未形成可接受的 IOB/GUI复验或粒子飞行证据；该结果仍只构成 Candidate 几何/场数组证据。

随后 GUI 几何审查否决了该理论解析 GEM/PA/IOB：镜的 30 mm 束槽被错误地实现为全宽矩形减料；Ion-Foil 曲线没有使用已恢复的四个 CAD 装配刚体位姿，导致其`y/z`位置和独立带区错误；二区加速器是任意板盒而非 Astral 加速器的机械基线/理论接口。`20260902__theory-resolved-geometry`下的 IOB、PA 和两次飞行日志仅保留为失败诊断，禁止用于任何几何、传输、焦点或分辨率结论，必须在重建后更换 run id。

之前把二区加速器沿项目`+y`放置的合同及 IOB 已被用户否决。现行 Candidate 令离子从出口沿项目`-z`离开，第一时间焦面严格为`z=0`；这不意味着其`y`坐标为零，当前声明的注入线为`(0,-390,0) mm`。因此从焦面向`+z`依次为 exit grid、grid1、repeller；它们的绝对位置只由两区时间聚焦方程、间隙和该注入线派生。横截面改为`x-y`的`4×4 mm`通道，外形保留`60×60 mm`开孔电极框、两个节点对齐理想栅和`72×72 mm`有限接地护罩；加速器仍使用独立 PA。此前沿`+y`的 PA/IOB 仅保留为错误朝向诊断，禁止用于几何、飞行或性能结论。

Ion-Foil 曲线现已不再采用六点手工近似：`Ion-Foil-1`的外侧 B-spline 边10/直边27、`Ion-Foil-3`的外侧 B-spline 边16/14经只读证据采样为共同`y`节点的25点曲线，并作为`resolved`输入冻结。该项修复仅恢复曲线尺度；为满足理论的两个独立响应区，Foil-3仍须以显式正`z`间隙串联，不能照搬原 CAD 的重叠绝对装配位姿。五电极镜槽则仍缺少可读实体的槽长、端部轮廓证据，当前全宽矩形减料已明确无效，禁止重新生成可运行PA/IOB。

后续 CAD 查询获得用户确认并由只读镜子装配 STL 导出交叉核对：镜槽在项目`x`方向固定为30 mm、在项目`y`方向贯穿完整600 mm镜长。因此所有十片镜电极的`resolved`切口为`x=[-15,15] mm`、`y=[-300,300] mm`，贯穿各自`z`厚度；先前的全宽`x`减料已撤销。只读导出由修正后的`OpenDoc6(Silent|ReadOnly=3)`产生16个独立零件和85个实例，保存在`20260902__mirror-cad-stl` scratch；其外轮廓中的安装孔和机械开窗尚不作为场决定性简化几何，不能与中央30 mm束槽混淆。

同时，resolved 几何检查修复了 Stripe 与中央接地件的真实干涉：中央接地件半高为69.5 mm，两侧均保留12 mm净距；正侧 Stripe-1/2 的范围为`z=[81.5,129.725198]`和`[141.725198,208.405553] mm`，负侧严格镜像。其4 mm纵向通道会按曲线最高点自动扩展，不再使用会截断上端 Stripe 的固定`±200 mm`减料盒。新的待编译 GEM/receipt 位于run identity `20260902__geometry-y-grid-v2`；它还没有 PA、IOB 或飞行结果。

同日，解析 L0 已对上述 resolved 双 Stripe 几何完成最小闭合：两条理论响应在 4 kV 名义能量、`v1=-40 V`、`v2=60 V` 下的因子为`h1=0.9950371902`、`h2=1.0075854437`，响应矩阵行列式为`0.0125482535`；对应物理曲线带宽范围为 set-1 `10.650498--48.225198 mm`、set-2 `14.847907--42.836142 mm`。矩阵的 2-范数条件数约为`319.19`，说明两响应虽不退化但当前偏压间隔的数值分离度有限，后续应在真实场与返回时间平台联合优化中处理。此 L0 不计算镜周期、返回时间、振荡数、时间平台或质量分辨率，不能替代 SIMION 飞行验证。

随后对只读镜组 STL 的平面边界进行复核，并经用户确认了先前遗漏的`z`向封闭拓扑：`反射电极装配-电极A 盖板`是`600×125×5 mm`的 Stripe-facing 接地板，具有约`580×4 mm`的居中长槽；`反射电极装配-电极E 盖板`是`600×120×5 mm`的外侧接地封闭板，没有中心束槽。A--E 五个主反射电极各有约`580×30 mm`长槽。因此当前合同明确为“4-mm内侧接地屏蔽板 → 五个30-mm槽主电极 → 封闭外侧接地板”，而非任何`z`向贯通槽。`20260902__geometry-y-grid-v2`的 GEM 仍错误地将30-mm槽穿过整个镜组，现已否决；它不可再编译或用于PA、IOB、飞行或性能结论。后续必须从修订后的resolved合同使用新 run id生成几何。

在加入端板后，解析包围盒检查还发现原`|z|=190 mm`内侧镜面会与串联后的第二组 Stripe（最大`|z|=208.405553 mm`）发生实体相交。Candidate 不能以互相穿透的 CAD 尺寸进入任何求解器，因此在保持五主电极、30-mm槽、5-mm端板和4-mm内侧槽不变的前提下，将理论优先的内侧接地屏蔽面移至`|z|=220.405553 mm`，即对冻结 Stripe 外包络保留`12 mm`净距；该净距现在由resolved合同失败关闭。此镜间距是待 CAD 顶层位置审计的理论 Candidate，不声称已经复现故障引用的旧总装绝对位置。`20260902__mirror-end-plates-v3`由旧190-mm间距生成，同样否决；后续使用新的 run id。

用户随后澄清镜的`z`位置、五段轴向长度、总体`z`长度及电压均由镜理论决定，而不是由 CAD 决定。合同已将当前几何显式降级为`cad_seed_not_l0_validated`：`220.405553 mm`仅是避免 Stripe 碰撞的下限，不是理论镜间距；`55/57/27/25/29 mm`仅保留为 CAD 机械参考。镜电压字段已从主合同删除：CAD 未提供、也不能推导出任何镜电压。新的`analysis/mirror_l0.py`提供 Berdnikov 轴势、转折点和3900/4000/4100 V三点归一化周期的计算基础；任何 PA、IOB 或飞行必须等待 L0/L1 优化得到三点等时、转折裕量、Poincare 稳定及`gamma≈90°`的理论解，不能把目前 v4 几何作为工作点。

对于已加工镜，现行规则进一步收敛为“几何冻结、电压优化”：五段长度、四个`5 mm`间隙、端板和经审计的实际相对位姿是硬件输入；`mirror_l0.optimize_fixed_geometry_voltages()`只接受这些固定轴向边界，搜索四个非接地镜电压，并返回三点周期残差和转折点。其输出仍标为`l0_voltage_candidate_not_l1_validated`，不会自动写入主合同、生成 PA 或批准飞行；L1 的 Poincare 稳定和`gamma≈90°`仍为必经门。

顶层坐标链现已由两镜总装、单镜子装配和离子箔子装配的只读刚体变换组合验证：项目`z`对应总装`Y`，A侧开槽盖板中心位于项目`z=±104.5 mm`，其间中面为`z=0`；项目`x`对应总装`Z-86 mm`，项目`y`对应总装`-X-158 mm`。这将实机五个主电极的正侧起始边界冻结为`107, 167, 229, 261, 291 mm`，对应镜内侧5-mm屏蔽面`|z|=102 mm`。组合后的四块 Ion-Foil 包络在项目坐标中为`x≈[-12,12] mm`、`y≈[-390,2] mm`，不再使用离子箔局部坐标直接放置。证据为`20260902__two-mirror-pose-audit/composed_top_level_cad_pose.json`和`top_level_project_envelopes.json`。

Ion-Foil-1 与 Ion-Foil-3 的总宽度分别是双 Stripe 理论中的高次项和线性项；它们以原生 B-spline 参数（非采样坐标表）进入 resolved 几何。Ion-Foil-2 同样已经按顶层刚体链合成：其 B-spline 外形构成`x=[-12,-2]`及`[2,12] mm`两片接地导体，二者之间天然保留`4 mm`束槽。此 CAD 曲线只冻结几何，不反推或硬编码 Stripe 电压；电压仍须由独立的理论/场反问题求解。

两只三角偏转棱镜及四件邻近接地屏蔽也已从 GEM 字面量移入同一 Candidate 合同，再由`resolved_geometry.py`验证稳定 ID、两侧`x`带、三角`y-z`轮廓和正体积屏蔽盒后输出。最新只读顶层包络将`grounded 2-1`唯一映射到中央接地旁棱镜：其实体有限于`y=[-3,32] mm`，但沿反射方向覆盖`z=[-97,97] mm`，因而覆盖两内侧接地镜的绝大部分；不得再缩成`z=±26 mm`。另一块`grounded-1`属于另一棱镜、有限于`y=[33,77] mm,z=[-100,-30] mm`。四块 Ion-Foil 的 CAD 包络均有限于约`y=[-390,2] mm`；条带和棱镜屏蔽均不得生成`y`向贯通实体。当前几何保留审计得到的三角尺度，但其顶层安装位姿仍标为 Candidate，不能据此宣称 CAD GUI 或三维场已验证。

在该冻结几何上，`mirror_l0_hardware_candidate.py`以Berdnikov轴势作了一次**宽界限的解析探索**。选择4 kV转折点`278.4 mm`（D电极内部）时，三点周期残差为约`+0.0000042/0/-0.0000033 ppm`，候选电压为`[0,-822.195,5462.447,1264.216,6994.226] V`。这只证明此简化L0模型存在数值等时解；搜索界限不是电源规格，且仍缺少真实开槽/边缘场、Poincare稳定、`gamma`、三维场、PA/IOB和飞行。因此它保存在run-local JSON中，绝不写回主电压合同或作为硬件设定。

该L0解已由`mirror_l1_candidate.py`用同向中央截面定义作二维傍轴筛查，结果为**不稳定**：`(x|x)≈9.026`、`det(M)≈0.9999993`、可逆性差约`-8.5e-8`，故不存在实数`gamma`。这明确拒绝该电压候选，且修复了“把返回反向斜率直接同出发斜率比较会伪造`gamma≈90°`”的符号陷阱。后续优化必须联合三点等时和稳定/`gamma≈90°`；在此以前PA、IOB和飞行门继续关闭。

注意上述首轮解析筛查暂取`H=62.5 mm`（外包络半宽）作为Berdnikov理想边界参数；它不是已验证的实机场半间隙。将`H=15 mm`（30-mm槽半宽）作为另一假设重跑时，L0三点残差约为`976/0/767 ppm`，同样失败。有限三维开槽电极不能从槽宽或外包络唯一推导理想二维`H`，故该参数现在由运行显式传入，并须由二维BEM/真实三维单位基场标定。联合 L0/L1 的两轮`H=62.5 mm`搜索也都未稳定（最小`(x|x)`约`5.47`和`4.81`）；这些是拒绝证据，不是镜的最终物理结论。

后续用户已为当前 Berdnikov 理想模型明确选择`H=15 mm`，即30-mm束槽的半宽；`H=62.5 mm`探索不再是活动假设。物理短的 Stripe-facing 接地盖板继续按 CAD 保留在`|z|=102--107 mm`，但理论镜的首个接地段从中央面`z=0`开始：A 的零电压阶跃在`z=0`为无操作基准，B/C/D/E 的势阶跃由机械间隙中心自动派生。外侧封闭接地端板在解析式中以镜像边界满足零电势；“反对称”仅指该数学镜像法，绝非实体或电压的反对称性。离子的转折位置是多电极等时/稳定性问题的输出，**不得**假定它必须位于E电极；下一道接受门是同一解的L1稳定性、`gamma`和真实三维无碰撞轨迹，而不是按电极字母筛选。

此前的轴势端板解释已被用户纠正：`z=320 mm`后的5-mm封闭盖板与最外侧E电极同电位，**不是接地盖板**。Berdnikov理想二维模型不包含实际槽或板厚，但其§4.3可用理想垂直终端电极平面处理有限反射端；该平面取闭合E盖板的**内表面**`L_e=320 mm`，因为这是镜内真空面对导体的边界，不能误取导体背后的外表面`325 mm`。理论的接地A段直接从`z=0`开始，机械层只用来将后续B/C/D/E势阶跃相对于该中面定位。因此解析模型不得加入`U_E→0`外侧跃迁或接地端板镜像；终端条件应为`U_L=U_E`。三维 CAD/SIMION则必须保留两块实体盖板：内侧者接地且开4-mm槽，外侧者闭合且与E同ID/同电压。末级E电压须高于本次离子最高`E/q`以保留离子；B、C、D及E之间不施加单调排序，其值由等时、稳定和三维轨迹条件联合决定。所有包含错误外侧接地边界的旧 L0/L1 数值结果均为错误输入诊断，不能用作任何电压、稳定性或性能结论。

已将上述边界条件实现为`mirror_l0.py`/`mirror_l1.py`的Berdnikov §4.3 通式：每个势阶跃具有关于`L_e`的同号镜像，终端校正为`2(U_L-U_E)F((z-L_e)/H)`；本硬件线强制`U_L=U_E`，因此该校正项为零而镜像项保留。所有物理数值均由合同或其机械关系派生：三点能量、名义能量、H、B--E搜索域、`L_e`和`U_L=U_E`均不在活动入口中硬编码。最新 H=15 mm、`L_e=320 mm` L0 run 取得三点周期残差约`-4.7/0/+3.3 ×10⁻⁶ ppm`，但随后同一解的 L1 中央截面映射为不稳定（`(x|x)≈-3.089`，无实数`gamma`）；它被拒绝，未写入电压合同，PA/IOB/飞行门仍关闭。证据位于`20260902__mirror-l0-h15-terminal-e-inner-plane` run-local scratch。

同一冻结几何和合同电压域上的无转折位置预设联合 L0/L1 搜索随后得到解析候选：`[U_A,U_B,U_C,U_D,U_E]=[0,-5159.567,3904.875,5502.648,7999.360] V`，三点周期残差为约`+1.24/0/-1.61 ×10⁻⁶ ppm`，`det(M)=0.99999995`、`gamma=89.999998°`。终端平面仍为`320 mm`且`U_L=U_E`。这是无限`y`二维解析筛查的 Candidate，不能写回主电压合同，也不能代替真实开槽、板厚、侧壁和完整三维场；只有先关闭几何净距并在SIMION PA中复验后，才允许 IOB 和飞行。证据同在`20260902__mirror-l0-h15-terminal-e-inner-plane/mirror_l0_l1_h15_no_turn_target.json`。

顶层 CAD 坐标复核还修正了长期镜的`y`放置：600-mm镜长的中心由`cad_to_theory_frame`派生为`y=-158 mm`，即机械范围`[-458,142] mm`，不允许在resolved几何中擅自以`y=0`居中。原先把 Foil 的包围盒和中央接地件包围盒视为实心矩形，并将两条已具 CAD 绝对位置的曲线再次在`z`方向串联，是错误的建模假设，已撤回；CAD 已确认 Foil 与中央接地件可容纳在镜间。曲线自身的同`y`宽度为 set-1 `10.650498--48.225198 mm`、set-2 `14.847907--42.836142 mm`，均小于204-mm镜内总间距。resolved合同现在直接采用 CAD 项目坐标的曲线，不再施加合成`z`平移。仍未完成的是中央接地件的**实际开口轮廓**：在该轮廓只拥有包围盒证据前，禁止把它错误简化为实心盒并生成PA；必须完成只读 CAD 轮廓审计后再关闭此门。

同日的只读 SolidWorks 2022 审计已取得镜组和棱镜的局部包络，但确认顶层/离子箔装配的旧绝对引用损坏，且三块 ion-foil 零件不能直接打开；完整证据、可用尺寸与关闭条件见[`CAD_AUDIT_20260902.md`](CAD_AUDIT_20260902.md)。在该门关闭前，不会以方盒替代 Stripe 曲线或报告 CAD-faithful 的离子飞行/分辨率。

2026-09-02 的曲线合同进一步收敛为“理论 B-spline 参数化、CAD 作为该参数化的只读实现证据”：活动 `resolved_geometry` 只评价原生三次 B-spline 的 knot/control 参数，不再读取旧的 25 点 CAD 边界采样表。对总板间宽度的精确求值显示，`Ion-Foil-3` 对应的 Stripe-2 宽度可用线性项表示（端点线性模型的最大残差约 1.1 μm），而 `Ion-Foil-1` 对应的 Stripe-1 宽度为高次响应。这个分类规定了后续的理论反演接口；它**不**使 CAD 几何单独唯一决定电压。电压仍须由目标 \(\psi,g\)、镜周期/三点等时、目标 \(K\) 与真实三维场联合求解，不能从控制点坐标直接当作已知硬件电压。

本机证据入口为
`artifacts/projects/parallel_mirror_dual_stripe_mr_tof/archive/`
`20260801_130002__migration-snapshot__repo__mr-tof/legacy-project-root/archive/`
`20260721_102322__migration-snapshot__cad__initial-user-design/archive_manifest.json`；
manifest保存原始来源、119个文件（9个SLDASM、110个SLDPRT）、48,392,256字节和逐文件SHA-256。
manifest中的`mr_tof`是迁移前记录身份，只读保留且不允许接收新运行。新运行使用当前
`parallel_mirror_dual_stripe_mr_tof`身份和同名artifact根。二进制不进入Git，因此换机后须单独迁移
artifacts并复核哈希。旧artifact根已经逐文件迁入并删除，描述符状态为`archived_verified`，解析器不再
回退或搜索迁移前顶层路径。

## 分阶段建立顺序

1. 在 SolidWorks 2022 中打开顶层装配，检查丢失/外部引用、零件数量、单位、坐标系和保存警告；冻结原始快照，不原位改写。
2. 以已选平行镜双条带拓扑建立项目理论绑定，明确时间聚焦条件、质量范围、分辨率、振荡数、传输率、
   两套条带电压/形状和尺寸约束；原Astral参数只作参考测试。
3. 从获批理论和工程输入建立`baseline → resolved`机器合同，并识别可优化变量、硬约束和制造容差。
4. 由同一resolved合同建立低保真解析参考、COMSOL/SIMION独立候选及CAD生成路径；先完成最小单粒子/单圈验证，再扩展多圈和统计验证。
5. 完成数值收敛、跨求解器、GUI可检查、SolidWorks同步、性能和鲁棒性门禁后，才允许生成第一套formal资产。

## 开放问题

- 顶层装配身份、装配引用和绝对路径依赖尚未检查。
- 工程图中两套漂移条带的面对面电极、电气分组、中央接地走廊、棱镜和镜平行关系尚未映射；哪些部件
  属于分析器本体、离子源、注入/引出、真空和检测子系统也尚未划界。
- 反射次数/圈数语义、飞行事件、全局时间和粒子年龄合同尚未定义。
- 活动理论尚未编译为机器合同；设计数值、验收阈值和优化优先级仍待确定。
## 2026-09-03 geometry-review SIMION release

The prior 8-mm `z` mesh was rejected for visual geometry review: it cannot
represent a 5-mm mirror inter-electrode clearance or the positive physical
Stripe-to-Stripe clearance.  The replacement review-only PA uses
`(x,y,z)=(2,0.8,2) mm/gu` and a bounded `180 x 700 x 720 mm` physical domain.
It is allowed solely to inspect the CAD-constrained assembly and its assigned
prototype voltages in SIMION.  It is neither a field-convergence nor a flight
or resolution result.  The following mechanical facts are preserved in the
GEM source: each active mirror plate has a `30 x 580 mm` bounded aperture;
the inner 5-mm grounded cover has its own 4-mm aperture; the outer 5-mm E
cover is closed; the four physical Stripe bodies have an explicit nonzero
serial clearance; and prism/accelerator coordinates are expressed in the
frozen project frame.

### 2026-09-03 finite-slot CAD correction

The preceding review geometry's Ion-Foil `4 mm` beam channel was still
incorrectly cut through the whole project-`y` extent.  A new read-only
SolidWorks STL plus native-sketch audit of the frozen working copy establishes
that the 392-mm Ion-Foil body retains material bridges of **5 mm at its
project-`y` minimum end and 2 mm at its maximum end**.  The active resolved
contract now derives the slot as `y=[-385,-2] mm` inside the `[-390,0] mm`
body and rejects a missing or through-cut bridge.  This fixes the four Stripe
conductors' topology but does not yet close the analogous grounded-prism
frame audit: their two CAD parts have different nested-clearance feature
chains, so no value is borrowed from the Foils.  No new PA/IOB has been built
from this intermediate state; the prior geometry-review IOB remains rejected
for inspection only.

### 2026-09-03 central grounded-2 cross-aperture measurement

User measurement fixes the central (`grounded 2`) cross aperture: the
reflection-axis opening is `80 mm` with two `57 mm` end lands in the
`194 mm`-long grounded frame, hence `z=[-40,40] mm`. Both branches retain the
`4 mm` project-x width. The `22 mm` drift-through branch is now fixed as
`y=[6,28] mm`: from its effective far-Stripe-side frame edge `y=32 mm`, leave
`4 mm`, then open `22 mm` toward the Stripe; this leaves the `3 mm` wall to
the effective Stripe-side edge `y=3 mm`. `grounded 2` is emitted as one
continuous `e(20)` grounded frame with this rectangular cross opening and
the separately nested triangular prism clearance. The false `e(20)/e(21)`
two-side representation has been retired; PA/IOB regeneration remains gated
on the normal full-geometry static checks and user GUI review.

### 2026-09-03 accelerator aperture and grounded-1 topology correction

The MR Candidate accelerator's declared transverse aperture is now
`25 x 25 mm`, not `4 x 4 mm`; repeller and the five second-zone rings are
therefore 40-mm outer open frames with the same contract-derived 25-mm clear
aperture. The two ideal grids remain planes. This is an MR Candidate input,
not a statement about the existing Astral accelerator hardware.

`grounded-1` is one CAD physical frame, not two `x`-side electrodes. Its
composed top-level project envelope is `x=[-24,12]`, `y=[33,77]`,
`z=[-100,-30] mm`; its CAD 4-mm channel is the finite rectangular subtraction
`x=[-2,2]`, `y=[35,75]`, `z=[-100,-30] mm`. Consequently, the two 2-mm end
lands at `y=[33,35]` and `[75,77]` arise from the single solid after slot
subtraction. They must never be represented as independently added bridge
boxes. The associated prism's audited box is `x=[-12,12]`,
`y=[42.828427,67.828427]`, `z=[-90,-40] mm`; these figures confirm that its
start remains inside the shield clearance.

The reusable, solver-neutral two-zone time-focus equation now belongs to
`common/accelerator/two_zone_theory.py`, alongside the existing neutral ring
and enclosure derivations. This common core is an independent accelerator
subsystem, not an oa-TOF asset; OA and MR retain separate scientific contracts,
three-zone theory, coordinates, CAD and solver assets. No OA Formal source,
PA, IOB or voltage contract was altered by this change.

### 2026-09-03 first finite-3-D prism interface observation

After GUI approval of the assembled Candidate geometry, a new run rebuilt the
detector's independent raw zero-voltage PA and materialized the unchanged
analyser and accelerator PA families from the content-addressed cache.  The
cache materializer now re-copies only divergent files once before its final
byte-for-byte refusal; it never accepts an unverified PA family.  The new
three-instance IOB reloaded with all 28 physical adjusted electrodes and its
independent detector PA before flying.

The bounded first-prism diagnostic then flew exactly one 524 Th, +1, 4-keV
particle from the two-zone focus through prism 16 to its frozen grounded-1
interface plane.  SIMION recorded the interpolated interface point as
`t=2.64642090795 us`, `(x,y,z)=(-0.00287412885,54.0501194774,-101) mm`, which
is inside the contract's `y=[35,75] mm` acceptance.  Evidence is the verified
run `20260903_194116__sim__simion__first-prism-finite-3d` and its
`results/first_prism_l0_result.json`.  This is a prototype observation of one
interface crossing only: it does **not** validate the second prism, K=25
circulation, first-order time focus, transmission, detector TOF, FWHM or
mass resolution.
