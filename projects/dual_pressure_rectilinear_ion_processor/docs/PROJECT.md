# 双压力区矩形射频离子处理器项目状态

## 当前目标与资格

以贴近公开文献的简化实体电极贯通多极引导、HP 捕获冷却、LP 输运聚集、整体抬升、RF 淬灭和正交引出。
生产电场来自真实电极的原生 Laplace 求解；旧解析规定场不是生产场。
当前未建立新的 N=100 功能结论、空间/全程时间步收敛、GUI/CAD 验收、COMSOL 对照或实际仪器性能资格。
旧探索与旧场借用方案已被取代，完整记录见[历史快照](history/20261016__native-flight-and-source-identity.md)。

## 科学权威与几何

[baseline](../config/baseline.json)拥有几何、气体、RF 和时序；
[原生电压](../config/native_operating_point.json)是电极电压唯一权威；
[numerics](../config/numerics.json)拥有离散；[geometry sources](../config/geometry_sources.json)只映射来源，不另维护设备参数。
文献依据为 Stewart 等的[装置论文](https://pubs.acs.org/doi/10.1021/jasms.3c00311) Figure 2/3 及正文。

| 几何量 | 当前解释与边界 |
|---|---|
| HP / LP 长度 | 100 / 80 mm；主阱内切半径 r0=2 mm |
| 引出狭缝 | 8×0.8 mm，实体 Pull 板开孔 |
| HP 辅助楔形电极 | 对角间距4→7 mm，对应径向2→3.5 mm；不是理想四极双曲面 |
| 入口孔 | 将文献“2 mm 钢孔”解释为直径2 mm圆孔，不是半径2 mm；孔型属于模型解释 |
| LP 外辅助板 | 面向离子的内表面总间隙中心4 mm、端部3.7 mm，板厚向外增长 |
| LP 内辅助板 | 轴向全长2.5 mm，局部 z 内表面±1.4 mm、板外表面±1.6 mm，内表面净距2.8 mm |
| 离散 | 0.1 mm均匀网格，HP/LP辅助形状各60段中点阶梯；不表示60组独立电极 |

引导段30 mm、LP 中心 local x=170 mm、平板宽厚、内辅助板具体定位、3/3.5 mm浮动屏蔽半宽、
透镜细节和末端透镜50 V是项目假设或工作种子，不称厂家 CAD。
15个可调电极包含随 HP/LP common-mode 浮动的屏蔽；实体、孔、场域和编号由同一 native projection 派生。
几何改变必须重新 Refine；当前方案每个新主运行从 GEM 构建私有场，不用旧 PA 族的重读匹配追认为身份恢复。

## 坐标、时序与工作点

原生 PA、native projection 和 source.json 保留局部母集：local x 沿 guide→HP→LP，local y 引出，local z 为另一径向。
[刚体变换](../config/coordinate_transform.json)给出 `world=(-local_z, local_x, 9.8-local_y)` mm；向量只旋转，时间不变。
世界 x 为横向、+y 为慢漂移、−z 为加速，frame 为 `ion_processor.xyz.reflection_z.drift_y.transverse_x.local.v2`。
它与 MRTOF 方向兼容，但装配 port Y 尚未注册，不能称 MRTOF 全局坐标。
气体分区、接受域和 HP/LP 占据仍在逆变换后的 local 坐标判断，慢轴压缩使用 `slow_sigma_y_mm`；
canonical 半径/散角相对 world z，`max_rod_radius_mm` 不代表世界原点圆柱门。

RF 配置为3.7 MHz、`rf_peak_to_peak_v=1000 V`，实际电极波形由公共 RF 核及原生 drive 派生。
捕获时 HP−5 V、LP0 V；HP 输运偏置2 V；LP 抬升至4 kV，引出 push/pull 及 split 侧电极相对电压±900 V。
这些是功能工作点，尚未优化；均匀整体抬升不直接增加阱内动能，主要加速来自出阱电势落差。

捕获截止1500 μs、输运截止4000 μs、整体抬升4000…5500 μs；
`extraction_start_us=5500`是 RF 淬灭时刻，真正脉冲延后0.5 RF周期，即5500.135135… μs。
测量面 local y=9.8 mm（world z=0）距 local y=10 mm数值地边界两个网格，只是观察面，不是实际质量分析器。
末透镜后的 local x=211.25 mm 是 PA 内下游数值出口，不是金属；`radial_escape`也是接受域终止，
`solver_stop`不能独自确定撞击电极。

## 母群与碰撞绑定

默认源为524 amu、+1、5 eV、N=100，使用公共 Halton 薄圆柱入射片；版本化 N=10 只供探索，不授予功能资格。
气体规定为28 amu、300 K，HP 1 Pa、LP 0.2 Pa；压力是几何回调，不是气流求解。
截面2.27e−18 m²来自官方 HS1 示例，未经 N2/524 amu标定；MFP=-1、steps_per_mfp=20。
未建模碎裂、反应、空间电荷或离子间碰撞。

runtime 使用显式 `adjustable` 设置导入 HS1 的9项参数，初始化前后内部 getter 逐项断言并写审计。
每粒子实际开始积分时重置 HS1 私有状态、重赋和核对参数，然后执行 `seed=base_seed+globalID−1`；
本母群映射42…141，HS1初始化参数43不是所有粒子的最终seed。
这些是可追溯赋种及模块绑定机制，不证明随机子流独立或逐轨迹精确重放。
旧气体绑定或旧源身份问题的运行不能提升为当前已验证 N2 物理证据。

## 自动并发与统计评价

生产入口使用公共首正式批45秒观测、实测资源重规划和批执行器，不固定项目并发数。
worker 消费同一冻结100粒子母群的区间，保持绝对 RF 时钟，按公共 offset 合并事件、样本和 seed；
根控制文件保留完整100粒子，根 HS1 CSV 是所有 worker 核验同值后的派生 pair，不表示 master 自身 Fly。
CLI worker 关闭可选稠密 TRJ，但完整 events/samples CSV仍保留；GUI 的完整母群保留轨迹显示策略。
资源与峰值容量由[execution profile](../config/execution_profiles.json)及实际公共回执约束。

功能目标以[验收合同](../config/acceptance.json)为准：捕获/引出率均至少0.9、HP均能不超过1 eV、
引出前慢轴σ不超过2 mm、引出子群均能3500…4500 eV。
保留完整母群和损失，不用仅LP条件子群代替全体分母，也不调阈值制造通过。
随机碰撞实现不同本身不是物理或并发失败；GUI统计复现应比较比例及位置/能量分布。
精确分区重放未验证，不作为新的 N=100 门禁；尚无独立 ensemble 重复或统计等价检验，不能承诺单次 N=100 误差范围。

## 当前N100运行

`20261016_014153__sim__simion__ion-processor-n100-auto-private` 已完成真实 N=100：10批、实际峰值9路，公共批执行374.156秒（不含首批45秒观测、前置构建和后处理）。100个source与100个terminal ID闭合，18文件场族在Fly前后身份一致，HS1内部参数与42…141赋种审计完整。

| 指标 | 实测 |
| --- | --- |
| 捕获 | 100/100 |
| 引出观察面 | 85/100 |
| 终态 | acceptance_surface 85、solver_stop 14、timeout 1 |
| 捕获均动能 | 0.03908 eV |
| 引出均动能 | 3928.694 eV |
| 引出前全体存活 | 99；慢轴σ=5.24752 mm |
| 其中LP子群 | 98；慢轴σ≈0.2008 mm（条件子群，不替代全体判据） |

`functional_status=functional_incomplete`、公共终态`status=failed`：引出率、全体聚集及LP占据判据未满足；捕获、冷却及引出能量满足。未调整参数或阈值制造PASS。
纯分析run `20261016_015317__analysis__simion__ion-processor-n100-loss-diagnosis` 保存全部15个未引出ID的终态六维状态、最后样本、连续CSG最近电极/间距、脉冲相对时刻和图。
13个solver_stop在引出阶段邻近E5拉出电极(9)、E7侧电极(3)、E14屏蔽(1)；1个在输运阶段邻近E11。它们是几何关联，原生碰撞电极ID仍unknown，不能仅凭最近电极证明因果或数值收敛。
ID37在5520 μs超时，world y=118.6858 mm，仍在HP；不得把timeout的最近金属解释为撞击。

完成分析后，通过公共owner-completion退役本CLI场族3,313,116,304 B，保留全部CSV、日志、图、IOB和冻结输入，并用公共退役回执验证剩余证据；原manifest保持历史身份。CLI旧IOB须重建场后才能用，不作为用户直接入口。
用户工作台 `20261016_015429__test__simion__ion-processor-n100-user-workbench` 已从同一冻结GEM独立Refine并封存为未Fly checkpoint，完整18文件场族保留；未复制或vendor-open已退役PA。运行控制、完整100源及Fly2与CLI master逐字节相同。57,106个对应采样点的电势及三分量电场值全部相同（max绝对差均0）；该有限采样比较不代表全场身份或收敛证明。GUI由用户打开、Fly和确认，Agent未执行GUI或追加重复Fly。

首个准备运行 `20261016_013420__sim__simion__ion-processor-n100-auto-private` 在Fly前失败：官方wb:save同时输出IOB/Lua/Fly2，而消费器原先只允许IOB。现先核对伴随Lua与完整母群Fly2的SHA，再生成批次切片；未知项或漂移仍拒绝。该失败run的3,313,116,304 B可重建场已公共退役，小证据保留15,332,048 B，不复用其run_id。
新producer结束写入后，在私有可写场范围完成落盘再建立不可变身份；不对旧immutable场flush来追认历史身份。summary.status使用success/failed供公共生命周期消费，functional_status单独保存功能判据结果。

## 诊断与剩余边界

[全过程诊断](../config/diagnostics.json)包括几何轨迹、分时离子云、阶段相空间、能量/慢轴位置/展宽、
全母群状态闭合和带 ID 损失表；缺记录为unknown，不能外推最后位置为存活。
[原生场诊断](../config/field_diagnostics.json)查询真实 PA 的分时电势/电场，原始局部 CSV保留，
另输出项目坐标 CSV；图形明确来源、单位、选择和拟合范围，不把局部二次拟合用作电场或收敛证明。

本轮N=100、真实负结果、损失证据和用户加载包已完成；GUI人工确认由用户执行。上游端口、MRTOF 全局装配、COMSOL 对照、
全程时间步与网格收敛仍未完成，不自动扩展成优化或高统计扫描。
