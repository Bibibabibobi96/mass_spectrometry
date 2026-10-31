# RF多极杆离子光学：SIMION实施与验证

本页覆盖统一多极杆项目的SIMION入口，并区分四极杆专属workflow与四／六／八极共同typed模式。
三变体共用的设计、输入冻结与投影机制见[实现与运行合同](IMPLEMENTATION.md#求解器投影)；
下表中的无碰撞传输支持三变体；接口就绪和质量过滤保留四极杆范围，不由家族名称扩大资格。
本文只说明SIMION几何、Program、运行入口与独立验收。跨求解器状态和开放任务只见
[`PROJECT.md`](PROJECT.md)；2026-07-28以前的完整run、数值和故障链冻结在
[`retired_projects/rf_quadrupole_ion_optics/docs/history/20260728__pre-document-consolidation-simion.md`](history/retired_projects/rf_quadrupole_ion_optics/docs/history/20260728__pre-document-consolidation-simion.md)。
多极杆各轴向实体、事件面和`numerical_census_marker`只采用
[实现与运行合同](IMPLEMENTATION.md)的统一术语。

## 几何与运行时权威

三变体无碰撞传输使用[共同求解器投影](IMPLEMENTATION.md#求解器投影)和具名runtime profile。
活动GEM由[设计同步器](../analysis/sync_simion_geometry.py)从具名profile编译的resolved发布生成，
生成GEM不得手改。无碰撞、接口就绪和质量过滤入口共用[simion_transport.lua](../simion/simion_transport.lua)，
各自冻结实际Program、粒子与PA输入；共享机制不扩大各workflow的物理资格。
默认裸杆不生成接地边界电极；显式圆柱壳及可选端盖共用同一0 V电极。
外部孔板／透镜由装配加入，不在Program中补出几何或可调端盖电压。
共享模板、GUI复核、`.wgem`绕行和跨工作区可移植性状态只由[实现与运行合同](IMPLEMENTATION.md)登记。

Lua只实现RF-only或RF+DC Fast Adjust、静态电极、时间步上限、最长飞行、事件/轨迹和summary，不含
collision、drag、pressure或buffer-gas逻辑。物理量来自冻结resolved；共同传输数值来自具名runtime绑定，
四极专用workflow使用自身数值合同。实际采用的正数步数与trajectory quality会冻结
进run config与Lua。入口可用于探索性数值取值；非基线取值只标记为未资格的探索结果，不得冒充既有
baseline或资格证据。Program不得以未记录的默认值或命令行覆盖物理权威输入。

## 活动入口

有限三维无碰撞、四极接口就绪及质量过滤的现有 SIMION CLI 均接受 `-ContinuationPredecessorManifestPath`：传入同项目、同 workflow 终态 run 的
`run_manifest.json`，并为本次执行指定新的 `-RunId`。运行器验证源、场、数值和原批分区，
在容量保护及只读锁下引用 manifest 绑定的完整批次；缺失单元重新飞行，全复用时不启动 SIMION。
compact 分析只需状态与摘要；qualification 和 solver_review 还要求批轨迹。旧资产缺少必要的
冻结身份或批 receipt 时拒绝复用。续跑 plan 保留直接父 run 与各批真实来源，不修改父终态。
Fly 配置由冻结的 `simion_fly_physics.json` 同时驱动 Lua 和原生命令，比较物理输入而不把分析代码变化
视为飞行变化。只读句柄在当前进程存活期间保护来源；若写入者状态未知，保留容量保护记录，进程退出后
操作系统会关闭句柄。恢复前须重新确认写入者已结束。这些是软件恢复合同，不代表真实求解或科学资格。
已由无求解器测试覆盖完整与部分复用、两代来源、身份漂移及缺批派发；尚未以真实 SIMION 求解验收。
接口就绪和质量过滤沿同一批次机制保存完整 worker 的原生完成 receipt，引用原始 state／summary，
compact 续跑不要求已被保留策略删除的轨迹样本。部分缺批保持原分区，只观测并补做缺失完整单元；
分析失败后可从原 CLI 指定该失败 run 为前驱，在新 run 中重分析。全复用只取得分析资源，不构建 PA 或原生 IOB。
prepared 与 finite 恢复均使用公共固定分区 selector，按本 case 实际最大缺失完整单元选择冻结画像。
画像不足时该原单元就是正式观测批，观测进程保留并计入 CPU／内存及互斥准入；覆盖充分后不因恢复而固定单路。
finite 后续更大缺失单元重新检查画像，不沿用不足的小单元观测；原分区、ID和已完成结果保持不变。
这项接线已由软件 worker／真实 CLI 参数测试覆盖，未据此新增原生求解或科学资格。

三个 CLI 另接受 `-NativeFieldRunPath <原producer run或manifest>`，仅复用相同实际 GEM/include、grid/cell、
原生 gem2pa/refine 参数及求解器身份的 fractional 场；源或分析改变不重新求场。两个四极专用入口默认
采用 `solver_review` 保留原 producer 的 PA family、fractional companion、IOB 和小 checkpoint。
Refine 成功即记录 field-ready，布局尚未完成时续跑只补必要 IOB；正常完整布局直接引用原 IOB。
部分批次恢复默认取前驱的场，显式场来源仍须通过同一身份和原生完成事实校验；全批复用跳过场读取、
PA 验证及模板复制，但继续比较本次实际 Fly 布局与参数。原 producer 资产沿现有容量保护和公共 PA 只读锁
持到消费者收尾，不发布第二份 cache，不改变 fractional surface、Refine 停止条件或现有物理资格。
两入口冻结同一个公共 `rf_drive.lua`，检查与 Fly 都显式传递该 kernel；相位由冻结 resolved 的 `phase_rad`
经同一 core config 传入 Lua 和分析，不再读取不存在的 `phase_deg` 或二次换算。
无碰撞有限三维入口接入 `-ResumeFinalization -RunId <run_id>`，并在 run 外保存小 Result；收尾复用现有冻结请求、
capacity session、实际 PowerShell owner 和 native 进程完成事实、终态 journal，不重飞也不改父终态。
Result 包含执行与数据状态、科学结果、失败原因、恢复动作及耗时。显式前驱仍用于以新 run 补缺批。
目前已用无求解器真实进程验证跨进程发布失败恢复、存活的 inherited grant 复验和原 CLI 恢复接线；
原 CLI 正常求解到收尾及真实 SIMION 求解尚待验收。host release 后、wait/completion 写入前若进程突然崩溃，现有 ledger 不保留
足够的 release 与操作退出事实，不能自动恢复该窗口；必须检查实际 writer 和 grant，不得推定成功。

| 科学问题 | 入口 |
|---|---|
| 接口就绪输运 | `../workflows/interface_readiness/run_simion.ps1` |
| 四／六／八极无碰撞传输 | `../workflows/no_collision_transport/run_simion.ps1` |
| RF+DC质量过滤 | `../workflows/mass_filter_reference/run_simion.ps1` |
| IOB结构检查 | `../simion/workbench/inspect_builtin_quad_reference.lua` |

接口入口只接受配对bundle中的canonical表示；质量过滤入口只接受显式基础ION11并生成逐质量配对表。
无碰撞入口的具名runtime profile绑定当前杆系typed电气模式，但不接受自由design/source路径，
也不得选择矩形`official_transport` integration oracle。

接口就绪与质量过滤入口向公共 SIMION 调度器提交粒子总数和冻结数值身份；资源识别、并发与回收
由[公共实现](../../../common/simion/README.md)维护，项目不保存第二套调度参数。

## 输出与来源纪律

新运行输出canonical粒子事件表、稀疏轨迹、summary及run manifest。源事件、杆端、出口孔穿越、
规范交接、近接口统计和terminal事件均保持粒子ID、三维位置/速度、能量、RF相位和终止原因。
terminal只表示数值标记、撞壁、超时等终态分类，不是近接口统计面的别名。接口运行必须逐ID证明canonical与ION11
两种表示等价；质量过滤响应稳定文件名为`mass-response__simion.csv`。

IOB加载门禁必须检查：

- 单一项目PA实例及本地路径；
- 放置变换、尺寸、cell size和PA checksum；
- Program/Fly2与冻结run config一致；
- GUI中Program、Adjustables、粒子定义和PA实例可检查；
- 运行和分析失败按三件套失败关闭，不以文件存在判成功。

## 数值与资格边界

已完成的敏感性、资源终态及接口比较只以 [PROJECT](PROJECT.md) 和其资格合同为准。
旧数值表与已退役接口叙述保存在
[历史记录](history/retired_projects/rf_quadrupole_ion_optics/docs/history/20260911__solver-sensitivity-and-retired-interface.md)，不构成活动运行授权。

RF 多极杆到 oa-TOF 的连接由 integration 拥有；项目只提供端口与 canonical handoff。
公开入口由[项目 README](../README.md#工作流入口)导航，不再使用本项目旧 pulse_capture 链。

长 PA 输入和缓存隔离遵循[公共 SIMION 参考](../../../docs/tools/SIMION_REFERENCE.md#长pa输入路径)。

圆杆 L2 传输使用已认证 field-screen run 的冻结设计、合同与采样结果，要求与当前解析设计的真实杆阵列、坐标、r0 和极数一致，并仅采用杆半径比例严格匹配且通过场筛选检查的唯一候选；缺失或不匹配时拒绝，不以最优候选替代既定几何。场筛选为带接地外边界的二维场，传输使用其有限余弦谐波沿 z 均匀延拓，不代表三维真实求解或科学资格。当前 octupole 的既有扫参不含基准设计比例 0.5，需要匹配该设计的已认证场数据。
该近似使用 20 mm 接地边界，不等同于裸 enclosure 的完整场；传输截断为有限余弦谐波，不使用正弦谐波。
