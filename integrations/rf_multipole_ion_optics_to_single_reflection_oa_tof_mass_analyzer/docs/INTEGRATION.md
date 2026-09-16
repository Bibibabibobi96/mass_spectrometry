# RF多极杆到单反射oa-TOF当前集成状态

本页只维护当前设计、资格、限制和待办。操作见[RUNNING](RUNNING.md)，参数与失效域见
[ARCHITECTURE](ARCHITECTURE.md)，历史见[HISTORY](HISTORY.md)。文档收口未执行新求解或晋升。

## 所有权

- 上游项目拥有器件几何、RF驱动和canonical输出；源以冻结粒子表发布，不能因源的生成方式另立输入权威。
- 独立[加速器项目](../../../projects/orthogonal_accelerator/README.md)拥有局部理论与构建，
  [oa-TOF](../../../projects/single_reflection_oa_tof_mass_analyzer/README.md)拥有整机布局、反射器、耦合和Formal资产。
- integration拥有连接器、端口绑定、单飞适配、campaign生命周期、联合分析和集成证据。
- 唯一公开执行入口为[execute.ps1](../workflows/family_source_closure/execute.ps1)；
  [run_single_flight.ps1](../runtime/run_single_flight.ps1)是其内部SIMION运行边界。

## 当前配置与入口

| 对象 | 权威来源与范围 |
|---|---|
| 连接、端口与位姿 | [connection profiles](../config/connection_profiles.json)及两端port合同 |
| 活动campaign发现 | [lifecycle registry](../config/diagnostics/lifecycle_registry.json)；普通探索按显式exploration准入 |
| 单飞布局 | [layout profiles](../config/single_flight_layout_profiles.json) |
| 300 mm孔径矩阵 | [pre-pulse合同](../config/explorations/ideal_acceptance_300mm_terminal_aperture_height_axialgrid010_pre_pulse_n5000.json) |
| 当前来源 | `continuous_frontend`或`pre_pulse_restart`；后者不能冒充完整母群连续传输 |
| 准备输出 | authored最小行单向展开为resolved plan/source/budget并冻结到run-local |

当前20环三区候选为`CANDIDATE_ONLY`，不改变原Formal。完整母群使用
`frontend_xy025_z010_coarse100_full_bore_main_local_xy050_z010`与`full_accelerator_v1`。
上游细域、主域与local网格来自冻结profile，不由文档数值表另行定义。
旧横向core、零场碰撞载体与旧pre-pulse优先级均不能成为当前完整母群路径。

连接器继承上游屏蔽截面。正gap时有带孔端板，方形零gap不另造套筒或端板；圆形侧口由具名
对接合同派生。长gap分域由冻结bridge合同控制，粗PA提供Dirichlet来源、细PA按优先级替换，
不叠加场。孔径由入口local表达；缺少local或主family身份不闭合时不能飞行。

单飞及分段analyzer入口已在外层区分轻准备、refine重计算、飞行重计算和轻后处理；
[阶段运行边界](RUNNING.md#主机资源阶段)说明适用范围。此次改动不改变既有内部并发、观测和断点续算，
也不增加真实求解或物理资格结论。

## 当前资格与有效证据

| 范围 | 当前判定 | 证据与限制 |
|---|---|---|
| 单粒子分域路径、restart与局部缺陷修复 | 已有专项功能证据 | [历史索引](HISTORY.md)，不证明统计、场收敛或八臂完成 |
| 旧零场／旧细域孔径比较 | 仅历史诊断 | 几何、电势或上游细域改变后，不能复用其handoff与当前结果混表 |
| 9月11日第一组三链对照 | 物理资格失效 | RF对象作用域错误导致脉冲前RF未更新；匹配的检测数字也不能恢复资格 |
| 修复RF后的第二组三链对照 | 对照失败 | pre-pulse IOB优先级与continuous不一致，producer状态集合不闭合 |
| 当前修复后的方形h100 | 仍需重跑闭合 | 重建pre-pulse证据，再派生post-pulse与同钟continuous；不重复refine相同family |
| 圆形四孔径与完整八臂 | 未完成 | 缺当前场family及完整三阶段证据，不宣称孔径优劣或分辨率提升 |
| Formal与跨求解器等价 | 本轮无新增资格 | 不能由局部命中、单点峰宽或文档整理取得 |

两组三链的精确run身份、数字、失败原因及整治前叙述保留在
[失效对照与文档快照](history/20260911__single-flight-documentation-and-invalidated-comparisons.md)。本页依据已有源码及记录收窄冲突声明，
没有重新核验全部外部manifest。运行前核对所用修订、冻结输入和对应验证收据；文档中的实现描述、
工作区文件存在或代码已提交均不能单独证明该入口已通过真实运行或取得物理资格。

## 限制与判定边界

完整母群分母始终保留。post-pulse条件群的检测率不能代替母群传输，少量命中不能证明峰宽优劣。
离散检测/损失一致、脉冲状态一致、轨迹数值等价与场收敛分别验证；一次PASS不能覆盖其他层级。
修复后的四槽pre-pulse必须与continuous保持同一PA角色优先级；所有旧数字只在对应冻结实现下解释。

来源快照只证明实际记录的依赖身份；尚不宣称全部Python运行与工作树彻底隔离。
恢复只能消费核验过的来源，建立新run；外部输入缺失、源或时钟不一致时不能凭历史文件名猜测。

## 开放任务

| 动作 | 进入条件 | 关闭条件 |
|---|---|---|
| 方形h100修复后全链对照 | RF作用域与IOB角色修复已通过相称静态回归 | 新pre/post/continuous冻结同母群、时钟和场；状态/终态与误差判据独立核验 |
| 完成其余方形并扩展圆形 | 前一阶段完整且缓存来源可核验 | 八臂完成，发布完整母群比较与不确定度，不使用共同命中子群 |
| 分域与整体场比较 | 同几何、源、电压、时刻和数值预算 | 电势/场交接及配对粒子差异满足预登记判据 |
| 扩充跨工具路径preflight | 使用已有公共短路径和run package机制 | 各入口声明深层路径与实测限制；PA完整性错误不混同MAX_PATH |

既有SIMION只读standalone长PA输入已由[公共参考](../../../docs/SIMION_REFERENCE.md#长pa输入路径)闭合，
不再列为待开发能力。原生family仅在一次性构建staging中操作，运行消费已发布standalone表示；
具体输入边界按该公共参考核对。尚未迁移的入口不能沿用旧family物化步骤启动供应商进程。
跨工具preflight待办不代表公共长路径能力尚未实现。
