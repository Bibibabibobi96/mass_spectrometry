# 独立系统指南完整审查与验收

DOC_STATUS: ARCHIVED_READ_ONLY

审查基线为 `3005980a9a0d3a62a67f36dff389a3110868faa7`。本文逐项记录全部指南建议的实施、保留决定及可核验边界；最终清理、CI与交接终态在完成节单列。
逐项附录覆盖 93 个生产脚本、60 个测试脚本和 37 条原门禁；文件存在、实现完成、软件回归通过、真实求解器验收和科学资格分别判断。
原指南快照为130,715 B，SHA-256 `ED4DF125C891815E72EE351DF921FB3E3558CBB803803C809E4C0AF779396C60`。2026-10-29重新读取原Page后，仅以只读文件读取进行全文比较：Page正文95,458字符，本地95,459字符，差异仅本地末尾一个LF；没有执行指南文本。

## 指南主题决定与证明范围

以下是对建议的最终实施决定；分类、实现和最终软件／原生验收分别提供证据。具体93＋60文件及37路由逐项依据见附录。

| 主题 | 决定与理由 | 实现及可核验边界 |
|---|---|---|
| G1 | 必改：新增／修改测试自身必须执行，不能由 Core 名称推断覆盖 | 现 catalog test owner＋实际模块并入执行集；fixture/init/删除/未知扩大。真实临时 checkout 中注入失败测试，非 Core 与新增模块均使 L1 非零；修后再通过 |
| G2 | 采纳：默认 advisory 审计不影响退出码却重复全库 AST；硬检查仍保留 | audit 显式请求；scope／索引字节检查与保守扩大；测试验证暂存坏／工作树好仍拒绝及反方向。26.522883→9.822432 s 仅默认 advisory 边界 |
| G3 | 必改：统一终态摘要、原因及恢复命令；修复真实完成消费竞态 | 当前摘要保留选择、状态、时间、命令、队列与日志；ready 依赖以已消费 PASS 放行，L1 停未启动队列／L2 继续独立诊断；健康已启动任务自然收尾 |
| G4 | 采纳：先求 effective 执行集再决定依赖，窄 test-only 避免 broad route 吞并 | DOCUMENTATION_ONLY 取实际三阶段，未知与 FullScope 保守全量；L2 完整集保持，37 catalog 路由无新增／删除 |
| H1 | 原优化可选，选中后保护与等价验收必须完成 | 连续共享 guard 在同一复制 owner 交接验证事实；Windows保护探针及真实三工作点验证通过；逻辑 SHA 读量降低，不宣称 OS 物理 I/O 或大 PA 倍速 |
| H2 | 采纳 selector/consume 分工，保留真正消费验证 | selector 校验小 receipt、真正物化边界核 payload；三工作点势／mask／grid及原源不变，未取消独立后继消费验证 |
| H3 | 只消除同一 producer 边界的重复全文验证；保留不同消费边界 | 三个已用完整公共 publisher 的末尾重复 verifier 移除，narrow 结果检查保留；实际 IP／MR 外层发布已闭合，不从内部 helper 推断缺陷。300 mm 父输入身份缺口另作必改 |
| H4 | 采纳默认 metadata／显式 deep；合法恢复目录误拒为必修缺陷 | 默认零 PA payload 读，--verify-hashes 与窄 cache-entry 保留真实内容校验；合法 XOR recovery 由原 owner 校验身份，layout 投影严格树形。实际全根仍有旧 scratch 命名失败，未冒称全根 PASS |
| H5 | 保留现 Copy-VerifiedRunInput，额外 record-bound 层不采纳 | 已有源／目标验证与冻结执行；小输入收益未量化，新增同义证明机制有维护和身份交接成本。A078 真实父身份反例单独修复，不因保留 H5 掩盖缺口 |
| C1 | 采纳一次 by_run/by_path 索引，保留原锁与事务 | 80 runs／400 objects 受控锁占用333.910→14.9027 ms；相同路径只索引一次，实际删除与保护边界不缩减 |
| C2 | 必改：owner动作、partial结果与全入口耗时完整表达 | 原 reconcile 统一 owner_actions/owner_action_failures；八类动作与 partial 可诊断，某 owner 失败仍收集独立结果，容量达标不等于 closure complete |
| C3与自动闭环 | 必改已定位手工续步缺口，复用原 owner 接 fresh admission/reseal | 同 CLI 单次最终准入；压力只受保护维护一次并重新准入；已删除只重试 reseal，不重删。新 pin／lease／owner／inventory 变更仍拒绝 |
| R1 | 采纳每轮一份完整主机快照，保留各 family 创建身份判断 | 完整双臂源与18原始样本保全；单 worker +14.86%成本保留，4/8 worker采样减少63.28%/50.08%，不外推整轮调度 |
| 预算内并行与耗时分配 | 保留现中央正预算与可用非 heavy 路径；不无条件解除 heavy 互斥，不新建 LPT/aging 服务 | 现 case/batch owner 已有预算与完整合并；自扩张重任务仍独占。历史缺少同 workload／测试集／源码／环境绑定，耗时权重可能误导且增加加载／fixture成本；确定性回退是本轮明确决定 |
| A1 | 必改科学决策平行实现／缺失参数；不重构全部 PS | 电压、step floor、恢复预算和资格比较归既有 Python controller；PS 管实际执行、Save和恢复运输。原数值向量、完整投影、恢复调用及负例实测；新增启动／反馈成本明确披露 |
| A2 | 必改实际反向边，保留领域所有者 | 中性缓存常量、GUI保护、公共成功记录消费与纯场投影由唯一 owner 正向依赖；只切真实反向边，不将器件模型搬入 common 或全仓重写 DAG |
| D1与重复实现 | 删除无当前生命周期职责的实现，保留动态／正式入口及语义不同实现 | 两个无活动消费者模块及专属测试退出；历史 backfill 日常重复分支退役；MR图复用已有导出器。OA图的原子发布、生成Lua数据和正式 CLI 不因长度／静态无引用删除 |
| Agent完整执行与恢复合同 | 必改已复现的停写、发布及容量收尾缺口，沿原 package/session/journal/retention 权威 | 两个 OA 工作流消费同一内部 owner；unknown writer 不伪造完成，保留 checkpoint/writing 与原容量保护并禁止 retention/publish；该表不承诺 owner 退出后 FileShare 句柄继续存在，也不续活过期 lease。保留原异常与secondary。真实P1部分构建、P2 prepared发布故障、P3恢复和P4零原生重分析分别提供证据 |
| GUI/CAD范围 | GUI依赖截图的验收按用户明确取消；CAD不适用本轮几何零改动 | 原GUI failed/unknown保留，不授予新GUI等价或Formal资格；取消专用新producer，不保留为后续待办。此前真实求解、恢复和软件验证不因此改写 |

## 架构收益与新增成本

本轮接受的结构变化以现有职责归属为依据。缓存角色与目录名从布局 CLI 移到中性合同，账本、历史校准和布局验证消费同一份常量；旧定义已删除。
GUI 源保护从退役 CLI 私有投影移到现有两个 owner 共同消费的窄模块，移除跨调用缓存，当前判断读取当前收据。
两者改变依赖方向，没有增加新的缓存或容量账本。

运行适配器由设计候选和径向压缩两个已有科学工作流调用。它复用 run package、容量 session、retention、终态 journal 和受管进程 API，
让科学实现提交 summary 与输出事实，由原生命周期权威完成发布和恢复。两个消费者属于同一个 OA-TOF 项目，不将其描述为两项目验证。
独立审查确认没有未调用辅助函数；随后移除未使用的 RepoRoot 参数和 preparedWait 局部变量，原 16 项生命周期回归在 139.211 s 内全部通过。
必要的 writer、租约与 journal 检查保留，因为真实故障链已经出现“求解结束但发布未闭合”的情形。

删除无活动消费者的 native_fast_adjust_operating_pa_cache、spatial_registration 及其专属测试，保留实际使用的 operating_pa_cache、rigid_transform 与 resolve_connection。
退出历史 backfill 的重复日常维护分支，保留历史迁移用途；两个 MR 图像输出改用已有公共导出器。
不因文件长度拆分领域算法，不为三个短数值转换器建立公共 API，不迁移具有不同发布合同的 OA 图像输出。
没有另建按历史时长调度的服务：现有耗时记录尚不能可靠绑定工作负载、测试集合、源码和环境，预算准入与确定性顺序继续生效。

生产代码量并未下降。最终代码提交181e4119的官方CLOC为total +12,020、production +4,452（约+1.90%）、tests +7,568；相对0f1仅两个测试文件净增4行code，没有生产变更。
新增生产代码主要承担已经复现的执行、停写、发布和恢复边界，新增测试覆盖这些真实失败；具体语言与过滤口径见后表。
这些成本不能用“测试更多”直接抵销；最终接受仍要求完整门禁与实际恢复链通过。

## D1 正文具名候选补充

以下候选不全部落在153份长文件附录中，单列最终决定，避免将长度清单误当指南正文全部范围。

| 原指南候选 | 最终决定与可核验依据 |
|---|---|
| Confirm-OpenPaStreamSha256、Remove-PrivatePaFamilyDirectory | 从 common/simion/short_pa_path_support.ps1 删除无活动调用／测试／公开文档消费者的两个函数；实际复制、guard及受管清理入口保留。源码差异有明确删除，活动源码检索无残留，未建立永久兼容别名 |
| Test-PathPrefix | 从 common/verify_changed.ps1 删除未调用私有 helper；路径路由沿现 catalog 与公共选择机制，实际入口测试验证选择与失败传播 |
| Remove-NativeCorridorRuntimeSession | 从 MR native_corridor_runtime_support.ps1 删除未调用函数；实际 Suspend／公共 owner 收尾路径保留，没有删除有效生命周期能力 |
| native_fast_adjust_operating_pa_cache.py、spatial_registration.py | 删除无当前 adopter 的未接入公共包装及专属测试，更新说明；现已使用的 native_fast_adjust_runtime_support、component_focus_pa_cache、rigid_transform、resolve_connection 保留，不能混同合同 |
| finite_interval_design_compiler.py | 保留公共物理权威和实际 tests/frontend_fixtures 消费（integrations/tests/frontend_fixtures.py:21）；仅从 runtime_dependencies.json 删除 local/cooled_frontend 未使用的冻结依赖，不搬公式进测试、不伪造生产消费者 |
| paper1_j2_candidate_pool.py、paper1_j2_real_field_sensitivity.py | 保留本项目 Paper 1 J2 研究准备API及专属纯分析测试；analysis/README.md:105明确owner、预注册pilot、无活动生产workflow、使用/退出条件；灵敏度模块孤立main及专用I/O imports删除。没有新造CLI，也不把本次指南任务变成J2真实研究 |
| standalone_field_bank、cooled_frontend.analyze、local_frontend.replay、paired_accelerator_pulse/static_field运行模块 | 保留实际内嵌Python／importlib／PowerShell字符串消费者。可核验入口分别在 local_frontend_field_support.ps1:219、cooled_frontend/execute.ps1:266/477、frontend_flight_support.ps1:232/253/269及paired两个execute.ps1:37/39。Python静态import图不构成删除依据 |

三个MR有限数值转换器确实同义；本轮不抽新helper，是因为短重复尚无真实错误或可测收益，新增API依赖与迁移成本不合算。它们与 strict_json.finite_real 的字符串接受／错误语义不同，不能机械替换。EI/EG短parser各有物理owner，约15行重复不足以证明共用utils层的净收益。两个MR图像薄封装已改用现有export_figures；OA图具有不同原子写入/回滚合同，保留。重复_PhaseTimings随历史backfill日常分支退出而消除，不新建遥测框架。

门禁小清理逐项决定：MR 对纯 Lua 目录的空 Python discover 已退出，三项 Lua 回归保留；统一单组调度后每个根入口只预热一次 Matplotlib。integrations wrapper 的 Ruff、MR wrapper 的 registry及 RF 静态树解析仍保留：独立直接入口需要其完整校验，本轮未建立跨 wrapper 的 pass-token／缓存协议，不将它们概括为已经全部消重。

## 实测收益与边界

| 对象 | 基线／对照 | 本轮观测 | 可以支持的结论 |
|---|---|---|---|
| G2 第一波默认 advisory，同语料 process-wall 中位数 | 26.522883 s | 9.822432 s | 默认退出消费者 audit（1→0）；完整硬检查不变，显式完整 audit 的 2,189 条记录相同。不是后续 scoped hard checks 的计时 |
| C1 80 runs／400 objects fixture | 锁占用 333.910 ms | 14.9027 ms | 同一 fixture 的锁占用减少；不外推为真实容量维护总耗时 |
| C3 同 Python 热进程 fixture | 18.5576 ms | 10.7795 ms | 仅同一热进程 fixture 改善，不是完整 CLI 启动墙钟 |
| R1 单次采样，1 worker | 261.9704 ms | 267.4477 ms | 中位数约增加 2.09%，无单 worker 加速 |
| R1 单次采样，4 workers | 962.1824 ms | 658.2779 ms | 三组交替对照的中位数约减少 31.58% |
| R1 单次采样，8 workers | 1,730.3419 ms | 1,122.3315 ms | 三组交替对照的中位数约减少 35.14%；只测采样，不含启动、等待与输出 |
| R1 冻结双臂重测，1 worker | 397.6261 ms | 456.7082 ms | 增加 14.86%，单 worker 未改善 |
| R1 冻结双臂重测，4 workers | 2,787.6528 ms | 1,023.5216 ms | 三对中位数减少 63.28%，只限采样边界 |
| R1 冻结双臂重测，8 workers | 4,766.7381 ms | 2,379.6709 ms | 三对中位数减少 50.08%，不外推整轮调度 |
| H1 8,388,645 B 合成输入 | 41,943,225 B 逻辑 SHA 读取 | 16,777,290 B | 相同输入的 SHA 遍历由 5 次降为 2 次；不含复制／native 读取，也不是 OS 实际磁盘吞吐 |
| H2 18 B 合成载荷，N=5／6 | 23／27 次逻辑 SHA 读取，414／486 B | 10／12 次，180／216 B | 不含复制／native 读取；selector 仍校验 1 次小 receipt，不外推 GB 性能 |
| H4 16 MiB 本地输入、7 对 | deep 0.0388656 s／16 MiB | metadata 0.0020546 s／0 payload B | 默认范围变化，显式 deep 仍读全量且能拒绝同大小改写 |

R1 实际八 worker 调度整轮为 57.0983365 s，其中一次 52.342612 s 间隔没有完整分段观测，不能归因于 sleep，也不声称整轮加速。
R1 最终重测已保全两臂完整源码：BASE 为原 80,292 B 混合 WORKTREE 快照（不是 Git 3005980），NEW 为当前 82,265 B、SHA 423D4C42…7473。18 样本的交替顺序／warmup／采样边界与原实验相同，6 类完整返回字典相等，8 个睡眠 worker 原 handle 自然退出 0，资源同 token released。原先历史 NEW 整源码未找到精确副本，原 raw／方法仍保留并披露限制，不以本轮源码冒充。最终重测采样合计 37.6740721 s，外层 127.286349 s 含准入等待及其他未分段开销；L2 同时运行，背景不同，不把新旧实验绝对时长差外推为产品整体收益。
H1/H2 真实小 PA 验收已独立通过：`20261029_062052__test__simion__h1-h2-three-workpoints`，BASE 五文件固定为 `ad6d7577bf3cce6f218fb6a96f2e65869358ba2d` 原字节，NEW 为本轮候选；不是把这组 BASE 默认为 3005980。
19 次实际 SIMION CLI exit 0，完整 manifest 验证 65 outputs。
三工作点各 343 个唯一节点的 potential/mask/grid 和两采样点 BASE/NEW 完全一致，60 次保护探针全部拒绝；源即时及延迟 1.5 s 的身份不变。
H1 实测 SHA 读量 5 次／14,000 B→2 次／5,600 B；H2 selector＋compose 为 14 次／39,200 B→4 次／11,200 B，小 receipt 两臂均 1 次／1,050 B。
组合 wall 5.2496865→3.6012297 s，仅一组 BASE 先 NEW 后，NEW 多 18 次探针且 L2 同时运行，不作为加速证据。
SIMION 原始日志存在尺寸小于 11 的精度警告；这只证明小 PA 传输／代数等价及保护，不证明场精度、大 PA 吞吐、Fly/GUI 或物理资格。
host 同 token released、容量 lease 清除，ready/light evidence 707,213 B 与实际相等；compact 已移除 14 个可重建 PA／39,340 B。

A1 将科学反馈决策交给已有 Python 权威，PowerShell 保留 I/O、Save 与恢复时序，收益是删除平行科学实现。
这一选择有生产运输成本：已测单次完整反馈中位数约 0.8906437 s；一个恢复夹具的控制请求数由 6 增至 13。
这些是反馈／夹具边界的观测，不是求解器总耗时，也不构成提速声明。本轮不为此新增驻留进程或另一套决策实现。

## 已执行的容量与历史整理

原 1FF 退役 transaction 的必要证据迁入具名 instrument_assembly run，原始 SHA 不变，新增元数据净成本 11,827 B。
四个公共 transaction 的实际占用校准共增加台账 1,808,029,364 B，其中 B85 build-scratch 漏记 1,808,018,320 B。
这是恢复账本真实性，未释放这些字节。校准 run 共 10 文件、137,569 B，完整 manifest 已通过；原 transaction 和其他 ledger 字段不变。
11 个已确认退役、无活动消费者的空暂存目录由现有锁保护下非递归移除，释放逻辑字节 0；不计入重型载荷释放收益。

完整元数据布局复验在 L1 终态后已越过 execution aliases，实际停于 B85 非空 build-scratch。
原 owner、冻结输入、消费者、pin/lease 和既有取消入口已完成只读审核；精确处置方案只移除 9 个可重建 scratch 文件，保留原 pinned run 和原事务原文。
取消会令该旧 key 不再允许普通续建。首次自动审批认为站立授权不足，拒绝执行；随后用户在本对话明确批准该精确取消和删除，才通过同一公共入口执行。
实际移除 9 个 scratch 文件／1,808,018,320 个逻辑字节，原 transaction 的 18,270 B 原字节在 inputs/journal 保真，当前退役 transaction 61,494 B 与 ready/light ledger 相等。
原 producer 的 174 文件元数据／文件身份及原 ledger/pin 不变，172 个非 PA 文件 SHA 再核一致，两个 PA 不新增读取。
新证据 run `20261029_053251__analysis__python__b85-cancellation-evidence` 共 13 文件／257,610 B、完整 manifest 7 outputs 通过；host 同 token released、capacity lease 已清除。
worker 9.2744332 s、root 全程 28.2731357 s 是不同边界；卷 free 从 623,259,312,128 增至 625,066,860,544 B，增加 1,807,548,416 B。
卷变化比逻辑删除量少 469,904 B，期间有新证据与 journal／其他活动，不能精确归因这个差额。只证明精确取消及证据保全，不证明旧 key 可普通续建或数值已重建。

用户取消截图依赖GUI验收后，原GUI r3专用载荷经公共owner只读计划确认无活动消费者／容量覆盖／current GUI源保护；原pin保持至公共处置。首次自动审批认为取消验收不等同于删除载荷授权，拒绝执行，未写入或删除；用户随后明确批准该精确38文件／1,275,410,616 B范围，才由原 invoke_solver_review_retirement.ps1 owner-abandonment入口执行。wrapper exit 0，实际移除字节与批准一致，外层64.6642404 s，该GATE预约实际 released（wrapper未打印token字符串，不虚构精确token ID）。独立公共退休验证通过：392个原小文件共3,631,618 B逐bytes/SHA不变；唯一新增收据476,821 B，实际393文件／4,108,439 B与light_evidence/ready/pin=false账本相同，pin由原owner正常收尾解除。扣除新收据，净逻辑减少1,274,933,795 B；未测卷free变化。原failed状态、原三件套身份、冻结输入、IOB/GEM/代码/N100/日志不改写，P1–P4及published cache不动。原IOB须重建私有PA后才可再用；原manifest只描述退休前历史，后续按公共retirement --verify核验，不冒称完整磁盘／GUI PASS。

## 整轮验收记录

真实恢复 P1 已完成受控失败并独立验收：`20261029_040100__test__simion__radial-handoff-p1`。
原 family Refine 成功且有 10 条完成记录，前 8 个 standalone 导出成功，最后 response9 因本次自有空目录自然保存失败；CLI exit 1、原 run failed 均保留。
事务保持 building，完整构建 operation 绑定、inventory 与 generation 为空，不将前 8 个导出视为完整恢复资格。
manifest 完整验证 78 outputs、13 个 tracked operation 已退出、host 同 token released、容量 lease 消失；run ready/pinned 为 3,041,934 B。
partial transaction 的 20 文件／2,138,465,530 B 已由正常 owner 自动记账且与实际相等，未手工校准。
注入的自有空目录只在原 owner 停写封存后精确移除，原 Result/manifest/transaction 快照身份不变；P2 必须整体重建该组件。
driver 102.3796857 s、managed CLI 99.9827573 s、owner 94.3650845 s、内部 Refine 34.43 s 是不同计时边界，不能相加或与完整 Fly 一轮作速度比较。
外层完整 argv 可由冻结 builder/resolved/alias 重建，内部 refine argv 在原日志保留；不将重建命令称为原始 argv 日志。

| 轮次 | 范围 | 结果 | 摘要墙钟 |
|---|---|---|---:|
| 第一波 L1 | 18 阶段；2,167 tests／2 skip | PASS | 1,941.079916 s |
| 第一波 L2 | 37 阶段；5,431 tests／20 skip | PASS | 2,374.088572 s |
| 最终候选 L1 r1 | 受管文本字节发现 CRLF，后续阻断 | FAIL | 约 8.86 s |
| 最终候选 L1 r2 | 23 适用阶段；4 阶段失败 | FAIL | 1,823.992282 s |
| 最终候选 L1 r3 | 23 适用阶段；21 PASS、2 FAIL | FAIL | 1,849.876001 s |
| 最终候选 L1 r4 | 23/23 适用阶段；16 个 unittest runner 共报告 4,212 次测试执行／14 skip | PASS | 1,819.666241 s |
| 最终候选 L1 r5 | 23/23 适用阶段；4,255 次 unittest／14 skip；固定 7DD 源码及两模块 focused 37 项夹具修复已含于本轮 | PASS | 1,928.100826 s |
| 最终候选 L2 r1 | 36/37 阶段；MR 全量 1,742 tests 中 9 errors／12 skip | FAIL | 2,202.506102 s |
| 最终候选 L2 r2 | 36/37 阶段；5,675 tests／20 skip／1 failure；原始调度完成消费竞态 | FAIL | 2,423.781944 s |
| 最终候选 L1 r6 | 含最终 G3/layout 窄修及平台名称文案；运行中宿主再次重启，原摘要未取得终态 | INTERRUPTED（外部） | 无完整墙钟终态，不能作性能比较 |
| 最终候选 L1 r7 | 相同冻结源；系统随后再次重启至本地10:27:13，原进程已不存在 | INTERRUPTED（外部） | 无完整墙钟终态，不能作性能比较 |
| 最终候选 L1 r8 | 最终 G3/layout 源码；23/23 PASS，16 个顶层 unittest runner 共4,261次测试执行／14 skip／0 failures／0 errors | PASS | 2,023.959472 s |
| 最终候选 L2 r3 | 完整37/37 PASS，28个顶层unittest runner共5,681次执行／20 skip／0 failures／0 errors | PASS | 2,329.907340 s |
| PID测试修正后的改动L1 | 仅两个测试文件触发6/6阶段PASS；2个顶层unittest runner共1,220次执行／7 skip／0 failures／0 errors | PASS | 1,686.655631 s |
| PID测试修正后的完整L2 r4 | 新181e输入；原摘要33 PASS／4 RUNNING，重启前integration日志已有两个具名FAIL；整轮未取得终态 | 原RUNNING保留；非整轮PASS/FAIL | finished/elapsed为null，不补造墙钟 |
| 181e push CI 40822854689 | changed-scope 7阶段PASS；1,220次测试执行／27 skip；repository_integration按push策略skipped | completed/success | gate step 1,508 s；不是完整L2 |

r3 OA 的 8 个失败／错误共享同一原因：新增容量运行配置后，现有同步器未刷新 campaign 的 runtime 权威绑定。
已在原 bindings 加入 runtime，由原 --write 生成唯一 SHA 字段变化；2 个新增回归先失败，修后两个完整模块 24 tests／2.538 s 通过。
strict validator、retired 状态、执行授权及科学输入不变。
r3 MR 的单个错误是五场景实际反馈测试超过旧 40 s 时限；原方法独立执行 32.938 s 通过，不能据此认为原生科学运行有故障。
在保留全部反馈／校验计数和单场景 40 s 上限的前提下拆分执行，改后测试 39.392 s 通过；五场景分别 14.749712、5.773416、14.116129、3.015640、1.718176 s。
仍实际执行 29 次 Python 物理反馈、7 次 Python stencil plan，共 36 次真实 Python 调用；另有 30 次完整 verifier 的参数／次数 stub，不冒称完整 manifest 校验实跑。
原恢复、电压与证据小文件读取断言保留。增加四次 PowerShell 启动隔离成本，不声称加速；后续 L1 r8 与 L2 r3 均已通过，按实际终态另列。

附录 A078 另确认输入身份缺口：300 mm Candidate 只核父 selected result，却读取 live reference，且未核传入 configuration 的父输入记录。
三项专属回归在修复前共 0.800 s 全部失败；相同父 manifest/selected 原字节下，临时 live reference mass 从 100 改到 200 会改变 Candidate，错 configuration 与父冻结 reference 漂移也没有被旧实现拒绝。
保留该正式 CLI；输入绑定修复与直接回归为必改，publisher 去重仍为可选。修后 8 项专属测试在 4.037 s 通过；20 项相邻测试在 1.790 s 完成，其中 1 项因未配置历史 T5 receipt 明确 skip。
两个编译入口复用同一父输入加载边界；独立审查确认 base/grid 科学计算体及原 publisher、CLI AST 不变，且实际历史父运行的两个小输入记录适用。
新 L1 r4 在冻结源码、同一中央资源账本下完整通过；随后完整 L2 的 MR 全量集合暴露 9 个测试准备错误。已修复实际 mock owner／finally AST 夹具，原 37 项 focused 测试由 9 errors 改为全部通过，耗时 18.091 s；未放宽科学断言。
真实 P2 还暴露发布失败前 key_root/recovery 的 6,110,431 B 未登记；仅 transaction/run 的实际字节已经正确登记，不能将这解释为全部外部缓存容量闭合。
现有 cache owner 已补齐写入前登记、独立异常实际字节校准和验证后的 owner 交接；复用原写入状态、journal 与普通重放入口，没有增加第二账本或恢复服务。136 项回归全部通过（36.641 s），独立审查通过。原 P1/P2 记录未回写。

修后真实 P3 `20261029_040300__test__simion__radial-handoff-p3` 成功，driver 252.1206096 s、managed 252.1120554 s、owner 247.7206671 s。
没有重做 heavy response Refine；28 次 response append、6 条 private controller/ground Refine 完成记录。五次实际 N100 Fly 均 exit 0、100 splats、quality 8，CSV SHA 与全部 canonical peak metrics 与原基准／两次 warm 运行一致。
86 条 operation observation 闭合，6 个非继承 host release 均为同 token 的实际 released；容量 lease、执行 alias 已清除。两个活动 published cache 分别为 1,238,072,039／128,105,715 B，run 为 1,280,287,672 B，均与对应活动 ledger 相等；原遗漏的 recovery 范围已包含在 reflector key 中。
这里不把 retired transaction 的 bytes 当作当前盘占：其历史值由既有退役语义保留，两个控制 journal 实际共 32,608 B，单独披露，不声称其历史字节被释放。

P4 `20261029_073507__test__simion__radial-p4-reanalysis` 以 P3 冻结父运行重分析，driver 24.4479942 s、owner 21.080837 s；独立 public manifest 全量验证通过。
实际 0 Build／0 Fly／0 Refine，五模式在同一个 frozen actualworker 内重新分析；writer 的 operations/resource_releases 均为空，没有伪造五个独立 bridge 或 release。
五份 CSV、全部 canonical peak metrics、13 项科学输入及 143 项源码身份与 P3 一致；父 492 个文件的元数据及 454 个非 PA 文件内容指纹前后相等，38 个 PA 仅 stat，没有额外重哈希。
新 run 为 194 文件／3,270,937 B，与 ready ledger 一致，受管 worker／launcher 退出、双流和容量闭合。以上只证明恢复、复用和重分析链，不晋升 Candidate/Formal。

COMSOL 真实连接生命周期 `20261029_075812__test__comsol__connection-lifecycle-smoke` 已独立验收：完整 manifest 12 outputs，21 个冻结源文件逐 SHA 一致；wrapper、实际 launcher、managed worker／launcher 与双流正常退出，非继承同 token released、容量 lease 清除。run 36 文件／421,432 B 与 ready/light ledger 一致。callback 225.407 s、owner 320.9425814 s 是不同边界，后者含准入等待；最终报告仅 `STATUS=PASS`，不从被覆盖文本推导版本号或模型计数。未创建／加载模型、Study 或 Compute，不提供物理或 GUI 资格。

GUI 请求首尝试在创建 run 前因错误保护 TEMP 路径拒绝；第二次因一次性协调脚本遗漏已有 Python 解释器环境变量失败，36.3076727 s 后正常失败封存。二者只修临时验收作者，不修改正式容量或 PA helper。第三次 `20261029_083000__test__simion__radial-p3-gui-r3` 已完成真实 hit-only 构建与 N100 CLI Fly（2.3237499 s）；CSV 仅 Mode 标签不同，其余 16 字段与 P3 actual 相等，诊断的科学字段相等。图像捕获对 SIMION 和空白记事本均超时；运行时重置、精确辅助进程重启及前台复测没有恢复，用户禁用 Oray 并重启后，系统确认 CM_PROB_DISABLED、NVIDIA 正常；空白记事本截图仍失败，用户确认退出向日葵后仍失败，根因未定，不能归因驱动或 VPN。GUI 八项检查均记 unknown，未伪造 PASS。用户正常确认退出后，GUI exit 0、原文件身份保持，owner 以缺少截图验收失败封存、资源与容量闭合，无 secondary error。owner 2,080.1087465 s 含 GUI 等待及环境排障，不作构建性能比较。用户随后明确取消截图故障修复及由此无法完成的任务，因此本轮 GUI 验收及专用新 run 准备取消，按用户取消记录，不改写为通过；本轮不据此授予 GUI 等价或新正式资格。

这些轮次的范围、测试数与失败状态不同，不能将摘要时长的下降写成整体性能收益。

L1 r8 外层实际进程另计2,026.1201845 s；不是摘要墙钟。common 864 tests／1 skip的runner body为1,987.496 s、stage1,992.802637 s；integration614 tests为1,880.577 s；MR726 tests／6 skip为1,337.292 s。MR与quad本轮是Core加实际改动模块，不冒充L2全Static；没有unittest汇总的阶段记N/A而非0 tests。

本轮采用冻结的现有工作树，未使用独立checkout：L1 r8按preflight中记录的受版本控制及非忽略文件清单算法，运行前后2,288个文件／202,011,156 B、整体SHA `8e9ab984198a6cee7f56e12f3c7896606d3f52cee9ae039018e2d530dfa7a05b`完全相同，执行期间禁止源码／文档编辑。它针对原指南“避免门禁中途混入编辑”的目的，是有证据的方法替代；两次指纹本身不是对期间从未改写后恢复的形式化证明。该方法也不授予干净checkout对未跟踪／忽略文件、本机依赖或外部artifacts的隔离保证。最终提交的Git blob绑定见下节；新181e CI已取得success，另列其精确范围，不拿旧HEAD的CI绿灯代替。L1结束后仅更新common R1说明与项目GUI取消事实，并通过StructureOnly（306md／164history／9authority、0errors）；L2已对更新后的文档及同一代码重新冻结并通过，实际终态见后节。


## 已知关键阶段耗时参照

以下均为unittest测试体秒数，不能与stage、process或整轮摘要混加。历史原始出处见[第一波报告的已知历史记录](20261028__system-guide-first-wave.md)，当前记录见已保全L1 r8／L2 r3提取表。共同机器、并发背景、源码和测试集合并未受控保持一致，因此只提供参照，不把时差归因于这次改造。

| 阶段 | 更早已知记录：tests／skip；body秒 | 第一波L2：tests／skip；body秒 | 当前L2 r3：tests／skip；body秒 |
|---|---|---|---|
| common | 778／1；293.799（单阶段PASS） | 803／1；1799.582 | 864／1；1973.075 |
| instrument assembly | 605／0；1737.629（该整轮L2退出1） | 605／0；1977.008 | 614／0；1911.296 |
| MR full Static | 1693／12；1818.682（该整轮L2退出1） | 1693／12；2101.692 | 1742／12；2220.443 |
| quad full Static | 224／0；231.109（定向PASS） | 224／0；325.790 | 226／0；292.375 |

另有MR Core历史42项／172.135 s，第一波L1同42项／227.807 s；当前L1是Core加被改模块、726项／6skip、1337.292 s，范围不同。common和MR的当前测试体成本高于第一波，不能只选择降低的阶段宣称收益；完整门禁与新增真实故障回归的成本均保留。科学反馈新增Python启动成本及生产代码增长已另列，不因总体摘要接近而隐去。

## 官方 CLOC：最终提交身份

`3005980a9a0d3a62a67f36dff389a3110868faa7` → `181e411950bb0f1da8c5528ecfeda95641932204`；官方CLOC 2.10；统计时间`2026-10-29T05:20:49.6580348+00:00`。
公共入口`common/report_cloc_delta.ps1 -Base 3005980a9a0d3a62a67f36dff389a3110868faa7 -Current 181e411950bb0f1da8c5528ecfeda95641932204`，固定官方工具、C locale。原执行exit 0，中央GATE实际release的token为`ef0b4a0313004fa4ac0552939e7fde23`；计量时WORKTREE_DIRTY=false、tracked dirty=0、untracked=0。这是已提交181e测试修正后的计数，不把旧0f1结果冒称当前最终输入。

| 类别／语言 | files 基线→结果（增量） | blank | comment | code |
|---|---:|---:|---:|---:|
| total／JSON | 252 → 252 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 34645 → 34753 (+108) |
| total／Lua | 95 → 96 (+1) | 361 → 361 (+0) | 712 → 715 (+3) | 11050 → 11122 (+72) |
| total／MATLAB | 125 → 125 (+0) | 960 → 960 (+0) | 1964 → 1964 (+0) | 14752 → 14752 (+0) |
| total／PowerShell | 142 → 144 (+2) | 1022 → 1033 (+11) | 950 → 999 (+49) | 38213 → 40164 (+1951) |
| total／Python | 834 → 841 (+7) | 23441 → 24069 (+628) | 20841 → 23513 (+2672) | 269971 → 279842 (+9871) |
| total／SIMION GEM | 10 → 10 (+0) | 26 → 26 (+0) | 54 → 54 (+0) | 214 → 214 (+0) |
| total／TOML | 1 → 1 (+0) | 4 → 4 (+0) | 0 → 0 (+0) | 24 → 24 (+0) |
| total／YAML | 2 → 2 (+0) | 4 → 4 (+0) | 2 → 2 (+0) | 140 → 158 (+18) |
| total／SUM | 1461 → 1471 (+10) | 25818 → 26457 (+639) | 24523 → 27247 (+2724) | 369009 → 381029 (+12020) |
| production／JSON | 251 → 251 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 34511 → 34619 (+108) |
| production／Lua | 77 → 78 (+1) | 297 → 297 (+0) | 611 → 614 (+3) | 9295 → 9367 (+72) |
| production／MATLAB | 77 → 77 (+0) | 484 → 484 (+0) | 1392 → 1392 (+0) | 9799 → 9799 (+0) |
| production／PowerShell | 134 → 136 (+2) | 964 → 974 (+10) | 917 → 966 (+49) | 36563 → 38488 (+1925) |
| production／Python | 419 → 420 (+1) | 13065 → 13195 (+130) | 9077 → 9261 (+184) | 143530 → 145859 (+2329) |
| production／SIMION GEM | 10 → 10 (+0) | 26 → 26 (+0) | 54 → 54 (+0) | 214 → 214 (+0) |
| production／TOML | 1 → 1 (+0) | 4 → 4 (+0) | 0 → 0 (+0) | 24 → 24 (+0) |
| production／YAML | 2 → 2 (+0) | 4 → 4 (+0) | 2 → 2 (+0) | 140 → 158 (+18) |
| production／SUM | 971 → 975 (+4) | 14844 → 14984 (+140) | 12053 → 12289 (+236) | 234076 → 238528 (+4452) |
| tests／JSON | 1 → 1 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 134 → 134 (+0) |
| tests／Lua | 18 → 18 (+0) | 64 → 64 (+0) | 101 → 101 (+0) | 1755 → 1755 (+0) |
| tests／MATLAB | 48 → 48 (+0) | 476 → 476 (+0) | 572 → 572 (+0) | 4953 → 4953 (+0) |
| tests／PowerShell | 8 → 8 (+0) | 58 → 59 (+1) | 33 → 33 (+0) | 1650 → 1676 (+26) |
| tests／Python | 415 → 421 (+6) | 10376 → 10874 (+498) | 11764 → 14252 (+2488) | 126441 → 133983 (+7542) |
| tests／SUM | 490 → 496 (+6) | 10974 → 11473 (+499) | 12470 → 14958 (+2488) | 134933 → 142501 (+7568) |
| unclassified／SUM | 0 → 0 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 0 → 0 (+0) |

完整过滤口径：`extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked`。

分类器SHA-256：`d3365e7f02e66a775ec8eb3b12fb7b7bfa1bf34b87009543768a8e36bb4db749`；语言定义SHA-256：`985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6`。

`INPUT_IDENTITY SNAPSHOT=baseline FILES=1461 SHA256=2eb9ba02f1e90fef5430d4db55608a3786dbdf7f3b824c00938b893d9fa310c9`

`INPUT_IDENTITY SNAPSHOT=result FILES=1471 SHA256=d668c3a12e40c53c219976941c6d6a47fe7cedb80d2833d12f92614fe1bd90ac`

新原始完整输出[cloc_pid_fix_exact_commit.txt](20261029__system-guide-complete-review/cloc_pid_fix_exact_commit.txt)（14283 B，SHA-256 `8b4b31eebae85d5e05973da1900ba144248c29a16706a638ce6f1671500d3898`）及[实际release记录](20261029__system-guide-complete-review/cloc_pid_fix_exact_commit_release.txt)已逐字节保全到本报告同名载荷目录；不改写已冻结69文件包。
25行由新原文自动转写：每行files/blank/comment/code均核base+delta=result；各语言之和等于类别SUM；逐语言及SUM均满足total=production+tests+unclassified，未分类始终0。
相对0f1提交，只有total/Python、total/SUM、tests/Python、tests/SUM的code结果及增量各加4；生产code/blank/comment/files及所有非code指标不变。生产总增量仍+4452，测试由+7564变为+7568，总量由+12016变为+12020。旧0f1完整输出与release仍留原69文件包，只作历史记录。

## 两处最终窄修与布局复核边界

L2 r2 唯一失败来自真实完成消费竞态：child 在 completion sweep 与第二次 HasExited 判断之间退出，依赖阶段在 predecessor PASS 尚未消费时被误报 BLOCKED。生产修复仅将 running 数量判断改用既有 Result 是否为空，不增加状态、重试或延时；3 项 focused／13 场景通过（34.892 s）。该修复后的 L1 r8、最终完整 L2 r3 均已通过；旧 L1 r5 的 PASS 不追认到新源码。

真实布局复验还发现，原布局验证器只允许 current_generation.json/generations，错误拒绝 cache owner 已验证的合法 XOR recovery。修复复用 owner 的身份与清单，只严格投影 recovery 目录形状；默认不额外哈希 PA／大 parity，current deep 仅验证一次，拒绝额外成员、casefold 冲突及 reparse。7 项 focused 在 6.514 s 通过，最终 Windows junction 四场景在 2.868 s 通过。

修后真实元数据扫描已越过整个 common 根与 PA cache/transactions，随后在项目旧 scratch 命名处失败。因此不声称整个 artifact 根布局通过。只读清单观察到153个旧不合规则目录，最近观察 mtime 为2026-10-26；没有消费者、归属或必要性证明，不据年龄删除、改名或放宽规则。此153目录与指南93生产＋60测试条目不是同一集合。它们按既有未知消费者保护保留，指南范围内实现与验收结论单独判断。

用户取消截图排障及截图依赖任务，属于明确调整验收范围。原生运行、软件门禁和实际恢复证据继续保留；GUI未验收的边界随最终报告保留，不通过弱化原GUI合同制造PASS。


## 完整L2 r3历史终态与源码边界

以下是181e测试修正之前、由0f1提交及既有精确格式变换绑定的完整L2历史记录；不追认为新181e原字节的整轮结果。新L2 r4原摘要未闭合且integration已观察到两个具名FAIL，不能以本节历史PASS替代；用户明确无需新增或重跑L2，后续仅核对既有失败证据及收尾，不把补跑列为待办。

L2 r3摘要区间2026-10-29T03:11:41.9180079Z至03:50:31.8240548Z，为2,329.907340 s；外层进程2,331.0514201 s，exit 0。37阶段全部PASS，28顶层runner实报5,681次测试执行／20skip／0failure／0error；不是跨runner去重方法数，也没有叠加嵌套夹具门禁。全37阶段/28runner的body、stage、process与queue时间和原始行号在原始提取表及replay保留；阶段并行，不能相加补造整轮墙钟。

运行前后2,288文件／202,011,899 B整体SHA均为4ecae61483f1984b428299d1d791715fc351e2f5fe505f99c13bf90101eb64b1。中央host sequence16722、records=[]；唯一既有MR来源保护mrtof-two-reference-detector-20261014-233947的commitment为0，不是门禁残留。原成功诊断由公共入口自动CLEANED，完整root replay保留。独立审查重新相加28个原始unittest汇总，与上述数字一致。

整轮之后索引检查另发现未跟踪新Python文件gui_source_protection.py的两个末尾空行及未发布归档正文的一条末尾空行。只移除这些LF，Python AST完全相等，2项直接共享合同回归在0.149 s通过，Ruff与活动文本差异检查通过。完整L1/L2使用修正前原字节，不伪称已对修正后原字节整轮重跑；这两处精确格式变换已纳入最终Git绑定，原始证明保存在验收证据包。

## 已提交代码与历史受测字节绑定

原九主题代码截至`0f1df0f9a02b05c09bc7999d50149012f1a4ad4f`已普通推送。当前最新代码提交为`181e411950bb0f1da8c5528ecfeda95641932204`，仅修两个测试的actual-worker身份断言，净增4行测试code；生产源码未改，已普通提交并推送。原来的连续OA恢复缺陷作为一个完整主题提交；命名、门禁、MR策略、组装DAG、父输入修复、无消费者退役、可选图导出及旧证据迁位分别审阅。

| 提交 | 主题 |
|---|---|
| `ef8d88e4` | docs: rename the platform in active project documentation |
| `55dc4a12` | fix: make scoped gates consume completed results before scheduling |
| `9bf9584b` | fix: close the OA execution and PA recovery lifecycle |
| `1854101e` | refactor: restore MR scientific decision and evidence ownership |
| `ef58e99c` | refactor: make single-reflection assembly dependencies directional |
| `630ec875` | fix: bind 300mm candidates to frozen parent inputs |
| `9170c15a` | refactor: retire unused wrappers and redundant dependency entries |
| `ef2a565b` | refactor: reuse the shared exporter for MR figures |
| `0f1df0f9` | docs: archive legacy common evidence under its owned history |
| `181e4119` | test: verify actual worker identity across Python launchers |

前九主题提交与各次普通push之前均已披露第一波L1/L2的1941.079916／2374.088572 s和当时2023.959472／2329.907340 s；181e测试修正提交另披露本次六阶段L1的1686.655631 s。各commit有实际验证、作用及限制正文，正常索引hook均通过。不同集合与背景的墙钟不构成受控整体提速证据。

对历史0f1 Git树2288文件逐blob与当时工作树核对：除了.gitattributes、.gitignore及既有四极official_fixed_100.ion三处CRLF→LF可逆规范文本差异，全部原字节相同。当时工作树202011990 B／SHA5edc284da79ad3c9c2b0c241ad689833a9a2c8acd22f242597c52efeba6b9fca；Git原字节202011814 B／SHAa4f3122a622e141ebef50c3eb3f0bcca5f334b01dbfd41991775f4ba47ab0bf0。精确还原两处末尾LF与下述Git属性变化后，完整重构L2的2288／202011899／4ecae614…64b1；未发现其他内容变化。三处换行与post-gate变换的逐文件bytes/SHA、算法及原验证方法均在正式证据包；本结论不把规范文本SHA冒充外部输入file SHA。

第九主题提交真实触发hook拒绝原始CRLF TXT；不能为通过检查而改写证据。沿[Git官方路径属性](https://git-scm.com/docs/gitattributes#_checking_whitespace_errors)，仅在既有根history TXT -text/-eol规则补-whitespace，继续由history清单复核完整bytes/SHA，活动源码、MD与其他history路径均不获新豁免。隔离Git四阶段实测0.494807 s：原规则同raw拒绝→新规则同raw接受→坏活动源码仍拒绝→修复源码完整检查通过；raw索引／工作树始终字节相同。hook未跳过，最终正常提交成功。该局部Git配置验收独立于前述完整软件回归，不声称完整L2包含后续属性变化。

R1三份受测源共119943 B已绑定0f1提交raw Git blobs，不再另存重复源码；混合WORKTREE BASE与原测量/方法保留。必要原始验收及测量文件正式清单见[系统指南验收证据](20261029__system-guide-validation-evidence.md)。

## 正式证据保全与一次性文件处置

必要小证据已由提交`3e7b80da`正式保全：[69份原字节验收清单](20261029__system-guide-validation-evidence.md)，共2,002,502 B；源、目标、索引Git blob的bytes/SHA逐项相等，独立审查无缺项或extra。文档StructureOnly与专属文档L1三阶段均通过，摘要25.404058 s；该快速路径不冒充完整软件回归。原运行、PA缓存及三件套仍由原owner保留，冻结历史不重写。

九个旧TEMP范围在必要raw提交后，通过正常审批、fresh正常用户CIM、无其他引用进程、无reparse、与独立预检精确库存匹配才删除。此前自动审批拒绝未绕过；新的恢复和保全证据经正常审批后完成精确清理。旧G2 corpus可从固定c946原字节重建，早期overlay和混合R1 BASE另存，不能混称全部Git恢复。

| 精确TEMP范围（共同父目录C:/Users/Liao/AppData/Local/Temp） | 文件数 | 删除逻辑bytes |
|---|---:|---:|
| `capacity-benchmark-845b54bcd8c945459710f76d3c271d96` | 1418 | 618333 |
| `codex_g2_pre_import_odsoiwu0` | 4 | 51117 |
| `scheduler-multibirth-candidate-86012fa4455941449d665f2b7e9b4721` | 4 | 93622 |
| `codex_rf_gate_contract_candidate_8iayfqoc` | 3 | 56166 |
| `codex_g2_final_benchmark_20261028` | 1459 | 22011642 |
| `codex_campaign_binding_red_0fec42ede6f8427f82fc206475590b09` | 2 | 8 |
| `capacity-pressure-baseline-1f3bd056a8cb4d4c8561dd7610d477d5` | 4 | 8532 |
| `codex_pa2d_toy_1c6e33c78bb64f3688ed5887428b38c0` | 5 | 22591 |
| `codex_guide_wave1_20261028_f773196bc812465eb95e29625b8210a6/capacity_host_release_probe.ps1` | 1 | 2655 |

合计2,900文件／22,864,666 B，核验及删除2.4718363 s；这是逻辑删除字节，不是实测卷free变化。原run、published cache、原pin/保护与中央账本不动。

两个R1目录也在必要raw、混合BASE和方法已保全，3份当前源已逐Git blob绑定之后删除；fresh CIM无其他引用、精确普通文件库存匹配。

| 精确TEMP目录 | 文件数 | 删除逻辑bytes |
|---|---:|---:|
| codex_r1_process_snapshot_20261029 | 12 | 123409 |
| codex_r1_remeasurement_20261029_423d4c42 | 20 | 229761 |

合计32文件／353,170 B，核验及删除0.417452 s；不把混合BASE误作3005980，不重复归档可从固定提交恢复的119,943 B当前源码。

原主TEMP及来源日志给出的旧门禁诊断均已实际清除；后续CI测试修复和新CI真实success已在后节分开记录；L2 r4原未闭合状态及其具名失败不被改写为通过。

## 逐项审查附录说明

来源为独立评审《mass_spectrometry 系统审查与修改指南｜3005980》（Page ID：page_4e30e6be7c308191b188c3625d498db3），
基线为 [3005980](https://github.com/Bibibabibobi96/mass_spectrometry/tree/3005980a9a0d3a62a67f36dff389a3110868faa7)。

以下依据五份逐项审查及 Agent 0 的优先级纠正合并：优先采用 disposition_strength、decision_strength、category，
再应用 priority_corrections；原宽泛 CHANGE_REQUIRED 不自动升级为必须拆分。每个文件 ID 和路径只列一次。
共 153 项（93 个 A 生产项、60 个 B 测试项），当前工作树 153 个原路径均存在且受 Git 跟踪；存在性只证明链接可定位，
不证明行为验收闭合。决定分布为 37 项限界必改、5 项保留且配套必测、52 项可选、59 项保留；无未决分类。
行号重新按当前源码定位，原审查 SHA 不作为本轮最终源码身份或执行证据。
MR、RF、OA、oaTOF、IP 和电子枪仅为对应项目路径的显示缩写，链接指向完整唯一路径。

“必改”只覆盖已定位错误、依赖或恢复边界；“可选”保留收益与迁移风险，未据文件长度采纳的拆分不是待完成事项。
右列主题表示本轮已形成的实现/配套回归包，不单独授予 PASS。软件执行、真实求解/GUI及最终全 L1/L2 的验收状态
统一见主报告。P1–P3 已完成真实 PA producer handoff，P4 已完成显式冻结父重分析；GUI 验收及仅为其准备的新 producer 已按用户指令取消，既有 GUI failed/unknown 记录保留，不赋予 GUI 等价或新正式资格。最终L1 r8与L2 r3已取得实际PASS终态；后续格式／Git属性补充验收与字节差异见主报告。

## 附录一：153 个长脚本逐项决定

| ID | 唯一文件 | 决定、收益与代价 | 当前可核验位置 | 实施主题／保留决定 |
|---|---|---|---|---|
| A001 | [common/analysis/peak_metrics.py](../../common/analysis/peak_metrics.py) | 保留：峰形、宽度、配对和bootstrap属于同一数值权威；未发现由804行本身造成的合同缺口。<br>收益：保持单位、配对ID与统计语义一致，避免复制数学实现；代价/风险：不迁移；拆分会增加导入与数值回归面而没有实测收益。 | [AnalysisSettings](../../common/analysis/peak_metrics.py)（L22）<br>[test_defaults_and_valid_boundary_settings](../../common/analysis/test_peak_metrics.py)（L15） | 保留决定；无新增实现要求 |
| A002 | [common/contracts/capacity_ledger.py](../../common/contracts/capacity_ledger.py) | 必改（限界）：窄改底层反向导入 CLI 的共享角色常量；保留同一 ledger 事务，不按行数拆账本。<br>收益：消除已定位职责或恢复缺口；代价/风险：不因1578行拆账本；提函数须有独立职责/测试收益。 | [INTEGRATION_CACHE_ROLES](../../common/contracts/artifact_cache_contract.py)（L7）<br>[ledger 正向导入共享常量](../../common/contracts/capacity_ledger.py)（L1085）<br>[test_owner_queries_do_not_import_command_entrypoints](../../common/contracts/test_shared_artifact_contracts.py)（L20） | A2／Agent 0 |
| A003 | [common/contracts/capacity_protection.py](../../common/contracts/capacity_protection.py) | 保留：现有锁内lease/pin/路径保护符合边界。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：不扩展第二租约系统。 | [capacity_decision_lock](../../common/contracts/capacity_protection.py)（L47） | 保留决定；无新增实现要求 |
| A004 | [common/contracts/legacy_capacity_backfill.py](../../common/contracts/legacy_capacity_backfill.py) | 必改（限界）：重复 daily startup/maintenance、ledger I/O 与计时分支已退出，_PhaseTimings 随日常单一 owner 收敛；历史 backfill/replay 仍保留<br>收益：去除两套日常 authority 和重复计时对象，测试直达实际 reconcile API；代价/风险：未抽象新计时框架；需维持 historical apply/replay 与 daily 请求拒绝的独立负例 | [plan](../../common/contracts/legacy_capacity_backfill.py)（L975）<br>[test_legacy_owner_rejects_daily_requests_without_discovery](../../common/contracts/test_reconcile_artifact_capacity.py)（L114） | C2、D1／Agent 0 |
| A005 | [common/contracts/legacy_capacity_calibration.py](../../common/contracts/legacy_capacity_calibration.py) | 保留：保留显式历史校准；仅随共享常量 authority 修正导入，不把迁移报告重构当必改。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：按报告/迁移分段提函数与额外聚合字段可选，不能从长度断言缺陷。 | [build_calibration_inventory](../../common/contracts/legacy_capacity_calibration.py)（L793）<br>[test_calibration_binds_sealed_generic_owner_disposition](../../common/contracts/test_legacy_capacity_calibration.py)（L184） | A2 配套／Agent 0 |
| A006 | [common/contracts/legacy_owner_disposition.py](../../common/contracts/legacy_owner_disposition.py) | 必改（限界）：按依赖包含/重叠成组，失败组原子回退、独立组继续；无独立性证明仍整组阻断。<br>收益：消除已定位职责或恢复缺口；代价/风险：是否拆分一组相关target必须先证明互相独立；无证明继续整体阻断，不为成功数盲目部分提交。 | [_activation_groups](../../common/contracts/legacy_owner_disposition.py)（L535）<br>[test_failed_linked_group_is_atomic_and_independent_range_can_activate](../../common/contracts/test_legacy_capacity_calibration.py)（L348） | C 独立 owner 继续／Agent 3 |
| A007 | [common/contracts/reconcile_artifact_capacity.py](../../common/contracts/reconcile_artifact_capacity.py) | 必改（限界）：沿唯一 owner 完成压力白名单下一次受保护维护与 fresh admission；完整记录独立 owner 失败，不复活失效 lease。<br>收益：消除已定位职责或恢复缺口；代价/风险：closure_complete只有全部owner状态足够才派生；不新添capacity_satisfied同义字段；共享计时器抽取可选。 | [_run_maintenance_owner_actions](../../common/contracts/reconcile_artifact_capacity.py)（L1136）<br>[test_workflow_pressure_relief_uses_one_protected_pass_and_fresh_admission](../../common/contracts/test_capacity_reconcile_runtime.py)（L120） | C2/C3 准入与收尾／Agent 3 |
| A008 | [common/contracts/run_artifact_support.ps1](../../common/contracts/run_artifact_support.ps1) | 必改（限界）：修复 host release 次错覆盖容量主错；保留原异常/回执，释放失败阻止自动维护继续。<br>收益：同时保留初始故障、容量回执及cleanup故障，并在host释放失败时阻止自动维护继续；代价/风险：低到中：既有Gate catch/finally及两处压力catch，有限故障注入；不新增状态机。 | [Invoke-ArtifactWorkflowCapacityAdmission](../../common/contracts/run_artifact_support.ps1)（L162）<br>[test_host_release_failure_preserves_original_error_and_stops_pressure_recovery](../../common/contracts/test_capacity_reconcile_runtime.py)（L38） | Agent 原错保真／Agent 3 |
| A009 | [common/contracts/run_capacity_lifecycle.py](../../common/contracts/run_capacity_lifecycle.py) | 必改（限界）：保持一次索引优化；已完成删除后只重试精确 reseal，重新核 owner/reason/pin/余量，不重删。<br>收益：消除已定位职责或恢复缺口；代价/风险：为按长度拆lifecycle模块/测试不是must。 | [resume_partial_retirements](../../common/contracts/run_capacity_lifecycle.py)（L795）<br>[test_automatic_reseal_publication_failure_recovers_without_repeating_deletion](../../common/contracts/test_run_capacity_lifecycle.py)（L230） | C1/C3 生命周期／Agent 3 |
| A010 | [common/contracts/solver_review_retirement.py](../../common/contracts/solver_review_retirement.py) | 必改（限界）：原 retirement owner 自动 reseal；GUI 源保护归中性 authority、每次判断 fresh，不按文件长度拆 plan/apply/repair。<br>收益：消除已定位职责或恢复缺口；代价/风险：plan/apply/repair分文件可选；保留严格repair与第二批拒绝底层保护。 | [current_gui_source_retention](../../common/contracts/gui_source_protection.py)（L51）<br>[test_new_gui_receipt_is_visible_to_each_owner_decision](../../common/contracts/test_shared_artifact_contracts.py)（L46） | C3 reseal、A2／Agent 3 |
| A011 | [common/contracts/verify_artifact_layout.py](../../common/contracts/verify_artifact_layout.py) | 必改（限界）：默认 root/cache 布局仅 metadata，显式 deep 和窄 cache-entry 仍核 payload；共享角色常量正向归属。实际合法 recovery 目录由原 owner 校验身份，layout 仅严格投影目录形状；current deep 一次、非当前代 metadata，拒绝额外成员/casefold/reparse。<br>收益：消除已定位职责或恢复缺口；代价/风险：hashed_bytes等额外观测字段按实际消费者需要；不得取消窄--cache-entry真实消费验证。 | [verify_artifacts_root](../../common/contracts/verify_artifact_layout.py)（L930）<br>[_verify_pa_family_recovery_tree](../../common/contracts/verify_artifact_layout.py)（L763）<br>[test_common_layout_reads_metadata_by_default_and_deep_audit_rejects_same_size_change](../../common/contracts/test_verify_artifact_layout.py)（L279）<br>[test_common_layout_accepts_published_parity_without_default_payload_reads](../../common/contracts/test_verify_artifact_layout.py)（L298）<br>[test_common_layout_rejects_recovery_directory_reparse_points](../../common/contracts/test_verify_artifact_layout.py)（L350） | H4、A2／Agent 0/3；真实 recovery 布局窄修／Agent 4 |
| A012 | [common/integration/resolve_connection.py](../../common/integration/resolve_connection.py) | 保留：连接编译器已经统一仓库规范化文本与产物原始字节身份，并有单一resolve/plan/write/verify路径。<br>收益：避免出现第二套装配合同或自动推断缺失姿态；代价/风险：无必要迁移；内部helper提取只在具体修改需要时发生，须承担全部合同负例回归。 | [_dot](../../common/integration/resolve_connection.py)（L27）<br>[test_direct_mating_translation_is_derived_from_both_port_centers](../../common/integration/test_resolve_connection.py)（L29） | 保留决定；无新增实现要求 |
| A013 | [common/ion_release/cylinder.py](../../common/ion_release/cylinder.py) | 保留：采样、序列化、种子身份和materialize共享同一确定性状态；现有纯函数可独立测试。<br>收益：维持同母体、同seed、原出生状态和ID前缀；代价/风险：无必要迁移；机械拆分增加状态重算和身份分叉风险。 | [_canonical_json](../../common/ion_release/cylinder.py)（L35）<br>[test_axial_energy_position_and_ids_are_preserved_without_total_energy_rescaling](../../common/ion_release/test_cylinder.py)（L72） | 保留决定；无新增实现要求 |
| A014 | [common/report_cloc_delta.ps1](../../common/report_cloc_delta.ps1) | 保留：当前722行流水线职责连贯。依赖真实CLOC，逐文件汇总、分类与功能分区可加性检查、漏文件/重复文件/诊断失败关闭、WORKTREE与commit两入口均保留。无需按长度拆分或另造计数器。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：不迁移；维护现有负例，避免新增依赖及语义漂移 | [Test-IncludedPath](../../common/report_cloc_delta.ps1)（L61）<br>[test_fixture_filename_in_test_boundary_preserves_production_priority](../../common/contracts/test_report_cloc_delta.py)（L32） | 保留决定；无新增实现要求 |
| A015 | [common/resource_budget_support.ps1](../../common/resource_budget_support.ps1) | 必改（限界）：只同轮复用全主机枚举、每个 family 仍独立校验身份；采样异常自然等待同一直接根进程，不扩为任意后代框架。<br>收益：消除已定位职责或恢复缺口；代价/风险：不声称现代码资源不安全；旧同机三组交替实测：1 worker 中位数增加 2.09%，4/8 workers 减少 31.58%/35.14%；最终双臂完整源保全重测为1 worker +14.86%、4/8 workers -63.28%/-50.08%。两次环境/背景不同，只证明各自采样边界，整轮 57.0983365 s 不作加速声明。 | [Get-RepositoryProcessSnapshot](../../common/resource_budget_support.ps1)（L101）<br>[test_process_snapshot_preserves_complete_family_sample](../../projects/rf_multipole_ion_optics/tests/domain/test_resource_budget.py)（L750） | R1、Agent 进程收尾／Agent 4 |
| A016 | [common/simion/cache_generation.py](../../common/simion/cache_generation.py) | 保留：已有writable producer稳定化与immutable snapshot/materialize两类公共原语，常规路径职责清楚。<br>收益：复用经过持久视图验证的复制机制，避免第三套copy实现；代价/风险：无必要迁移；Windows持久读取改动将需要大文件与独立重开验证。 | [materialize_direct_inventory](../../common/simion/cache_generation.py)（L459）<br>[test_owner_inventory_uses_one_unbuffered_hash_without_stale_fallback](../../common/simion/test_cache_generation.py)（L28） | 保留决定；无新增实现要求 |
| A017 | [common/simion/pa_family_cache.py](../../common/simion/pa_family_cache.py) | 可选：文件体量大但sealed metadata命中、事务推进、repair与materialize已有明确语义；未发现必须靠拆文件修复的执行故障。<br>收益：窄身份/库存层抽取可降低未来维护时的依赖跨度；没有当前吞吐收益证据；代价/风险：高：导出符号、CLI、事务故障恢复、frozen dependency closure与B009均需迁移验证。 本轮仅采用右列具名包，结构拆分不采纳。 | [PAFamilyCacheError](../../common/simion/pa_family_cache.py)（L95）<br>[test_abandon_empty_transaction_preserves_failure_and_reconciles_without_deletion](../../common/simion/test_pa_family_cache.py)（L161） | 不拆文件；已选 A092 producer handoff／Agent 1；P2 实际暴露 key_root/recovery 6,110,431 B 漏记，由原 cache owner 补写入前登记、异常校准及验证后交接／Agent 3，136 回归及 P3 真实恢复通过 |
| A018 | [common/simion/resource_scheduler.py](../../common/simion/resource_scheduler.py) | 可选：现有case/batch预算与确定性分配保留；没有证据证明当前计数均衡错误。<br>收益：消除已定位职责或恢复缺口；代价/风险：本轮不采纳按耗时 hint/aging：现有记录缺少同 workload／测试集／源码／环境的可信绑定，新增调度权威缺乏收益依据；放宽heavy互斥前grant返回+内部pool clamp必须同时实现，不据当前调用os.cpu_count就推断已经超售。 未据长度采纳结构改造。 | [select_memory_profile](../../common/simion/resource_scheduler.py)（L159）<br>[test_physical_danger_limits_are_frozen_from_shared_host_policy](../../common/simion/test_resource_scheduler.py)（L26） | 可选未采纳；保留当前 owner |
| A019 | [common/simion/short_pa_path_support.ps1](../../common/simion/short_pa_path_support.ps1) | 可选：H1同次新复制的source两次/target三次完整校验有明确调用链，但当前校验未被证明错误；连续guard交接是删读的必要条件。<br>收益：高优先级候选：可减少大型PA完整读取与重复打开；逻辑 SHA 读量已同机测得；真实 run 20261029_062052__test__simion__h1-h2-three-workpoints 的 19 次 SIMION CLI、三工况各 343 节点及 60 次保护探针通过，H1 SHA 读量 5/14000→2/5600 B。小 PA 单对照不证明 OS 物理吞吐或大 PA 加速；代价/风险：中到高：现有source/target注册、异常cleanup、registry嵌套scope及Windows持久视图均需保持；需实际受管PA与独立vendor重开。 本轮仅采用右列具名包，结构拆分不采纳。 | [New-ShortPaCopy](../../common/simion/short_pa_path_support.ps1)（L237）<br>[test_published_copy_hands_off_verified_handle_without_second_payload_read](../../common/simion/test_short_pa_path_support.py)（L49） | 已选 H1/H2／Agent 2 |
| A020 | [integrations/analysis/plot_single_flight_spatial_six_panel.py](../../integrations/analysis/plot_single_flight_spatial_six_panel.py) | 可选：同CLI可重复解析同一checkpoint CSV，属于实在的重复I/O；尚无数据规模或耗时证据证明其优先于更大开销。<br>收益：可复用一次已验证DataFrame降低CSV解析与内存暂存，提前参数成组检查减少部分输出；代价/风险：中：保留独立path wrapper并比较多图科学数组/输出选择；需代表性CSV量级才可宣称提速。 未据长度采纳结构改造。 | [_quantiles](../../integrations/analysis/plot_single_flight_spatial_six_panel.py)（L48） | 可选未采纳；保留当前 owner |
| A021 | [integrations/runtime/build_single_flight_program.py](../../integrations/runtime/build_single_flight_program.py) | 保留：较长文件包含约923行生成模板文本，不能用模板行数推断算法复杂度；冻结依赖和真实Lua回调已有覆盖。<br>收益：保持生成程序、模板与冻结闭包一致；代价/风险：无必要迁移；外置模板需新增资源冻结/缺失拒绝与生成字节回归。 | [_ordinary_standalone_pa_basename](../../integrations/runtime/build_single_flight_program.py)（L49） | 保留决定；无新增实现要求 |
| A022 | [integrations/runtime/single_flight_electrode_contract.py](../../integrations/runtime/single_flight_electrode_contract.py) | 保留：电极拓扑和电压投影已经是单一权威，并有多RF组及禁止零填充合同。<br>收益：避免不同工作流私有role/ID映射；代价/风险：无必要迁移；拆分不能直接改善数值或运行成本。 | [_physical_voltage_value](../../integrations/runtime/single_flight_electrode_contract.py)（L21） | 保留决定；无新增实现要求 |
| A023 | [integrations/workflows/oa_mr/execute.ps1](../../integrations/workflows/oa_mr/execute.ps1) | 必改（限界）：修复 finally 级联遮主错及跳必要 cleanup；unknown writer 不发布、退容量或清活输入，真实同 token release 独立保留。<br>收益：保证已启动资源按各自owner尝试收尾，保留科学失败与封存失败，不错误报PASS；代价/风险：中：在既有owner内做异常隔离与错误聚合，保留原terminal publication/lease继承语义；需要多故障真实PS fixture。 | [Invoke-SimionStage](../../integrations/workflows/oa_mr/execute.ps1)（L58）<br>[test_closeout_preserves_primary_error_and_isolates_safe_owner_actions](../../integrations/tests/test_oa_mr_execute.py)（L1219） | Agent cleanup／Agent 2 |
| A024 | [integrations/workflows/paired_accelerator_pulse/runtime.py](../../integrations/workflows/paired_accelerator_pulse/runtime.py) | 保留：completed pulse阶段已有manifest绑定和每次调用verified-set，明确不读native payload；materialize/dispatch/batches/collect已分函数。<br>收益：保留全完成零native、部分整单元重放和精确物理身份；代价/风险：无必要迁移；内部恢复helper提取只改善维护，需frozen import与负例回归。 | [_read](../../integrations/workflows/paired_accelerator_pulse/runtime.py)（L33） | 保留决定；无新增实现要求 |
| A025 | [integrations/workflows/single_reflection_flight/execute.ps1](../../integrations/workflows/single_reflection_flight/execute.ps1) | 可选：该入口确实消费H1五次hash链；它自身已有阶段资格区分和嵌套cleanup，未发现必须改其科学行为的依据。<br>收益：若H1读量/guard实验支持，可直接接同owner转交记录，减少重复target校验；代价/风险：中：必须随A019原子接线，验证IOB slot、独立重开和native前保护；不能只删本地Protect。 本轮仅采用右列具名包，结构拆分不采纳。 | [Get-InstrumentNativePriorityOccupancyEvidence](../../integrations/workflows/single_reflection_flight/execute.ps1)（L135） | 已选 H1 消费接线／Agent 2 |
| A026 | [integrations/workflows/single_reflection_flight/prepare.py](../../integrations/workflows/single_reflection_flight/prepare.py) | 可选：prepare先冻结再消费，保留母体ID、原出生时刻并有一次采样/解析证据；建议提函数不对应已确认正确性缺陷。<br>收益：命名阶段可降低将来修改源/几何流程的认知成本，无已测性能收益；代价/风险：中：身份/时钟/continuation作用域及冻结依赖测试面大，移动时容易重读live author输入。 未据长度采纳结构改造。 | [_read](../../integrations/workflows/single_reflection_flight/prepare.py)（L73） | 可选未采纳；保留当前 owner |
| A027 | [integrations/workflows/single_reflection_flight/runtime.py](../../integrations/workflows/single_reflection_flight/runtime.py) | 必改（限界）：将六个已有函数归 census/pulse/downstream_fields/runtime owner，解除 runtime/continuation/collect 环；不新增通用模块或声称全 DAG 清理。<br>收益：建立可独立加载的证据/phase合同层，解除实际反向依赖，保持冻结消费者可独立执行；代价/风险：中：只提取最小纯合同到该workflow内部，更新runtime_dependencies和detached consumer；不得新增泛用common层或第二状态机。 | [materialize_phase_continuation](../../integrations/workflows/single_reflection_flight/runtime.py)（L595）<br>[test_frozen_source_drift_and_missing_snapshot_module_have_no_repo_fallback](../../integrations/tests/test_single_reflection_runtime.py)（L590） | A2／Agent 2 |
| A028 | [IP/analysis/diagnostics.py](../../projects/dual_pressure_rectilinear_ion_processor/analysis/diagnostics.py) | 可选：全母群分类、能量解释及图形在IP有明确领域职责；已用公共census/particle state，不能整体搬common。prepare_visual_style_map却来自RF，形成中性样式跨项目依赖。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [common particle_census imports](../../projects/dual_pressure_rectilinear_ion_processor/analysis/diagnostics.py)（现 L20）<br>[test_relative_census_and_explicit_conditional_vs_full_chain_efficiency](../../projects/dual_pressure_rectilinear_ion_processor/tests/test_diagnostics.py)（L117） | 可选未采纳；保留当前 owner |
| A029 | [IP/analysis/functional.py](../../projects/dual_pressure_rectilinear_ion_processor/analysis/functional.py) | 保留：保留正式 retention→publish→完整 verifier→seal 链；helper 级“缺发布验证”判断已撤销，不删除独立 verifier。<br>收益：保留已有完整正式发布链，避免重复包装器与删除必要独立消费验证；代价/风险：API统一仅属可选；若将helper作为独立发布入口，须另补完整发布合同。 | [正式 retention→publish→verify→seal](../../projects/dual_pressure_rectilinear_ion_processor/simion/run_functional.ps1)（L255/258/260/265）<br>[test_frozen_closure_loads_particle_count_policy_in_independent_python](../../projects/dual_pressure_rectilinear_ion_processor/tests/test_functional.py)（L583） | 保留决定；无新增实现要求 |
| A030 | [OA/analysis/accelerator_time_focus.py](../../projects/orthogonal_accelerator/analysis/accelerator_time_focus.py) | 保留：OA局部时间聚焦模型与公式族已有明确owner，器件理论供分析器/集成消费；千行不是迁移或拆公式理由。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [accelerator_state](../../projects/orthogonal_accelerator/analysis/accelerator_time_focus.py)（现 L185）<br>[test_fixed_energy_gap1_focus_sensitivity_matches_independent_fixture](../../projects/orthogonal_accelerator/tests/analysis/test_accelerator_time_focus.py)（L38） | 保留决定；无新增实现要求 |
| A031 | [MR/analysis/bunch_source_and_schedule.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/bunch_source_and_schedule.py) | 可选：已有唯一source/clock和schedule owner，444行函数本身不是缺陷；未发现第二科学权威或本次可复现恢复错误。<br>收益：纯plan可缩小测试输入及以后修改影响面；代价/风险：中：源schema1–4、母序列、receipt及byte稳定回归面大，新增数据结构会增加传输/转换。 未据长度采纳结构改造。 | [deterministic_ideal_bunch_states](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/bunch_source_and_schedule.py)（L101）<br>[test_controlled_slow_energy_list_publishes_seven_pure_probe_states](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_bunch_source_and_schedule.py)（L60） | 可选未采纳；保留当前 owner |
| A032 | [MR/analysis/downstream_fixed_grid_workpoint.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/downstream_fixed_grid_workpoint.py) | 必改（限界）：必改仅限 field projection 对编排模块的反向依赖；全 provider DAG 或所有 lazy import 的重写不属本项。<br>收益：将同一科学problem projection放到能被双方正向消费的窄owner，消除必须靠lazy import维持的环；代价/风险：中：field/source/mesh身份恢复敏感，需Agent3协作及原轻投影回归。 | [native_binding_problem](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/static_field_binding.py)（L1112）<br>[test_native_and_scalar_metadata_validation_does_not_import_workpoint](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_static_field_binding.py)（L1989） | A2 窄依赖／Agent 3 |
| A033 | [MR/analysis/downstream_workpoint_iteration.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/downstream_workpoint_iteration.py) | 必改（限界）：纯 controller 决策归 Python；prepared 输入消费正向委托公共成功记录 verifier，保留 owner/mode/真实 SHA。<br>收益：一个科学controller、一个record验证机制，恢复判定可纯测试；代价/风险：中高：staged/recovery历史状态及budget行为需完整轻fixture对照。 | [verified_successful_run_reference](../../common/contracts/verify_run_manifest.py)（L51）<br>[test_measured_acquisition_uses_public_request_and_never_changes_source_energy](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_downstream_workpoint_iteration.py)（L40） | A1/A2／Agent 2/0 |
| A034 | [MR/analysis/dual_stripe_l0.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/dual_stripe_l0.py) | 保留：纯理论族已具名、内聚且独立可测；长度不构成违规。<br>收益：保留稳定数学定义与独立参考，避免重命名/导入变动风险；代价/风险：不改成本最低；拆分会增加跨模块参数/数值权威分散。 | [gauss_legendre_rule](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/dual_stripe_l0.py)（L43） | 保留决定；无新增实现要求 |
| A035 | [MR/analysis/dual_stripe_operating_seed.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/dual_stripe_operating_seed.py) | 必改（限界）：唯一 frozen dataclass 归 mirror_candidate_receipt；seed/handoff 正向导入，seed loader 保留函数内懒导入，不扩大 detached exact-k 闭包。<br>收益：类型归receipt，loader仍归handoff，seed通过函数内懒导入保持正向依赖；代价/风险：低中：三个生产文件及实际import消费者，小于重写搜索/report的成本。 | [FixedHardwareMirrorPoint](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/mirror_candidate_receipt.py)（L36）<br>[test_handoff_and_point_load_in_new_process_without_seed](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_fixed_grid_mirror_stripe_handoff.py)（L116） | A2 类型归属／Agent 2 实施、Agent 3 独审 |
| A036 | [MR/analysis/export_resolved_cad.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/export_resolved_cad.py) | 可选：已有公共SolidWorks bridge、冷读与publication-only边界。未证实一个函数较长导致重复CAD或错误发布。<br>收益：消除已定位职责或恢复缺口；代价/风险：纯计划/COM/cold validation具名内部阶段可改善测试；代价为接口/冻结依赖变动和真实CAD复验，不为1167行自动重构。 未据长度采纳结构改造。 | [compile_parts](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/export_resolved_cad.py)（L107） | 可选未采纳；保留当前 owner |
| A037 | [MR/analysis/ip_prism_distance_study.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/ip_prism_distance_study.py) | 保留：保留正式 runner 已有 publish→verify→seal；完整 API 统一只属可选，无依据将当前 helper 判为缺陷。<br>收益：保留已有完整外层发布链，避免增加重复 publisher authority；代价/风险：不作仅风格 API 迁移；现独立 verifier 与 seal 顺序继续承担失败关闭 | [正式 retention→publish→verify→seal](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_ip_prism_distance_study.ps1)（L174/175/176/179）<br>[test_physical_controls_are_explicit](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_ip_prism_distance_study.py)（L35） | 保留决定；无新增实现要求 |
| A038 | [MR/analysis/ip_prism_focus_diagnostics.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/ip_prism_focus_diagnostics.py) | 保留：真实crossing、variance budget和虚拟aperture已有独立纯函数与明确资格边界。<br>收益：保持单一统计/粒子选择语义；代价/风险：零新增迁移成本；机械拆分只增加接口。 | [normal_crossing](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/ip_prism_focus_diagnostics.py)（L24）<br>[test_numerical_comparison_rows_preserve_frozen_vectors_order_and_missing_ids](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_ip_prism_focus_diagnostics.py)（L24） | 保留决定；无新增实现要求 |
| A039 | [MR/analysis/ip_prism_local_diagnostics.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/ip_prism_local_diagnostics.py) | 可选：重复export可统一，但本轮未证明正式入口覆盖已封存证据；不能仅凭private savefig判定现有run已损坏。<br>收益：common exporter增加统一exclusive preflight与partial-write rollback；代价/风险：低中：DPI、metadata、Figure关闭和既有输出命名须回归，覆盖拒绝可能改变重分析使用方式。 本轮仅采用右列具名包，结构拆分不采纳。 | [_save_figure](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/ip_prism_local_diagnostics.py)（L334）<br>[test_figure_export_failure_preserves_existing_files_and_closes](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_ip_prism_local_diagnostics.py)（L49） | 已选 D1 图导出／Agent 3 |
| A040 | [MR/analysis/joint_flight_preparation.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/joint_flight_preparation.py) | 保留：已分prepare、field/event audit、render；本文件没有project→integration import。<br>收益：保留MR field/halo/clock规则所有权；代价/风险：不拆无额外成本，搬入common会增加不当领域耦合。 | [audit_field_coverage](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/joint_flight_preparation.py)（L117）<br>[test_provider_voltage_projection_freezes_injected_public_waveforms](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_joint_flight_preparation.py)（L23） | 保留决定；无新增实现要求 |
| A041 | [MR/analysis/joint_mirror_stripe_l0.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/joint_mirror_stripe_l0.py) | 保留：单一耦合理论族具名trial、Jacobian、solver、action/phase，且有独立参考。<br>收益：避免拆散同一数学定义；代价/风险：无迁移必要；提空壳只增加传参。 | [classify_constraint_system](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/joint_mirror_stripe_l0.py)（L187）<br>[test_rounded_fast_phase_endpoint_matches_linear_analytic_count](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_joint_mirror_stripe_l0.py)（L43） | 保留决定；无新增实现要求 |
| A042 | [MR/analysis/mirror_exact_k_operating_point.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/mirror_exact_k_operating_point.py) | 可选：load/solve/report同函数尚未导致双权威或错误恢复；当前heavy互斥仍保留，未证实现有pool超售。<br>收益：具名阶段便于扩展；实际grant接线为未来重任务并发提供必要上限；代价/风险：中：branch caches/排序/parallel identity回归；公共grant协议需跨owner改变。 未据长度采纳结构改造。 | [solve_exact_k_operating_point](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/mirror_exact_k_operating_point.py)（L930）<br>[test_current_contract_uses_the_stripe_on_adiabatic_selector_status](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_mirror_exact_k_operating_point.py)（L47） | 可选未采纳；保留当前 owner |
| A043 | [MR/analysis/mirror_fixed_grid_voltage_correction.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/mirror_fixed_grid_voltage_correction.py) | 可选：两算法的证据/输出有重叠，但本轮未发现该重叠产生冲突或身份错误；不能因579/444行强制统一。<br>收益：可减少确实相同point provenance规则的维护点；代价/风险：中高：初始correction与多chord差异很多，共用context容易掩盖算法特有gate。 未据长度采纳结构改造。 | [build_correction_proposal](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/mirror_fixed_grid_voltage_correction.py)（L535）<br>[test_runner_uses_ledger_lifecycle_and_one_capacity_session](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_mirror_fixed_grid_voltage_correction.py)（L34） | 可选未采纳；保留当前 owner |
| A044 | [MR/analysis/native_static_field_provider.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/native_static_field_provider.py) | 必改（限界）：只闭合实际 runner 的原错、真实 release 与 seal-only 恢复；已有公共 seal CLI 可单独收尾，不新造恢复模式。<br>收益：消除已定位职责或恢复缺口；代价/风险：compile_request纯阶段抽取与provider↔binding窄合同可选；目前循环/私有调用复用同一公式，未证实双份科学权威。TE1提独立module需真实多owner收益。 | [Exit-NativeProviderHostStage](../../projects/parallel_mirror_dual_stripe_mr_tof/simion/run_native_static_field_provider.ps1)（L18）<br>[test_published_provider_seal_failure_uses_existing_cli_without_native_reentry](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_native_static_field_provider.py)（L1778） | Agent seal-only／Agent 4 |
| A045 | [MR/analysis/prepared_joint_diagnostics.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/prepared_joint_diagnostics.py) | 可选：canonical state/clock已集中；analyze_prepared_joint_flight520显式拒绝已存在输出目录，不能笼统声称当前导出允许覆盖。<br>收益：common exporter统一多格式失败回滚与输出记录；代价/风险：低中：metadata SHA、dpi180和close行为回归；已有fresh-directory保护降低即时收益。 本轮仅采用右列具名包，结构拆分不采纳。 | [_save_figure](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/prepared_joint_diagnostics.py)（L351）<br>[test_figure_export_preserves_names_dpi_records_and_closes](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_prepared_joint_diagnostics.py)（L28） | 已选 D1 图导出／Agent 3 |
| A046 | [MR/analysis/prepared_joint_trial.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/prepared_joint_trial.py) | 必改（限界）：以公共成功记录消费 helper 代替项目反导 integration CLI；保留精确 manifest record 与 owner/mode 校验。<br>收益：领域输入显式、装配role/provider决策归装配层、共用record verifier保持唯一；代价/风险：中高：CLI/prepared batch/97状态真实身份边界与负例需协同迁移。 | [verified_successful_run_reference](../../common/contracts/verify_run_manifest.py)（L51）<br>[test_prepared_component_import_and_reference_do_not_load_integration_cli](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_prepared_joint_trial.py)（L21） | A2 成功记录消费／Agent 0 |
| A047 | [MR/analysis/resolved_geometry.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/resolved_geometry.py) | 可选：resolved_geometry仍是唯一几何派生与fingerprint权威，未发现仅长函数即结果错误。<br>收益：消除已定位职责或恢复缺口；代价/风险：按mirror/stripe/prism/detector纯阶段提函数有局部可测试性收益，但增加中间结构和冻结差异；保留现函数是可接受结论。 未据长度采纳结构改造。 | [resolve_geometry](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/resolved_geometry.py)（L905） | 可选未采纳；保留当前 owner |
| A048 | [MR/analysis/run_downstream_workpoint_iteration.ps1](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_downstream_workpoint_iteration.ps1) | 必改（限界）：把候选电压、step floor、恢复模型与预算决定移到既有 Python controller；PS 只执行、保存和运输。<br>收益：同一纯controller可回归完整decision序列；PS只管实际执行/恢复持久化；代价/风险：高：state/pending/预算/历史兼容敏感；须复用现有轻fixture，不能只改字符串测试。 | [plan_staged_trial](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/workpoint_controller_state.py)（L544）<br>[test_transport_candidates_match_original_powershell_vectors](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_workpoint_controller_state.py)（L47） | A1 controller／Agent 2 |
| A049 | [MR/analysis/run_native_candidate_campaign.ps1](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_native_candidate_campaign.ps1) | 必改（限界）：补完整 composition plan/scope 参数透传；资格、统计排名和比较投影归同一 Python policy，PS 不保第二科学 authority。<br>收益：恢复默认入口可运行性，保持显式父plan；科学比较由既有Python owner单一维护；代价/风险：低中（参数修复）+中（比较迁移）；新增default child绑定fixture及ranking parity。 | [compare_candidate_campaign](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/source_z_energy_timing_diagnostic.py)（L2601）<br>[test_campaign_full_projection_matches_original_powershell](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_source_z_energy_timing_diagnostic.py)（L1915） | A1 campaign／Agent 2 |
| A050 | [MR/analysis/run_native_candidate_chain.ps1](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_native_candidate_chain.ps1) | 必改（限界）：焦点阈值、z0 分类与 qualification 优先级归既有 Python policy；保留实际 root seed 与恢复调用顺序。<br>收益：决策能纯测试，并与诊断owner的peak/clock契约保持一致；代价/风险：中高：warning precedence、TE1 reclosure、selected field和完成阶段复用均需parity。 | [candidate_policy](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/source_z_energy_timing_diagnostic.py)（L2640）<br>[test_best_focused_fallback_preserves_actual_field_for_final_cohort](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_native_candidate_chain_runner.py)（L1517） | A1 chain／Agent 2 |
| A051 | [MR/analysis/run_native_candidate_condition.ps1](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_native_candidate_condition.ps1) | 保留：其Mandatory CompositionPlanPath是正确的公开边界，漏传发生在campaign；已有Copy-ArgumentMap、明确child阶段、failure_stage和现行恢复参数。<br>收益：保留薄condition adapter，避免为上游错误不必要改动子入口；代价/风险：修复caller即可；整块抽terminal/参数注册只增加接口与回归。 | [Copy-ArgumentMap](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_native_candidate_condition.ps1)（L48） | 保留决定；无新增实现要求 |
| A052 | [MR/analysis/simion_candidate_reference.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/simion_candidate_reference.py) | 保留：OA理论与geometry已有owner复用，MR只做自身坐标/energy映射及GEM。<br>收益：单一物理定义不被复制；代价/风险：无改造收益证据。 | [derive_two_zone_focus](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/simion_candidate_reference.py)（L529）<br>[test_resolves_default_and_named_profiles_from_contract](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_simion_candidate_reference.py)（L80） | 保留决定；无新增实现要求 |
| A053 | [MR/analysis/simion_event_analysis.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/simion_event_analysis.py) | 可选：现有common KDE复用成立；未证实事件重复index是主要耗时。<br>收益：消除已定位职责或恢复缺口；代价/风险：分事件视图/表面解释可读性与CPU收益待测；勿机械合并Pearson不足样本、mm/us单位和legacy电荷语义。实际私有跨模块consumer保留或有计划公开，不能误删。 未据长度采纳结构改造。 | [parse_events](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/simion_event_analysis.py)（L176）<br>[test_histogram_span_preserves_disconnected_bins_and_declares_its_method](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_simion_event_analysis.py)（L141） | 可选未采纳；保留当前 owner |
| A054 | [MR/analysis/source_z_energy_timing_diagnostic.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/source_z_energy_timing_diagnostic.py) | 必改（限界）：承接 A1 已选科学决策与纯回归；独立拆 TE1、plot loader 或多 CLI handler 不在必改范围。<br>收益：消除已定位职责或恢复缺口；代价/风险：单独拆TE1参考、CLI handlers或plot loader属于可选组织；目前未证实同一物理事实在该文件双写。 | [candidate_qualification](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/source_z_energy_timing_diagnostic.py)（L2534）<br>[test_qualification_matches_original_powershell_priority](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_source_z_energy_timing_diagnostic.py)（L1945） | A1 纯决策 owner／Agent 2 |
| A055 | [MR/analysis/static_field_binding.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/static_field_binding.py) | 可选：intra-MR lazy循环/私有投影依赖可定位，但现状复用的是同一投影；无证据支持重复公式漂移。<br>收益：消除已定位职责或恢复缺口；代价/风险：抽纯response/operator合同可减环、独立测试，但增加API/冻结闭包与导入迁移成本；与Agent1 A032统一，不把整个模块重写判must。 本轮仅采用右列具名包，结构拆分不采纳。 | [verify_joint_asset_records](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/static_field_binding.py)（L252）<br>[test_actual_joint_payloads_are_verified_once_and_conflicts_or_drift_rejected](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_static_field_binding.py)（L32） | 大拆分不采纳；A032 窄接线／Agent 1 |
| A056 | [MR/analysis/two_prism_segmented_coverage.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/two_prism_segmented_coverage.py) | 可选：重复finite转换确切同义但未造成当前错误；现有load/source/run/report已有职责边界。当前heavy互斥下未证实超售。<br>收益：公开现有transport转换可降低输入语义漂移，未来grant接口可约束并发；代价/风险：低（finite）/中（grant）；需要保持numeric string与错误语义，防止共享helper将不同validators混为一谈。 未据长度采纳结构改造。 | [_finite](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/two_prism_segmented_coverage.py)（L65）<br>[test_fixed_grid_stripe_target_k_must_match_downstream_contract](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_two_prism_segmented_coverage.py)（L26） | 可选未采纳；保留当前 owner |
| A057 | [MR/analysis/two_prism_segmented_transport.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/two_prism_segmented_transport.py) | 可选：单一transport模型已经正确归属；12行转换重复不是独立科学算法或恢复缺陷。<br>收益：沿已有import公开一个转换，无新utils模块；代价/风险：低：改三个consumer及输入矩阵；若同名strict validators被误并会改变语义。 未据长度采纳结构改造。 | [_finite_value](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/two_prism_segmented_transport.py)（L404）<br>[test_initial_search_window_is_contract_owned_and_charge_aware](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_two_prism_segmented_transport.py)（L60） | 可选未采纳；保留当前 owner |
| A058 | [MR/analysis/two_prism_segmented_voltage_continuation.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/two_prism_segmented_voltage_continuation.py) | 可选：纯continue函数已存在，main是可追踪的一条CLI流水线；未发现私有worker接口导致当前失败或第二状态机。<br>收益：公开loaded evaluator和计划阶段可改善局部测试/未来复用；代价/风险：中：worker全局context、input provenance、branch evaluation次序需回归；新context层有管理成本。 未据长度采纳结构改造。 | [main](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/two_prism_segmented_voltage_continuation.py)（L1044）<br>[test_coverage_auto_selection_uses_one_same_p1_same_topology_sign_bracket](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_two_prism_segmented_voltage_continuation.py)（L69） | 可选未采纳；保留当前 owner |
| A059 | [MR/analysis/two_prism_segmented_voltage_seed.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/two_prism_segmented_voltage_seed.py) | 可选：单个bounded search已有显式预算、失败证据和内部evaluate/finish；长函数并未证明混有无关workflow或重复权威。<br>收益：在真正修改backtracking策略时提纯可减少测试设置；代价/风险：中：评价次序与预算账本最易在拆分中漂移。 未据长度采纳结构改造。 | [_finite](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/two_prism_segmented_voltage_seed.py)（L92）<br>[test_turn_identity_separates_paths_with_same_legacy_topology](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_two_prism_segmented_voltage_seed.py)（L113） | 可选未采纳；保留当前 owner |
| A060 | [MR/analysis/two_prism_simion_trial.py](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/two_prism_simion_trial.py) | 可选：materialize与analyze本来就是不同public函数，已有大量source/field/priority/event helpers；没有证据表明更细分层能修现有缺陷。<br>收益：plan/event纯函数可在新增field模式时缩小验证面；代价/风险：高：当前privatehelpers、Lua/FLY2、receipt、CLI和多种native/static路径的回归面大；无测量不能宣称更快。 未据长度采纳结构改造。 | [materialize_trial](../../projects/parallel_mirror_dual_stripe_mr_tof/analysis/two_prism_simion_trial.py)（L1813）<br>[test_collision_projection_preserves_optional_ip_detector_and_legacy_geometry](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_two_prism_simion_trial.py)（L56） | 可选未采纳；保留当前 owner |
| A061 | [MR/simion/mrtof_candidate.lua](../../projects/parallel_mirror_dual_stripe_mr_tof/simion/mrtof_candidate.lua) | 保留：保留Lua runtime回调与Python科学分析边界。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：仅具体回调混职责才提helper。 | [emit_cycle_events](../../projects/parallel_mirror_dual_stripe_mr_tof/simion/mrtof_candidate.lua)（L318） | 保留决定；无新增实现要求 |
| A062 | [RF/analysis/campaign_analysis.py](../../projects/rf_multipole_ion_optics/analysis/campaign_analysis.py) | 可选：preflight与series各有函数但同文件还含私有均值/RMS/分位数/相关系数；资格判断必须保留RF。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [campaign_request_preflight](../../projects/rf_multipole_ion_optics/analysis/campaign_analysis.py)（现 L218）<br>[test_pair_reports_segmented_minus_no_acceleration](../../projects/rf_multipole_ion_optics/tests/domain/test_campaign_analysis.py)（L118） | 可选未采纳；保留当前 owner |
| A063 | [RF/analysis/exit_state_plot.py](../../projects/rf_multipole_ion_optics/analysis/exit_state_plot.py) | 可选：RF数据/比较样式与paired IDs约束应保留。其图+manifest成对覆盖事务不等同common.figure_export的禁止覆盖单次导出，不能直接替换。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [prepare_visual_style_map](../../projects/rf_multipole_ion_optics/analysis/exit_state_plot.py)（现 L228）<br>[test_comparison_semantics_and_paired_ids_fail_closed](../../projects/rf_multipole_ion_optics/tests/domain/test_exit_state_plot.py)（L299） | 可选未采纳；保留当前 owner |
| A064 | [RF/analysis/followup_analysis.py](../../projects/rf_multipole_ion_optics/analysis/followup_analysis.py) | 保留：工程批次已单次加载run、显式claim_limit和DEFERRED_NOT_WAIVED；不是普通物理默认值入口。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [engineering_batch](../../projects/rf_multipole_ion_optics/analysis/followup_analysis.py)（现 L439）<br>[test_engineering_batch_loads_runs_once_and_preserves_order](../../projects/rf_multipole_ion_optics/tests/domain/test_followup_analysis.py)（L127） | 保留决定；无新增实现要求 |
| A065 | [RF/analysis/numerical_qualification.py](../../projects/rf_multipole_ion_optics/analysis/numerical_qualification.py) | 保留：identity和evaluate分别可测，numerical_observables为既有观测owner；资格阈值/工程进展合同归RF。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [validate_identity](../../projects/rf_multipole_ion_optics/analysis/numerical_qualification.py)（现 L429）<br>[test_temporal_pair_rejects_mesh_drift](../../projects/rf_multipole_ion_optics/tests/domain/test_numerical_qualification.py)（L438） | 保留决定；无新增实现要求 |
| A066 | [RF/analysis/stationary_field_sampling.py](../../projects/rf_multipole_ion_optics/analysis/stationary_field_sampling.py) | 保留：保留采样和诊断比较。实际配对是本文件(field_case,sample_id)+region+坐标，不是已接公共粒子配对；公共粒子ID语义不适用此场采样键。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [generate_stationary_field_sample_rows](../../projects/rf_multipole_ion_optics/analysis/stationary_field_sampling.py)（现 L346）<br>[test_compare_rejects_coordinate_difference](../../projects/rf_multipole_ion_optics/tests/domain/test_stationary_field_sampling.py)（L255） | 保留决定；无新增实现要求 |
| A067 | [RF/comsol/solve_deterministic_rf_quadrupole_particles.m](../../projects/rf_multipole_ion_optics/comsol/solve_deterministic_rf_quadrupole_particles.m) | 可选：MATLAB COMSOL模型、release construction gate、原始面插值属同一供应商边界；已有专用gate和函数，无跨语言重写理由。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [solve_deterministic_rf_quadrupole_particles](../../projects/rf_multipole_ion_optics/comsol/solve_deterministic_rf_quadrupole_particles.m)（现 L1）<br>[test_release_construction_gate_stops_before_particle_study](../../projects/rf_multipole_ion_optics/tests/analysis/test_comsol_workflow_architecture_contract.py)（L307） | 可选未采纳；保留当前 owner |
| A068 | [RF/comsol/solve_finite_3d_transport.m](../../projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m) | 可选：主体try约48-760同时构造模型/网格/场/粒子/导出；已有checkpoint和若干求解辅助，可沿真实阶段细分，不新造solver。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [top-level solver try](../../projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m)（现 L48）<br>[test_mesh_build_report_enforces_declared_cell_limit](../../projects/rf_multipole_ion_optics/tests/domain/test_resource_budget.py)（L2068） | 可选未采纳；保留当前 owner |
| A069 | [RF/core/compile_design_request.py](../../projects/rf_multipole_ion_optics/core/compile_design_request.py) | 保留：纯编译器分开了geometry/enclosure/drive派生和typed/governed校验，仍是唯一RF设计权威；无证据支持拆为多个默认值源。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [compile_design_request](../../projects/rf_multipole_ion_optics/core/compile_design_request.py)（现 L488）<br>[test_both_l3_runners_have_one_governed_physical_authority](../../projects/rf_multipole_ion_optics/tests/domain/test_resolved_design_consumers.py)（L19） | 保留决定；无新增实现要求 |
| A070 | [RF/runtime/run_finite_3d_transport.ps1](../../projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1) | 必改（限界）：沿既有 RF runner 保留求解主错与收尾次错；不以长函数为由建立通用 solver runner。<br>收益：补齐已存在正式入口的错误保留、身份或终态合同，防止错误复用/错误结果外观；代价/风险：必须覆盖真实driver的软件负例、双故障和资源收尾；若触及solver阶段/原生产物，再做对应真实solver验证。 | [New-RunPackage with retention and capacity](../../projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1)（现 L149）<br>[test_transport_closure_and_host_errors_preserve_original_failure](../../projects/rf_multipole_ion_optics/tests/analysis/test_comsol_workflow_architecture_contract.py)（L712） | Agent RF 原错/收尾／Agent 0 |
| A071 | [RF/runtime/run_simion_finite_3d_transport.ps1](../../projects/rf_multipole_ion_optics/runtime/run_simion_finite_3d_transport.ps1) | 必改（限界）：保留公共 PA cache、host lease 和批调度；窄修原错与安全收尾，不增加第二缓存或调度器。<br>收益：补齐已存在正式入口的错误保留、身份或终态合同，防止错误复用/错误结果外观；代价/风险：必须覆盖真实driver的软件负例、双故障和资源收尾；若触及solver阶段/原生产物，再做对应真实solver验证。 | [Invoke-CommonPaFamilyCache](../../projects/rf_multipole_ion_optics/runtime/run_simion_finite_3d_transport.ps1)（现 L73）<br>[test_pa_basis_delegates_to_the_common_content_addressed_cache](../../projects/rf_multipole_ion_optics/tests/domain/test_simion_runner_contract.py)（L612） | Agent RF 原错/收尾／Agent 0 |
| A072 | [RF/runtime/runtime_profile.py](../../projects/rf_multipole_ion_optics/runtime/runtime_profile.py) | 可选：profile解析、campaign设计编译与selection已有函数。当前普通registry是读取并记录SHA，没有在resolve_runtime_profile里要求匹配历史hash；不能照指南泛删hash。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [resolve_runtime_profile](../../projects/rf_multipole_ion_optics/runtime/runtime_profile.py)（现 L40）<br>[test_campaign_semantic_diff_resolves_profiles_without_execution_policy](../../projects/rf_multipole_ion_optics/tests/domain/test_transport_campaign.py)（L462） | 可选未采纳；保留当前 owner |
| A073 | [RF/simion/simion_geometry.py](../../projects/rf_multipole_ion_optics/simion/simion_geometry.py) | 保留：RF实体、电极映射与GEM/native布局有唯一投影owner，integration实际复用。不能抽成丢失RF边界的通用geometry平台。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [physical_electrodes](../../projects/rf_multipole_ion_optics/simion/simion_geometry.py)（现 L92）<br>[test_rectangular_reference_keeps_its_existing_standalone_bytes](../../projects/rf_multipole_ion_optics/tests/domain/test_simion_geometry.py)（L199） | 保留决定；无新增实现要求 |
| A074 | [RF/workflows/interface_readiness/run_comsol.ps1](../../projects/rf_multipole_ion_optics/workflows/interface_readiness/run_comsol.ps1) | 必改（限界）：必改失败收尾覆盖原 COMSOL 错误；保持单 workflow 与既有 terminal 边界。<br>收益：补齐已存在正式入口的错误保留、身份或终态合同，防止错误复用/错误结果外观；代价/风险：必须覆盖真实driver的软件负例、双故障和资源收尾；若触及solver阶段/原生产物，再做对应真实solver验证。 | [New-RunPackage](../../projects/rf_multipole_ion_optics/workflows/interface_readiness/run_comsol.ps1)（现 L64）<br>[test_interface_failure_closure_preserves_original_error](../../projects/rf_multipole_ion_optics/tests/analysis/test_comsol_workflow_architecture_contract.py)（L778） | Agent RF 原错/收尾／Agent 0 |
| A075 | [RF/workflows/same_solver_convergence/evaluate.py](../../projects/rf_multipole_ion_optics/workflows/same_solver_convergence/evaluate.py) | 可选：main约326行将closure身份、资格和数值比较串在一起，宜分验证/加载/比较。H5指小文件重复读取，不是把大型solver数据身份检查删除。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [verify_record](../../projects/rf_multipole_ion_optics/workflows/same_solver_convergence/evaluate.py)（现 L30）<br>[test_registered_simion_40_to_80_passes](../../projects/rf_multipole_ion_optics/tests/analysis/test_same_solver_numerical_convergence.py)（L821） | 可选未采纳；保留当前 owner |
| A076 | [oaTOF/analysis/analyze_paper1_connector_gap_residual.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/analyze_paper1_connector_gap_residual.py) | 保留：单/三臂残差分析已把checkpoint种类、时钟、母cohort及detector-blind训练/验证/检验分离；这是必要科学合同。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [load_fixed_pulse_checkpoint_source](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/analyze_paper1_connector_gap_residual.py)（现 L120）<br>[test_compares_locked_axial_residuals_without_detector_outcomes](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_paper1_connector_gap_residual.py)（L65） | 保留决定；无新增实现要求 |
| A077 | [oaTOF/analysis/experiment_campaign.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/experiment_campaign.py) | 可选：已有preflight、单Candidate executor及执行前interrupted/provisional预态（614-627），中断不会留下成功或running外观；每row进度与最后完成阶段的汇总/恢复说明仍可改善，但不能据此判定已有错误执行。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [validate_campaign](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/experiment_campaign.py)（现 L217）<br>[test_campaign_table_and_selection_are_frozen_into_child_manifest](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_candidate_design.py)（L1162） | 可选未采纳；保留当前 owner |
| A078 | [oaTOF/analysis/ideal_acceptance_300mm_simion_candidate.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/ideal_acceptance_300mm_simion_candidate.py) | 必改（限界）：保留已登记 Candidate CLI；已复现 live reference 改变同一父结果的物理输入，窄修父 experiment/reference 与 selected 绑定。base/grid 复用已验证父输入，publisher 去重不采纳。<br>收益：阻止历史selected结果混用当前物理reference；保持既有科学公式、CLI和publisher；代价/风险：增加两个父小输入record及显式configuration身份核验；历史输入缺失或漂移失败关闭，不允许live fallback。专属合成grid夹具仅验证输入接线，不声称真实数值或三维资格。 | [_load_frozen_parent_inputs](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/ideal_acceptance_300mm_simion_candidate.py)（L86）<br>[test_live_reference_change_does_not_change_frozen_source](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_ideal_acceptance_300mm_simion_candidate.py)（L86） | A078 父冻结输入／Agent 4 |
| A079 | [oaTOF/analysis/oatof_oaaccelerator_coupling.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/oatof_oaaccelerator_coupling.py) | 保留：OA局部模型从OA import，反射器从分析器owner import；整机耦合求根归分析器，无common上移理由。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [imports OA accelerator functions](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/oatof_oaaccelerator_coupling.py)（现 L23）<br>[test_coupled_root_matches_independent_scipy_solver](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_oatof_longitudinal_independent.py)（L176） | 保留决定；无新增实现要求 |
| A080 | [oaTOF/analysis/paper1_focusability.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/paper1_focusability.py) | 保留：cohort分配、源载入、模型训练与focusability分函数，detector-blind约束是问题定义，不能为短代码删掉。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [assign_detector_blind_cohorts](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/paper1_focusability.py)（现 L147）<br>[test_source_assessment_is_detector_blind_and_reports_c1_diagnostics](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_paper1_focusability.py)（L108） | 保留决定；无新增实现要求 |
| A081 | [oaTOF/analysis/publish_formal_release.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/publish_formal_release.py) | 保留：Formal晋升明确请求、exact asset roles、N1000验证、GUI审阅身份、不可覆盖现有release与专门recover事务；不可并入普通run成功publisher。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [validate_runs](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/publish_formal_release.py)（现 L106）<br>[test_success_publishes_atomic_release_and_updates_four_contracts](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_publish_formal_release.py)（L321） | 保留决定；无新增实现要求 |
| A082 | [oaTOF/analysis/reference_analysis_core.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/reference_analysis_core.py) | 可选：导入正规化、单分析、比较、作图已有函数；峰形核心已唯一委托common。analyze_comparison约341行可提取子阶段，但当前长度本身无正确性缺陷。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [common.analysis.peak_metrics import](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/reference_analysis_core.py)（现 L31）<br>[test_large_integer_csv_ids_survive_alias_override_hit_and_event_columns](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_peak_metrics.py)（L123） | 可选未采纳；保留当前 owner |
| A083 | [oaTOF/analysis/reflectron_dual_stage_solver.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/reflectron_dual_stage_solver.py) | 保留：反射器场解/时间导数/能量像差是一组连贯理论，独立积分与缩放参考覆盖已声明适用域，拆算法会增加跨文件状态。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [solve_reflectron_fields](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/reflectron_dual_stage_solver.py)（现 L182）<br>[test_reflectron_time_matches_direct_potential_integral](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_oatof_longitudinal_independent.py)（L149） | 保留决定；无新增实现要求 |
| A084 | [oaTOF/analysis/three_zone_ideal_root_solver.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/three_zone_ideal_root_solver.py) | 保留：RootBounds/Settings、Jacobian audit、Newton attempt、clustering与两/三区收集已经分函数；迭代状态属于一数值算法族。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [_build_audit](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/three_zone_ideal_root_solver.py)（现 L463）<br>[test_independent_state_oracle_matches_affine_manifold](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_three_zone_ideal_theory.py)（L115） | 保留决定；无新增实现要求 |
| A085 | [oaTOF/analysis/three_zone_ideal_theory.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/three_zone_ideal_theory.py) | 保留：文件明确重用OA三段局部理论，再加整机反射器与物理gate；owner边界已满足指南，不应合并项目。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [OA three-zone public theory imports](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/three_zone_ideal_theory.py)（现 L20）<br>[test_eta_zero_is_exact_two_zone_degeneration](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_three_zone_ideal_theory.py)（L189） | 保留决定；无新增实现要求 |
| A086 | [oaTOF/analysis/three_zone_t5_simion_candidate.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/three_zone_t5_simion_candidate.py) | 可选：Candidate编译/写出/发布已分函数，CLI调用完整common writer本身不是缺陷；portable publication与300mm版本重复，可合并。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [_frozen_primary](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/three_zone_t5_simion_candidate.py)（现 L115）<br>[test_compiles_exact_frozen_candidate_and_consumer_mapping](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_three_zone_t5_simion_candidate.py)（L176） | 可选未采纳；保留当前 owner |
| A087 | [oaTOF/analysis/three_zone_theory_experiment.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/three_zone_theory_experiment.py) | 保留：stage graph、前置receipt、计划hash与数值执行独立，有意保持科学漏斗而非通用workflow系统。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [load_campaign](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/three_zone_theory_experiment.py)（现 L113）<br>[test_stage_graph_is_single_stage_only_and_t4c_is_manual_non_default](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_three_zone_theory_experiment.py)（L93） | 保留决定；无新增实现要求 |
| A088 | [oaTOF/analysis/three_zone_theory_numeric_execution.py](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/three_zone_theory_numeric_execution.py) | 保留：数值执行已由有界root audit/row evaluation/ranking/各stage函数组成，common peak_metrics已复用；无剖析证据要求并行或按1134行拆。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [_post_root_audits](../../projects/single_reflection_oa_tof_mass_analyzer/analysis/three_zone_theory_numeric_execution.py)（现 L257）<br>[test_root_branch_policy_never_selects_by_first_success_or_performance](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_three_zone_theory_experiment.py)（L146） | 保留决定；无新增实现要求 |
| A089 | [oaTOF/comsol/oatof_build_model_core.m](../../projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_model_core.m) | 可选：单model owner必要；当前函数含大量历史解释注释和真实geometry/field/particle边界，1280行不是1280行复杂控制流。可按vendor阶段提局部函数，但收益需抵偿真实COMSOL回归成本。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [oatof_build_model_core](../../projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_model_core.m)（现 L1）<br>[prepare](../../projects/single_reflection_oa_tof_mass_analyzer/tests/comsol/OaTofArtifactContextTest.m)（L7） | 可选未采纳；保留当前 owner |
| A090 | [oaTOF/simion/workbench/formal/oatof_resolved.lua](../../projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/formal/oatof_resolved.lua) | 保留：首行明确由resolved_geometry.json生成，主体是数据；不能手拆、手改或把该物理行数当程序复杂度。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [Generated from config/resolved_geometry.json; do not edit](../../projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/formal/oatof_resolved.lua)（现 L1）<br>[test_candidate_generates_nonformal_simion_text_from_frozen_contract](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_candidate_design.py)（L694） | 保留决定；无新增实现要求 |
| A091 | [oaTOF/workflows/design_candidate/run_candidate_workflow.py](../../projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py) | 必改（限界）：沿既有 candidate/stage reuse 接公共 owner，保留阶段原错；不新增恢复入口或物理配置。<br>收益：补齐已存在正式入口的错误保留、身份或终态合同，防止错误复用/错误结果外观；代价/风险：必须覆盖真实driver的软件负例、双故障和资源收尾；若触及solver阶段/原生产物，再做对应真实solver验证。 | [execute_prepared_run](../../projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py)（L1249）<br>[test_real_public_owner_runs_prepared_candidate_in_one_admitted_root](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_candidate_design.py)（L257）<br>[test_stage_completion_preserves_actual_failure_and_never_fills_unknown_facts](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_candidate_design.py)（L161） | Agent 公共 owner／Agent 1 |
| A092 | [oaTOF/workflows/radial_compaction/run_campaign.py](../../projects/single_reflection_oa_tof_mass_analyzer/workflows/radial_compaction/run_campaign.py) | 必改（限界）：以显式父 run、新身份、冻结输入、完整已绑定 Fly 单元复用和公共 owner 闭合恢复；禁止裸文件资格及无依据 1800 s kill。真实 P1–P3 handoff 与 P4 最终父恢复已验收，范围见主报告；GUI 按用户取消。<br>收益：补齐已存在正式入口的错误保留、身份或终态合同，防止错误复用/错误结果外观；代价/风险：必须覆盖真实driver的软件负例、双故障和资源收尾；若触及solver阶段/原生产物，再做对应真实solver验证。 | [execute_prepared_run](../../projects/single_reflection_oa_tof_mass_analyzer/workflows/radial_compaction/run_campaign.py)（L1391）<br>[test_full_replay_avoids_solver_grants_and_passes_public_writer_contract](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_radial_compaction_campaign.py)（L600） | A092 恢复、PA handoff、Agent／Agent 1/4 |
| A093 | [电子枪/analysis/resolve_contract.py](../../projects/transverse_helical_filament_wehnelt_electron_gun/analysis/resolve_contract.py) | 保留：baseline/mode/派生分别有函数，通用strict_json和粒子常数已共享；电子枪物理字段/模式仍项目唯一owner。300行validator可按字段族整理，但不是必改缺陷。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [common strict_json primitives](../../projects/transverse_helical_filament_wehnelt_electron_gun/analysis/resolve_contract.py)（现 L16）<br>[test_resolver_runs_with_only_frozen_shared_dependencies](../../projects/transverse_helical_filament_wehnelt_electron_gun/tests/analysis/test_resolve_contract.py)（L60） | 保留决定；无新增实现要求 |
| B001 | [common/contracts/test_legacy_capacity_calibration.py](../../common/contracts/test_legacy_capacity_calibration.py) | 保留：保留calibration迁移与负例；只为A006/A002实际修改加必要用例。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：未测到模块瓶颈前不按长度分片。 | [test_calibration_binds_sealed_generic_owner_disposition](../../common/contracts/test_legacy_capacity_calibration.py)（L184） | 保留决定；无新增实现要求 |
| B002 | [common/contracts/test_reconcile_artifact_capacity.py](../../common/contracts/test_reconcile_artifact_capacity.py) | 必改（限界）：原问题／必要回归：A004日常authority迁移时测试应打到真正daily API，历史发现用例仍在legacy owner。<br>收益：消除已定位职责或恢复缺口；代价/风险：提fixture/拆class本身可选；不要复制大fixture或删除symlink/同大小替换/恢复负例。 | [test_legacy_owner_rejects_daily_requests_without_discovery](../../common/contracts/test_reconcile_artifact_capacity.py)（L114） | C2/D1／A004 |
| B003 | [common/contracts/test_run_artifact_support.ps1](../../common/contracts/test_run_artifact_support.ps1) | 必改（限界）：原问题／必要回归：A008 host cleanup错误传播修复需要证明原错和回执保留、host释放失败不继续维护；现有stub只把release写为空函数。<br>收益：覆盖真实错误保留缺口，防止fail-closed流程因保留receipt反而误继续；代价/风险：低：有限stub行为臂，已有11真实PS/CLI压力臂保留，不重复整套成本。 | [test_host_release_failure_preserves_original_error_and_stops_pressure_recovery](../../common/contracts/test_capacity_reconcile_runtime.py)（L38） | Agent／A008 |
| B004 | [common/contracts/test_run_capacity_lifecycle.py](../../common/contracts/test_run_capacity_lifecycle.py) | 保留＋配套必测：随自动reseal补只重试seal、不重删与身份保护用例。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：现有lifecycle分组不必拆文件。 | [test_automatic_reseal_publication_failure_recovers_without_repeating_deletion](../../common/contracts/test_run_capacity_lifecycle.py)（L230） | C1/C3 必要回归 |
| B005 | [common/contracts/test_solver_review_retirement.py](../../common/contracts/test_solver_review_retirement.py) | 保留＋配套必测：wrapper行为改变需真实TEMP执行证明自动seal与故障恢复；保留底层第二批拒绝。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：repair/retirement拆模块可选，按实际耗时/路由收益决定。 | [test_wrapper_real_two_partial_batches_reseal_without_manual_step](../../common/contracts/test_solver_review_retirement.py)（L200） | C3 必要回归 |
| B006 | [common/contracts/test_verify_artifact_layout.py](../../common/contracts/test_verify_artifact_layout.py) | 保留＋配套必测：随H4补默认zero payload/deep计数/篡改拒绝/窄entry仍full；补合法parity零默认载荷读取、额外树成员、四类junction、casefold碰撞及历史generation仅metadata行为。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：按layout/cache分class或文件只是可选组织。 | [test_common_layout_reads_metadata_by_default_and_deep_audit_rejects_same_size_change](../../common/contracts/test_verify_artifact_layout.py)（L279）<br>[test_common_layout_accepts_published_parity_without_default_payload_reads](../../common/contracts/test_verify_artifact_layout.py)（L298）<br>[test_common_layout_rejects_recovery_directory_reparse_points](../../common/contracts/test_verify_artifact_layout.py)（L350） | H4 必要回归 |
| B007 | [common/contracts/test_verify_changed.py](../../common/contracts/test_verify_changed.py) | 保留：现1195行、45个test方法。路由数据/源码结构断言、PlanOnly与真实入口行为混合，但它们目标不同且已有行为补充；不能把源码字符串断言当实际门禁证明，也不能因文件长度删测试。第一波新增7项重型/namespace/import环境行为已在独立test_changed_test_selection模块，避免继续扩大本文件。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：不迁移；维护现有负例，避免新增依赖及语义漂移 | [test_ready_dependencies_fail_fast_and_natural_completion](../../common/contracts/test_parallel_gate_support.py)（L31） | G1–G4 |
| B008 | [common/integration/test_resolve_connection.py](../../common/integration/test_resolve_connection.py) | 保留：已有normalized/raw identity、gap/overlap及真实ValidateOnly公共入口正负例。<br>收益：维持连接身份与几何合同覆盖；代价/风险：不拆分、不重复执行；仅未来生产变更跑相关合同。 | [test_direct_mating_translation_is_derived_from_both_port_centers](../../common/integration/test_resolve_connection.py)（L29） | 保留决定；无新增实现要求 |
| B009 | [common/simion/test_pa_family_cache.py](../../common/simion/test_pa_family_cache.py) | 可选：测试与A017事务owner相对应；没有测得独立路由收益，不能单因长测试文件要求拆分。<br>收益：在A017真改边界时可按事务/repair/materialize选择更小回归范围；代价/风险：高：fixture共享、故障注入、动态路由和CLI调用可能被误遗漏。 本轮仅采用右列具名包，结构拆分不采纳。 | [test_abandon_empty_transaction_preserves_failure_and_reconciles_without_deletion](../../common/simion/test_pa_family_cache.py)（L161） | 已选 A092 cache 回归；不拆文件 |
| B010 | [common/simion/test_short_pa_path_support.py](../../common/simion/test_short_pa_path_support.py) | 可选：H1 已选做连续 guard 交接及读量回归；保留原 Windows 写/删/替换阻挡，结构拆分仍未采纳。<br>收益：连续 guard 交接减少重复读取，同时保留源/目标身份与写入阻挡；代价/风险：中：真实Windows小进程用例加读量计数；大PA验收另算，不能省掉慢过程来宣称优化。 本轮仅采用右列具名包，结构拆分不采纳。 | [test_published_copy_hands_off_verified_handle_without_second_payload_read](../../common/simion/test_short_pa_path_support.py)（L49） | 已选 H1/H2 回归 |
| B011 | [common/test_host_resource_scheduler.py](../../common/test_host_resource_scheduler.py) | 保留：多birth修复已有纯fixture与Windows长期回归，保持。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：R1投影测放既有resource_budget测试；正预算并发测随解除heavy互斥一起，不重复无关CIM全套。 | [test_more_than_three_stale_snapshots_resample_then_succeed](../../common/test_host_resource_scheduler.py)（L67） | 保留决定；无新增实现要求 |
| B012 | [integrations/tests/frontend_fixtures.py](../../integrations/tests/frontend_fixtures.py) | 保留：fixture保持测试专用且调用真实编译器；共享factory已存在。<br>收益：避免物理公式被复制进测试替身或生产反向导入测试；代价/风险：无必要迁移；跨test factory移位仅在实际sharding时有收益。 | [canonical_frontend_fixture](../../integrations/tests/frontend_fixtures.py)（L25） | 保留决定；无新增实现要求 |
| B013 | [integrations/tests/test_accelerator_interface.py](../../integrations/tests/test_accelerator_interface.py) | 保留：已有native前guard顺序、terminal/capacity分离和detached snapshot行为。<br>收益：保护真正边界而非源码文本形状；代价/风险：无必要迁移；拆分需路由证据。 | [test_actual_iob_entry_verifies_live_assets_once_after_guards_and_before_vendor](../../integrations/tests/test_accelerator_interface.py)（L40） | 保留决定；无新增实现要求 |
| B014 | [integrations/tests/test_cooled_frontend.py](../../integrations/tests/test_cooled_frontend.py) | 保留：已验证metadata hit、冻结parent消费、同出生几何时钟以及七个实际owner句柄。<br>收益：保留H2优化不可破坏的已有保护证据；代价/风险：无必要迁移；重复全运行不带来新证据。 | [test_saved_workbench_requires_public_pin_but_field_metadata_does_not](../../integrations/tests/test_cooled_frontend.py)（L148） | 保留决定；无新增实现要求 |
| B015 | [integrations/tests/test_dependencies.py](../../integrations/tests/test_dependencies.py) | 保留：已有detached Python/pwsh执行、缺resource与改hash拒绝，不缺独立冻结消费者门禁。<br>收益：用实际脱离checkout执行验证依赖闭包；代价/风险：保持现状；A027等真移动代码时更新既有闭包记录并运行对应用例，非必须拆此测试文件。 | [test_single_reflection_workflow_imports_form_a_dag](../../integrations/tests/test_dependencies.py)（L25） | 保留决定；无新增实现要求 |
| B016 | [integrations/tests/test_local_frontend_workflow.py](../../integrations/tests/test_local_frontend_workflow.py) | 保留：一次source identity、只消费冻结parent、同出生非零时钟已有明确行为断言。<br>收益：提供H5已满足子链证据，防止过度合并校验；代价/风险：无必要迁移。 | [test_real_frozen_geometry_keeps_native_cache_fingerprint](../../integrations/tests/test_local_frontend_workflow.py)（L167） | 保留决定；无新增实现要求 |
| B017 | [integrations/tests/test_oa_mr_execute.py](../../integrations/tests/test_oa_mr_execute.py) | 必改（限界）：随 A023 验证实际 finally 多故障与原错保留；已有 terminal/继承 lease 测试保留，不以源码顺序替代行为。<br>收益：证明原native错误与后续release/seal事实均保留；代价/风险：中：少量真实PS边界fixture，可复用既有stage harness，不跑求解器。 | [test_closeout_preserves_primary_error_and_isolates_safe_owner_actions](../../integrations/tests/test_oa_mr_execute.py)（L1219） | Agent／A023 |
| B018 | [integrations/tests/test_paired_accelerator_static_field_execute.py](../../integrations/tests/test_paired_accelerator_static_field_execute.py) | 保留：已覆盖完整static export无需vendor、腐坏拒绝及真实finally release/seal顺序。<br>收益：保护已满足的恢复与owner边界；代价/风险：无必要迁移；仅factory分享无新增正确性收益。 | [test_sample_coordinates_round_trip_exactly_and_reject_a_true_ulp_change](../../integrations/tests/test_paired_accelerator_static_field_execute.py)（L42） | 保留决定；无新增实现要求 |
| B019 | [integrations/tests/test_single_reflection_execute.py](../../integrations/tests/test_single_reflection_execute.py) | 可选：现有public managed/native stage fixture完整；H1交接的新测试仅依赖可选优化被选中。<br>收益：如H1实施，证明源/目标权威读量下降而实际IOB/replay行为不变；代价/风险：中：复用既有fixture添加计数/交接臂；真实PA工具验收不能用合成marker替代。 本轮仅采用右列具名包，结构拆分不采纳。 | [test_iob_copy_initializer_hands_off_guard_before_capacity_debit](../../integrations/tests/test_single_reflection_execute.py)（L25） | 已选 H1 消费回归 |
| B020 | [integrations/tests/test_single_reflection_field_stage.py](../../integrations/tests/test_single_reflection_field_stage.py) | 保留：已有metadata零payload、published两域六member零native及容量拒绝停止native的行为。<br>收益：维持H2已有满足部分，不重复制造新抽象；代价/风险：无必要迁移；H2 selector真改时新增小receipt校验和一次payload消费断言。 | [test_instance_rename_and_reorder_preserve_full_and_local_native_plans](../../integrations/tests/test_single_reflection_field_stage.py)（L41） | 保留决定；无新增实现要求 |
| B021 | [integrations/tests/test_single_reflection_preparation.py](../../integrations/tests/test_single_reflection_preparation.py) | 可选：A026本身可靠且分解可选；原测试已有one-sampler/one-CSV及source/clock/非连续续跑负例。<br>收益：仅在A026真改时分组可能有路由成本收益；代价/风险：中：需维护现有fixture与选择路由，不能丢identity负例。 未据长度采纳结构改造。 | [test_retired_provider_schema_is_rejected_without_mutating_input](../../integrations/tests/test_single_reflection_preparation.py)（L318） | 可选未采纳；保留当前 owner |
| B022 | [integrations/tests/test_single_reflection_program.py](../../integrations/tests/test_single_reflection_program.py) | 保留：已有真实plain-Lua callback、点/域选择、RF时钟和held-off行为；不是只断言字符串。<br>收益：保持供应商程序的真实回调语义证据；代价/风险：无必要迁移；外置模板才需要新字节/缺模板验证。 | [test_native_requires_complete_finite_explicit_source_velocity](../../integrations/tests/test_single_reflection_program.py)（L98） | 保留决定；无新增实现要求 |
| B023 | [integrations/tests/test_single_reflection_runtime.py](../../integrations/tests/test_single_reflection_runtime.py) | 必改（限界）：原问题／必要回归：A027修实际依赖环需要独立导入runtime/continuation/collect并验证冻结消费者仍可运行；既有metadata和一次context行为必须保持。<br>收益：防止修环造成隐藏动态依赖缺失或恢复证据语义改变；代价/风险：中：窄导入/continuation/collect行为加既有detached测试；不要求重跑真实物理求解。 | [test_frozen_source_drift_and_missing_snapshot_module_have_no_repo_fallback](../../integrations/tests/test_single_reflection_runtime.py)（L590） | A2／A027 |
| B024 | [IP/tests/test_functional.py](../../projects/dual_pressure_rectilinear_ion_processor/tests/test_functional.py) | 可选：源/clock/完整母群/坐标变换/冻结closure与分析拒绝路径是同一功能合同；已有event_fixture与prepare factory。仅按792行拆不能证明更快。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [event_fixture](../../projects/dual_pressure_rectilinear_ion_processor/tests/test_functional.py)（现 L65） | 可选未采纳；保留当前 owner |
| B025 | [IP/tests/test_gui_replay_plan.py](../../projects/dual_pressure_rectilinear_ion_processor/tests/test_gui_replay_plan.py) | 保留：已分CoordinateTests与GuiReplayPlanTests，覆盖private PA、引用样本不copy、native field与手工GUI声明边界；不是实际GUI自动验收。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [CoordinateTests](../../projects/dual_pressure_rectilinear_ion_processor/tests/test_gui_replay_plan.py)（现 L21） | 保留决定；无新增实现要求 |
| B026 | [MR/tests/analysis/test_bunch_source_and_schedule.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_bunch_source_and_schedule.py) | 可选：额外plan测试只服务可选A031拆分；原source/schedule测试已具独立参考。<br>收益：若改plan则能证物化一致；代价/风险：低中：新增case和fixture管理。 未据长度采纳结构改造。 | [_write_provider_receipt](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_bunch_source_and_schedule.py)（L204） | 可选未采纳；保留当前 owner |
| B027 | [MR/tests/analysis/test_corridor_field_provider.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_corridor_field_provider.py) | 保留：保留corridor/source身份与no-solve证明。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：只有实际共同合同迁移才改import；分COMSOL adapter测试需耗时证据。 | [test_frozen_provider_imports_from_public_root_context](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_corridor_field_provider.py)（L23） | 保留决定；无新增实现要求 |
| B028 | [MR/tests/analysis/test_downstream_fixed_grid_workpoint.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_downstream_fixed_grid_workpoint.py) | 必改（限界）：原问题／必要回归：A032实际依赖环修复必须以现有field/identity/轻恢复行为确认，不能仅靠导入位置断言。<br>收益：证明同一投影搬owner后科学与轻证据恢复不变；代价/风险：低中：主要复用原fixture，新增最小导入/身份检查。 | [test_native_source_validation_keeps_precedence_and_layout_read_order](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_downstream_fixed_grid_workpoint.py)（L37） | A2／A032 |
| B029 | [MR/tests/analysis/test_downstream_workpoint_iteration.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_downstream_workpoint_iteration.py) | 必改（限界）：原问题／必要回归：A1/A2必修变更涉及decision和verified inputs；需要同输入同序列及负例来防止改变科学结果。<br>收益：给必须迁移提供直接parity证据；代价/风险：中：新动作矩阵但复用现有prism/stripe fixtures。 | [test_measured_acquisition_uses_public_request_and_never_changes_source_energy](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_downstream_workpoint_iteration.py)（L40） | A1/A2 |
| B030 | [MR/tests/analysis/test_downstream_workpoint_iteration_runner.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_downstream_workpoint_iteration_runner.py) | 必改（限界）：原问题／必要回归：A1实际状态/外部调用边界改变，开发标准386–387要求行为fixture；source count不能证明预算/中断/恢复。<br>收益：证明pending写入、child执行一次、失败传播与release；代价/风险：中高：真实PS轻fixture存在进程开销；应复用而非全仓复制。 | [test_recovery_round_json_transport_preserves_probe_order_debits_and_terminal_resume](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_downstream_workpoint_iteration_runner.py)（L184） | A1 runner |
| B031 | [MR/tests/analysis/test_dual_stripe_l0_math.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_dual_stripe_l0_math.py) | 保留：已有独立数学参考，必要A035type移动不要求修改本文件（当前未直接引用该type）。<br>收益：保留数值参考可信性；代价/风险：无新测试成本。 | [test_gauss_legendre_rule_is_cached_read_only_and_exact_for_cubic](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_dual_stripe_l0_math.py)（L207） | 保留决定；无新增实现要求 |
| B032 | [MR/tests/analysis/test_ip_prism_distance_study.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_ip_prism_distance_study.py) | 可选：正式study已有verify/seal；只有选择可选完整publication API迁移才需新增该consumer测试。现有五组测试组织已清楚。<br>收益：迁移时能保证publicAPI失败语义；代价/风险：中：真实lifecycle fixture需明确TEMP与状态归属。 未据长度采纳结构改造。 | [RecordedContourAnalysisTests](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_ip_prism_distance_study.py)（L466） | 可选未采纳；保留当前 owner |
| B033 | [MR/tests/analysis/test_joint_flight_preparation.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_joint_flight_preparation.py) | 必改（限界）：原问题／必要回归：A2去反向integration验证依赖会改变本模块patch的接口，需要真实record边界证据来避免用mock掩盖身份遗漏。<br>收益：保证修改依赖方向时没有削弱source/field/clock检验；代价/风险：中：构造一套真实小manifest fixture；无需大solver。 | [test_reference_json_binds_real_compiler_and_derives_timeout_without_lua_numerics](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_joint_flight_preparation.py)（L148） | A2 记录消费 |
| B034 | [MR/tests/analysis/test_joint_mirror_stripe_l0.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_joint_mirror_stripe_l0.py) | 保留：纯理论测试已有独立analytic/constraint参考和窄_trial factory。<br>收益：避免减少独立期望或改容差；代价/风险：无迁移必要。 | [test_rounded_fast_phase_endpoint_matches_linear_analytic_count](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_joint_mirror_stripe_l0.py)（L43） | 保留决定；无新增实现要求 |
| B035 | [MR/tests/analysis/test_mrtof_batch_continuation.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_mrtof_batch_continuation.py) | 保留：已有真实complete/incomplete batch/newrun identity恢复证据；没有新行为缺口被本轮证明。<br>收益：现有恢复API无需第二实现；代价/风险：无新测试成本。 | [_prepared_joint_fixture](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_mrtof_batch_continuation.py)（L19） | 保留决定；无新增实现要求 |
| B036 | [MR/tests/analysis/test_native_candidate_campaign_runner.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_native_candidate_campaign_runner.py) | 必改（限界）：随 A1 验证完整 composition plan/scope 参数转发、冻结身份与完整候选比较；旧 stub 不再作为真实绑定的唯一证据。<br>收益：直接防止本次真实入口缺陷复发；代价/风险：低中：一个默认binding/冻结身份fixture及既有ranking parity，无solver。 | [test_comparison_projects_complete_candidate_metrics_and_best](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_native_candidate_campaign_runner.py)（L798） | A1 campaign |
| B037 | [MR/tests/analysis/test_native_candidate_chain_runner.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_native_candidate_chain_runner.py) | 必改（限界）：原问题／必要回归：A050必修科学policy迁移必须验证warning/next-action与真实调用边界；source.index不能证明调用顺序。<br>收益：保护TE1 completed复用与资格顺序；代价/风险：中：复用已有_field_dispatch fixture，少量root trace。 | [test_actual_root_feedback_keeps_one_request_and_matching_best_identity](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_native_candidate_chain_runner.py)（L19） | A1 chain |
| B038 | [MR/tests/analysis/test_native_corridor_bunch_screening_runner.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_native_corridor_bunch_screening_runner.py) | 可选：补真实cohort no-refly测试有价值，但当前筛选入口未在必修改动范围，本轮也未找到其行为缺陷；不能因source assertions存在就强制全改。<br>收益：提高no-refly和partialbatch回归置信度；代价/风险：中：真实入口轻fixture有启动/租约开销，重复现有batch tests可能收益有限。 未据长度采纳结构改造。 | [test_new_child_is_strict_but_read_only_evidence_accepts_complete_identity_pairs](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_native_corridor_bunch_screening_runner.py)（L20） | 可选未采纳；保留当前 owner |
| B039 | [MR/tests/analysis/test_native_static_field_provider.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_native_static_field_provider.py) | 保留＋配套必测：仅按文件长拆request/prepare/IP场景可选。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：A044真实closeout行为改动所需恢复/不再Refine测试must；共享fixture可减少重复，但避免新跨测试耦合。 | [test_published_provider_seal_failure_uses_existing_cli_without_native_reentry](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_native_static_field_provider.py)（L1778） | A044 closeout 必测；拆分可选 |
| B040 | [MR/tests/analysis/test_prepared_joint_trial.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_prepared_joint_trial.py) | 必改（限界）：原问题／必要回归：A046依赖方向变化必须保留真实prepared manifest/record校验及非连续ID/clock，现有多处patch可能掩盖这层。<br>收益：防止移除reverse import时把verified变成未验证标记；代价/风险：中高：真实小fixture可复用，现有大case不必全部拆。 | [test_prepared_component_import_and_reference_do_not_load_integration_cli](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_prepared_joint_trial.py)（L21） | A2／A046 |
| B041 | [MR/tests/analysis/test_resolved_cad_export.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_resolved_cad_export.py) | 保留：保留CAD接触、冷读、失败publication语义。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：A036没有必要结构改动时不拆832行测试。 | [test_tilted_mirror_uses_resolved_polygons_and_slots_not_bounds](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_resolved_cad_export.py)（L83） | 保留决定；无新增实现要求 |
| B042 | [MR/tests/analysis/test_simion_candidate_reference.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_simion_candidate_reference.py) | 保留：reference与profile已有分组、独立期望及owner委托测试。<br>收益：稳定科学与provider边界；代价/风险：不改无额外成本。 | [test_mr_delegates_accelerator_electrode_topology_to_component_owner](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_simion_candidate_reference.py)（L196） | 保留决定；无新增实现要求 |
| B043 | [MR/tests/analysis/test_simion_event_analysis.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_simion_event_analysis.py) | 可选：当前科学事件/母cohort/峰/collision测试保持。<br>收益：消除已定位职责或恢复缺口；代价/风险：拆组可提升定位但增加fixture导入/路由；只有实际A053改动才迁消费者回归。 未据长度采纳结构改造。 | [test_histogram_span_preserves_disconnected_bins_and_declares_its_method](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_simion_event_analysis.py)（L141） | 可选未采纳；保留当前 owner |
| B044 | [MR/tests/analysis/test_source_z_energy_timing_diagnostic.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_source_z_energy_timing_diagnostic.py) | 保留＋配套必测：pure TE1/fixture分模块可选。<br>收益：保持唯一 authority、既有身份及失败关闭边界；代价/风险：若A1决策归Python则补选优/qualification/clock/peak负边界；别删除source loss/clock字段简化fixture。 | [test_campaign_full_projection_matches_original_powershell](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_source_z_energy_timing_diagnostic.py)（L1915） | A1 必要回归；分组可选 |
| B045 | [MR/tests/analysis/test_static_field_binding.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_static_field_binding.py) | 可选：绑定消费、真实subprocess/Lua mock及退休缺payload边界继续保留。<br>收益：消除已定位职责或恢复缺口；代价/风险：A055为可选时测试拆分也非must；只有接收共同合同方案才同步imports，避免重复largefixture。 本轮仅采用右列具名包，结构拆分不采纳。 | [test_actual_joint_payloads_are_verified_once_and_conflicts_or_drift_rejected](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_static_field_binding.py)（L32） | A032 必要接线；大拆分不采纳 |
| B046 | [MR/tests/analysis/test_two_prism_segmented_transport.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_two_prism_segmented_transport.py) | 可选：numeric string矩阵是选择可选finite复用时的必需验收，当前没有实际converter故障。<br>收益：能证明同义而非放宽输入；代价/风险：低：有限输入matrix；既有transport math保留。 未据长度采纳结构改造。 | [test_voltage_pair_evaluator_preserves_signed_source_and_two_residuals](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_two_prism_segmented_transport.py)（L341） | 可选未采纳；保留当前 owner |
| B047 | [MR/tests/analysis/test_two_prism_simion_trial.py](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_two_prism_simion_trial.py) | 可选：额外plan/event parity只服务可选A060大分层；现有真实materialize/analyze fixtures与负例已多。<br>收益：若以后动trial边界则有明确parity证据；代价/风险：中高：CLI和多源模式回归量大，收益依赖实际生产改动。 未据长度采纳结构改造。 | [_materialize_static_stripe_fixture](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_two_prism_simion_trial.py)（L80） | 可选未采纳；保留当前 owner |
| B048 | [RF/tests/analysis/test_comsol_workflow_architecture_contract.py](../../projects/rf_multipole_ion_optics/tests/analysis/test_comsol_workflow_architecture_contract.py) | 可选：已有真实precommercial failed-triplet软件行为测试，但568-593仍只用token/index检查生命周期顺序；应在触及相关实现时以行为断言补强，不机械删除必要禁止规则。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 本轮仅采用右列具名包，结构拆分不采纳。 | [test_transport_closure_and_host_errors_preserve_original_failure](../../projects/rf_multipole_ion_optics/tests/analysis/test_comsol_workflow_architecture_contract.py)（L712） | Agent RF 失败回归 |
| B049 | [RF/tests/analysis/test_frozen_particle_policy_package.py](../../projects/rf_multipole_ion_optics/tests/analysis/test_frozen_particle_policy_package.py) | 保留：frozen namespace/analysis package isolation/真实独立Python不依赖live PYTHONPATH的测试有明确必要性；长fixture不是重复生产机制。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [one frozen analysis package test](../../projects/rf_multipole_ion_optics/tests/analysis/test_frozen_particle_policy_package.py)（现 L100） | 保留决定；无新增实现要求 |
| B050 | [RF/tests/analysis/test_same_solver_numerical_convergence.py](../../projects/rf_multipole_ion_optics/tests/analysis/test_same_solver_numerical_convergence.py) | 可选：make_run/copy_portable_closure等大量证据构造是same-solver negative身份矩阵，独立公开CLI评估保持必要；不应删覆盖换短文件。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [copy_portable_closure](../../projects/rf_multipole_ion_optics/tests/analysis/test_same_solver_numerical_convergence.py)（现 L158） | 可选未采纳；保留当前 owner |
| B051 | [RF/tests/analysis/test_simion_transport_runner_source.py](../../projects/rf_multipole_ion_optics/tests/analysis/test_simion_transport_runner_source.py) | 可选：虽然文件叫_source，已有真实pwsh pre-solver失败和host permission行为；不能全称字符串测试。956-980的执行/科学判定仍是源token/order断言。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 本轮仅采用右列具名包，结构拆分不采纳。 | [host permission lifecycle without solver](../../projects/rf_multipole_ion_optics/tests/analysis/test_simion_transport_runner_source.py)（现 L138） | Agent RF 失败回归 |
| B052 | [RF/tests/analysis/test_workflow_architecture_contract.py](../../projects/rf_multipole_ion_optics/tests/analysis/test_workflow_architecture_contract.py) | 可选：依赖方向、禁重复runtime mechanism与禁止production→tests是有效静态规则；具体函数调用token和source排布不能独立证明运行语义。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [no production tests dependency](../../projects/rf_multipole_ion_optics/tests/analysis/test_workflow_architecture_contract.py)（现 L157） | 可选未采纳；保留当前 owner |
| B053 | [RF/tests/domain/test_numerical_qualification.py](../../projects/rf_multipole_ion_optics/tests/domain/test_numerical_qualification.py) | 保留：样本/工程合同factory加数值资格负例矩阵明确，覆盖changed-only numerical axis、ID/physics漂移和禁止进展；每类判据不能简单合并。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [sample fixture](../../projects/rf_multipole_ion_optics/tests/domain/test_numerical_qualification.py)（现 L27） | 保留决定；无新增实现要求 |
| B054 | [RF/tests/domain/test_particle_source_preflight.py](../../projects/rf_multipole_ion_optics/tests/domain/test_particle_source_preflight.py) | 保留：source projection已明确一次读、hash/parse同源、frozen独立CLI；良好覆盖H5而不是待重新实现的重复代码。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [materializes once and batch frozen identity](../../projects/rf_multipole_ion_optics/tests/domain/test_particle_source_preflight.py)（现 L178） | 保留决定；无新增实现要求 |
| B055 | [RF/tests/domain/test_resource_budget.py](../../projects/rf_multipole_ion_optics/tests/domain/test_resource_budget.py) | 可选：同一ResourceBudgetTests含纯contract validation、Windows采样/真实pwsh children、并发worker调度和process-tree观测；适合按依赖分组但无证据表明物理拆文件必然提速。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 本轮仅采用右列具名包，结构拆分不采纳。 | [test_process_snapshot_preserves_complete_family_sample](../../projects/rf_multipole_ion_optics/tests/domain/test_resource_budget.py)（L750） | R1 必要回归；不按长度拆分 |
| B056 | [RF/tests/domain/test_simion_runner_contract.py](../../projects/rf_multipole_ion_optics/tests/domain/test_simion_runner_contract.py) | 可选：覆盖primary/control、单heavy lease、cache/reuse/resource身份和scientific status；既有多处行为test应保留。560从另一个test模块取geometry factory是可收敛的测试结构依赖。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [complete scientific negative result](../../projects/rf_multipole_ion_optics/tests/domain/test_simion_runner_contract.py)（现 L39） | 可选未采纳；保留当前 owner |
| B057 | [RF/tests/domain/test_transport_campaign.py](../../projects/rf_multipole_ion_optics/tests/domain/test_transport_campaign.py) | 保留：campaign/profile/schema/permission/path与预算字段的明确选择矩阵有factory，dry-run不写artifacts测试为Agent入口提供证据。<br>收益：保留明确领域owner、科学身份与独立参考覆盖，避免无依据重写；代价/风险：本结论限所列建议和代码合同，不表示所有未审路径无缺陷；未来行为变化仍需对应回归。 | [campaign_fixture](../../projects/rf_multipole_ion_optics/tests/domain/test_transport_campaign.py)（现 L31） | 保留决定；无新增实现要求 |
| B058 | [oaTOF/tests/analysis/test_candidate_design.py](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_candidate_design.py) | 可选：指南将该文件概括为数学/物理边界不够完整：它还包含publication/crash replay、real driver fake executor、frozen source与native stage reuse大量生命周期测试。2114行不构成必须拆分。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 本轮仅采用右列具名包，结构拆分不采纳。 | [test_integrated_runner_success_closes_one_root_manifest](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_candidate_design.py) | A091/A092 必要回归；保留组织 |
| B059 | [oaTOF/tests/analysis/test_peak_metrics.py](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_peak_metrics.py) | 可选：已用common peak_metrics，三个TestCase覆盖数学、CSV词法ID与source/paired bootstrap；独立统计样例和大量负例不能删。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [PeakMetricsTest](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_peak_metrics.py)（现 L42） | 可选未采纳；保留当前 owner |
| B060 | [电子枪/tests/analysis/test_matlab_contract_binding.py](../../projects/transverse_helical_filament_wehnelt_electron_gun/tests/analysis/test_matlab_contract_binding.py) | 可选：含MATLAB文本合同、PS AST抽取函数行为和frozen gate subprocess；字符串fixture体积不等于算法复杂度，且AST片段不覆盖完整script作用域/真实vendor。<br>收益：改善职责/可测性或减少已确认机制重复；没有承诺计时收益；代价/风险：新增跨模块依赖、frozen closure变更与数值/供应商回归成本；只有语义等价和实际路由/测量证据支持时采用。 未据长度采纳结构改造。 | [invoke_runner_functions parses AST fragments](../../projects/transverse_helical_filament_wehnelt_electron_gun/tests/analysis/test_matlab_contract_binding.py)（现 L48） | 可选未采纳；保留当前 owner |

## 附录二：37 个门禁路由逐项决定

路由保留其现有科学/机制职责；完整运行的状态、测试数量与耗时由主报告引用同一最终证据，不在本表伪填通过。

| ID | 当前 stage／catalog 定位 | 执行等级与前置 | 审查决定与利弊 | 基线差异及实际入口 |
|---|---|---|---|---|
| C001 | [host_resource_scheduler_tests](../../common/gate_catalog.json)（L6） | fast／locked<br>无显式前置 | 保留共享 scheduler/bridge 与 PID birth、孤儿和误复用负例；收益为资源身份可信，代价为真实进程夹具耗时。 | 相对基线：无字段变化<br>[test_host_resource_scheduler.py](../../common/test_host_resource_scheduler.py), [test_host_resource_python.py](../../common/test_host_resource_python.py) |
| C002 | [host_resource_adapter_tests](../../common/gate_catalog.json)（L50） | fast／stdlib<br>无显式前置 | 保留实际 PowerShell adapter/lease 合同；stdlib 不代表零进程成本。 | 相对基线：无字段变化<br>[test_host_execution_lease.ps1](../../common/test_host_execution_lease.ps1) |
| C003 | [livelink_resource_stages_tests](../../common/gate_catalog.json)（L80） | fast／stdlib<br>无显式前置 | 保留 COMSOL 资源适配回归；收益为阶段/原错/释放语义，软件 PASS 不代表真实 COMSOL 求解。 | 相对基线：无字段变化<br>[test_livelink_resource_stages.py](../../common/comsol/test_livelink_resource_stages.py) |
| C004 | [tof_error_budget_tests](../../common/gate_catalog.json)（L295） | fast／stdlib<br>无显式前置 | 保留独立 TOF 误差预算数值回归；不为模块数量合并科学边界。 | 相对基线：无字段变化<br>[test_tof_error_budget.py](../../common/analysis/test_tof_error_budget.py) |
| C005 | [documentation_link_tests](../../common/gate_catalog.json)（L318） | fast／stdlib<br>无显式前置 | 单测与全仓文档门禁职责不同；保留定位收益，承担有限重复扫描成本。 | 相对基线：无字段变化<br>[test_documentation_links.py](../../common/test_documentation_links.py) |
| C006 | [project_registry](../../common/gate_catalog.json)（L345） | fast／locked<br>无显式前置 | 保留生成注册表 freshness；不建立跨轮 PASS token，重复 wrapper 检查未据名称自动删除。 | 相对基线：无字段变化<br>[build_project_registry.py](../../common/contracts/build_project_registry.py) |
| C007 | [livelink_failure_classification](../../common/gate_catalog.json)（L371） | fast／stdlib<br>无显式前置 | 保留环境/供应商/物理失败分类；不能以本项替代求解器验收。 | 相对基线：无字段变化<br>[test_livelink_failure_classification.ps1](../../common/comsol/test_livelink_failure_classification.ps1) |
| C008 | [livelink_environment](../../common/gate_catalog.json)（L390） | fast／stdlib<br>无显式前置 | 保留 LiveLink 环境分类，和资源/失败分类分别承担合同。 | 相对基线：无字段变化<br>[test_livelink_environment.ps1](../../common/comsol/test_livelink_environment.ps1) |
| C009 | [rf_multipole_generated_publications](../../common/gate_catalog.json)（L409） | fast／locked<br>无显式前置 | All Freshness 是三 RF variant 的显式前置；ready 调度只在其 PASS 后放行依赖。 | 相对基线：无字段变化<br>[verify_project.ps1](../../projects/rf_multipole_ion_optics/verify_project.ps1) |
| C010 | [longitudinal_fit_tests](../../common/gate_catalog.json)（L111） | regression／locked<br>无显式前置 | 保留 longitudinal fit 数值权威；代价为持续维护独立参考。 | 相对基线：无字段变化<br>[test_longitudinal_fit.py](../../common/analysis/test_longitudinal_fit.py) |
| C011 | [peak_metrics_tests](../../common/gate_catalog.json)（L134） | regression／locked<br>无显式前置 | 保留峰/KDE/FWHM 权威回归；不复制各项目算法换取表面并行。 | 相对基线：无字段变化<br>[test_peak_metrics.py](../../common/analysis/test_peak_metrics.py) |
| C012 | [figure_export_tests](../../common/gate_catalog.json)（L157） | regression／locked<br>无显式前置 | 保留图导出不可覆盖与生命周期边界；预热消重不作为删除此路由理由。 | 相对基线：无字段变化<br>[test_figure_export.py](../../common/analysis/test_figure_export.py) |
| C013 | [beam_focus_diagnostics_tests](../../common/gate_catalog.json)（L180） | regression／locked<br>无显式前置 | 保留 beam focus 独立分析回归；不因较小套件而撤除。 | 相对基线：无字段变化<br>[test_beam_focus_diagnostics.py](../../common/analysis/test_beam_focus_diagnostics.py) |
| C014 | [particle_census_tests](../../common/gate_catalog.json)（L203） | regression／stdlib<br>无显式前置 | 保留完整母群/终态计数；科学 skip 不等于门禁 NOT_APPLICABLE。 | 相对基线：无字段变化<br>[test_particle_census.py](../../common/analysis/test_particle_census.py) |
| C015 | [plane_crossings_tests](../../common/gate_catalog.json)（L226） | regression／stdlib<br>无显式前置 | 保留穿越事件语义；分片须保持边界负例，当前不做机械拆分。 | 相对基线：无字段变化<br>[test_plane_crossings.py](../../common/analysis/test_plane_crossings.py) |
| C016 | [population_moments_tests](../../common/gate_catalog.json)（L249） | regression／locked<br>无显式前置 | 保留 population moments 统计语义；独立参考优先于减少测试行数。 | 相对基线：无字段变化<br>[test_population_moments.py](../../common/analysis/test_population_moments.py) |
| C017 | [particle_events_tests](../../common/gate_catalog.json)（L272） | regression／stdlib<br>无显式前置 | 保留粒子事件时空/状态语义；不与 census 混成同一判据。 | 相对基线：无字段变化<br>[test_particle_events.py](../../common/analysis/test_particle_events.py) |
| C018 | [common_contracts](../../common/gate_catalog.json)（L446） | regression／locked<br>无显式前置 | L2 完整 discover，L1 支持显式变更模块/安全扩大；保留嵌套入口测试，未据并发 elapsed 强拆套件。 | 相对基线：matches/test_selection<br>[common/contracts](../../common/contracts/) |
| C019 | [simion_common](../../common/gate_catalog.json)（L613） | regression／locked<br>无显式前置 | 保留公共 SIMION discover；软件夹具不替代 Refine/Fly/IOB 重开。 | 相对基线：无字段变化<br>[common/simion](../../common/simion/) |
| C020 | [rf_multipole_domain_tests](../../common/gate_catalog.json)（L636） | regression／locked<br>无显式前置 | 保留 RF domain owner；test-only 精选，fixture/init/未知路径扩大范围。 | 相对基线：matches/test_selection<br>[projects/rf_multipole_ion_optics/tests/domain](../../projects/rf_multipole_ion_optics/tests/domain/) |
| C021 | [integration_common](../../common/gate_catalog.json)（L696） | regression／locked<br>无显式前置 | 保留连接公共合同，与整机 assembly 门禁互补；承担两层独立验证成本。 | 相对基线：无字段变化<br>[common/integration](../../common/integration/) |
| C022 | [instrument_assembly_integration](../../common/gate_catalog.json)（L755） | regression／locked<br>无显式前置 | test-only 精选，混合生产或共享 fixture 走完整 wrapper；保留 Ruff 与冻结依赖验证。 | 相对基线：test_selection<br>[verify_integration.ps1](../../integrations/verify_integration.ps1) |
| C023 | [solidworks_common](../../common/gate_catalog.json)（L820） | regression／locked<br>无显式前置 | 保留 SolidWorks 公共机制回归；不由软件阶段推导 CAD GUI/冷重开通过。 | 相对基线：无字段变化<br>[common/solidworks](../../common/solidworks/) |
| C024 | [orthogonal_accelerator_static](../../common/gate_catalog.json)（L843） | regression／locked<br>无显式前置 | 保留 OA solver-free Static；不缩减科学覆盖，也不授予新的真实求解资格。 | 相对基线：无字段变化<br>[verify_project.ps1](../../projects/orthogonal_accelerator/verify_project.ps1) |
| C025 | [parallel_mirror_dual_stripe_mr_tof_static](../../common/gate_catalog.json)（L878） | regression／locked<br>无显式前置 | L1 Core 合并 ChangedTestModules，L2 Static 保留递归 Python 与三 Lua 回归；不凭长尾 elapsed 自动拆池。 | 相对基线：test_selection<br>[verify_project.ps1](../../projects/parallel_mirror_dual_stripe_mr_tof/verify_project.ps1) |
| C026 | [single_reflection_oa_tof_mass_analyzer_static](../../common/gate_catalog.json)（L934） | regression／locked<br>无显式前置 | 保留 oaTOF 静态与消费者边界；真实 PA handoff/Fly/恢复另列本轮验收。 | 相对基线：无字段变化<br>[verify_project.ps1](../../projects/single_reflection_oa_tof_mass_analyzer/verify_project.ps1) |
| C027 | [rf_multipole_quadrupole_static](../../common/gate_catalog.json)（L981） | regression／locked<br>rf_multipole_generated_publications | 保留 quadrupole 独立 Static 与 Freshness 前置；L1 未知测试路径扩大，不宣称独立入口能推断新 owner。 | 相对基线：test_selection<br>[verify_project.ps1](../../projects/rf_multipole_ion_optics/verify_project.ps1) |
| C028 | [rf_multipole_hexapole_static](../../common/gate_catalog.json)（L1059） | regression／locked<br>rf_multipole_generated_publications | 保留 hexapole 独立覆盖与 Freshness；不继承其他极数的物理资格。 | 相对基线：test_selection<br>[verify_project.ps1](../../projects/rf_multipole_ion_optics/verify_project.ps1) |
| C029 | [rf_multipole_octupole_static](../../common/gate_catalog.json)（L1122） | regression／locked<br>rf_multipole_generated_publications | 保留 octupole 独立覆盖与 Freshness；代价是必要的 variant 回归。 | 相对基线：test_selection<br>[verify_project.ps1](../../projects/rf_multipole_ion_optics/verify_project.ps1) |
| C030 | [dual_pressure_rectilinear_ion_processor_static](../../common/gate_catalog.json)（L1185） | regression／locked<br>无显式前置 | 保留 IP 科学/配置边界；未发现足以撤销 route 的重复证据。 | 相对基线：无字段变化<br>[verify_project.ps1](../../projects/dual_pressure_rectilinear_ion_processor/verify_project.ps1) |
| C031 | [dual_cone_tandem_quadrupole_ion_interface_static](../../common/gate_catalog.json)（L1244） | regression／locked<br>无显式前置 | 保留双锥接口单 owner；不以耗时较短作为裁撤理由。 | 相对基线：无字段变化<br>[verify_project.ps1](../../projects/dual_cone_tandem_quadrupole_ion_interface/verify_project.ps1) |
| C032 | [transverse_helical_filament_wehnelt_electron_gun_static](../../common/gate_catalog.json)（L1299） | regression／locked<br>无显式前置 | 保留电子枪 Static；不据此宣称真实电场/轨道或 Formal。 | 相对基线：无字段变化<br>[verify_project.ps1](../../projects/transverse_helical_filament_wehnelt_electron_gun/verify_project.ps1) |
| C033 | [apertured_tube_electron_impact_ion_source_static](../../common/gate_catalog.json)（L1330） | regression／locked<br>无显式前置 | 保留 EI 源 Static；无已定位 route 缺口，不追加形式重构。 | 相对基线：无字段变化<br>[verify_project.ps1](../../projects/apertured_tube_electron_impact_ion_source/verify_project.ps1) |
| C034 | [expected_values_tests](../../common/gate_catalog.json)（L474） | covered／stdlib<br>由 common_contracts 完整覆盖 | 精确 expected_values 单模块执行；完整 contracts 覆盖时同轮去重，减少重复但保留 authority。 | 相对基线：无字段变化<br>[test_expected_values.py](../../common/contracts/test_expected_values.py) |
| C035 | [gate_contract_tests](../../common/gate_catalog.json)（L499） | covered／locked<br>由 common_contracts 完整覆盖 | 保留路由、真实入口、摘要/ready/failfast 与 scoped/index 回归；字符串检查不冒充行为证据。 | 相对基线：command/matches<br>[test_verify_changed.py](../../common/contracts/test_verify_changed.py), [test_parallel_gate_support.py](../../common/contracts/test_parallel_gate_support.py), [test_development_standards.py](../../common/contracts/test_development_standards.py), [test_changed_test_selection.py](../../common/contracts/test_changed_test_selection.py) |
| C036 | [cloc_contract_tests](../../common/gate_catalog.json)（L563） | covered／locked<br>由 common_contracts 完整覆盖 | 保留真实 CLOC 分类/加性/身份回归；完整 contracts 覆盖时去重，不另造行数器。 | 相对基线：无字段变化<br>[test_report_cloc_delta.py](../../common/contracts/test_report_cloc_delta.py) |
| C037 | [python_dependency_contract](../../common/gate_catalog.json)（L588） | covered／locked<br>由 common_contracts 完整覆盖 | 保留 Python 依赖合同；有效 stages 决定 stdlib/locked，完整 contracts 覆盖时去重。 | 相对基线：无字段变化<br>[test_python_dependency_contract.py](../../common/contracts/test_python_dependency_contract.py) |

## 范围修正与验收边界

- **A032 和 A044 的限界。** A032 只移除纯 field problem 对 orchestration 的反向边，不要求整个 provider DAG 重写；
  A044 对应 [实际 provider runner](../../projects/parallel_mirror_dual_stripe_mr_tof/simion/run_native_static_field_provider.ps1) 的真实 release/原错保留，
  及 [seal-only 项目组合回归](../../projects/parallel_mirror_dual_stripe_mr_tof/tests/analysis/test_native_static_field_provider.py)。
  保留现公共 seal CLI，仅收尾恢复不得重新 Refine；不能把 analysis 文件较长当成新增恢复平台的理由。
- **发布链判断更正。** A029 的正式 IP runner 和 A037 的正式 MR study runner 已有 retention/publication/独立验证/seal
  外层边界，不能从内部 build/write helper 推导整个正式入口缺验证。二者不因风格统一而强制迁移，也不删除完整 verifier。
- **G2/G3 旧结论已过期。** 当前 [changed_source_scope](../../common/verify_development_standards.py)（L98）
  与 [index pre-commit](../../.githooks/pre-commit) 已有显式 scope、索引字节与保守扩大；
  [Invoke-IndependentGateStageGroup](../../common/parallel_gate_support.ps1)（L298） 已消费 ready 集、PASS 前置、
  missing/unselected/cycle BLOCKED 和缺 sidecar/log 回退。L1 只停止未启动队列，L2 在有效上下文中继续独立诊断；
  已启动健康进程自然收尾，文档检查仍独占，初始化失败仍阻断。L2 r2 还暴露 completion sweep 后 child 退出的消费竞态，最终在 [running 计数](../../common/parallel_gate_support.ps1)（L508）改用既有 Result 是否为空；[新行为回归](../../common/contracts/test_parallel_gate_support.py)（L105）覆盖 PASS 必先消费及实际失败阻断，无新状态/重试/延时。对应 [test_ready_dependencies_fail_fast_and_natural_completion](../../common/contracts/test_parallel_gate_support.py)（L31）。
- **计时与可选调度。** 摘要已分别记录 queue/resource wait/execution/cleanup、launch 和 parent process elapsed；
  这些是不同嵌套边界，不能相加或推导虚构 startup/纯计算时间。没有可信同 workload 历史 authority，因此本轮不采用自动 LPT、
  耗时 aging 或按模块长度分片：收益可能是减少尾部，代价是失真的历史权重、更多 fixture/导入成本和预算复杂度。
  保留确定性 catalog 顺序与原预算，不把该不采纳决定写成尚欠的框架开发。
- **选做 I/O 与文件组织分开。** H1/H2 的连续 guard/去重复读、MR 图导出等具名包一旦选做，其真实 owner、
  源/目标身份、原错与验收仍是必须条件；不把“原可选”当成可以省略回归，也不把它扩大为所有长文件拆分。
  H5 继续采用既有 Copy-VerifiedRunInput 默认源/目标验证：小文件收益未量化，本轮不新增同义 record-bound 层；
  H3 保留已闭合的正式发布链，不另建 publisher API。A078 后续直接反例确认父输入身份缺口，已列为窄范围必改并补专属回归；保留其正式 CLI，独立科学公式与 publisher 不重构。该软件修复不授予真实三维资格。
- **当前门禁名录逐项重核。** 当前 catalog 为 37 个唯一 stage；相对原 37 路由新增 0、删除 0。
  相对 3005980 有 8 项字段变化，已经在附录二逐行列出；covered 使用现有 full_scope_coverage_stage，
  不是缺失依赖。源码内固定前置/全仓检查不被这 37 个 catalog route 数量替代。
  各 route 的现有命令与长期测试是可核验入口，原矩阵历史 PASS/elapsed 未被搬作本轮最终验收。

## 本报告配套处置证据

以下TXT为原字节必要记录；新增门禁负例摘录单独归本报告，不修改已冻结的69文件包。失败原行附原源bytes/SHA，超长源码断言仅保必要前缀并明确截断，不把摘录冒充完整stdout。

| 只读载荷 | bytes | SHA-256 |
|---|---:|---|
| [gate_diagnostics_cleanup_preflight.md.txt](20261029__system-guide-complete-review/gate_diagnostics_cleanup_preflight.md.txt) | 22802 | `3BCD957E8A0A0F3250DFE35CBE9AEDED39E2F4DE3D81F383DFF7904FEA75DC1D` |
| [temp_cleanup_nine_actual_20261029.txt](20261029__system-guide-complete-review/temp_cleanup_nine_actual_20261029.txt) | 1609 | `C25AC865AA676C1905374B2247646EACC88B3E7F352F3234605BB61C00641A68` |
| [temp_cleanup_r1_actual_20261029.txt](20261029__system-guide-complete-review/temp_cleanup_r1_actual_20261029.txt) | 646 | `0F6F2D29B778F5D0AC7873FA4A7F53D3314D0B60A8145CD6D2C2C6B967EA1D5A` |
| [gate_diagnostics_cleanup_actual_20261029.txt](20261029__system-guide-complete-review/gate_diagnostics_cleanup_actual_20261029.txt) | 2341 | `6A83AF02AAE1F6A4EE615039A46B1A14FED4EA8165AA351C00E06570B166F213` |
| [main_temp_cleanup_actual_20261029.txt](20261029__system-guide-complete-review/main_temp_cleanup_actual_20261029.txt) | 883 | `D0B290101EEAFBEA9E4A8880D7AF45215335447A2B162C9613987CFB53ACF16C` |

旧诊断13目录已通过公共Remove-GateTemporaryDirectory按精确Path/ExpectedNamePrefix处理，并逐一核实际不存在；fresh正常用户CIM无其他exact引用，13份库存与预检匹配且无reparse。实际365文件／2,394,552 B、核验及处置0.5825681 s，retained=0。其中D09/D10的4文件／697 B位于主TEMP内，主TEMP后续盘点已排除，不重复计量。原r6/r7中断摘要保持原RUNNING/null记录，失败摘录保留错误与必要原行；科学run、缓存和中央账本未改动。

## 远端验收与最终冻结状态

旧代码`0f1df0f9a02b05c09bc7999d50149012f1a4ad4f`的[push CI 40816151259](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/40816151259)已明确FAIL，不能被本地修后通过覆盖。该push策略的repository_integration为skipped，不冒称远端L2。
测试修正提交`181e411950bb0f1da8c5528ecfeda95641932204`已普通推送，同时包含此前证据提交3e7b80da。[新push CI 40822854689](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/40822854689)精确绑定该提交，现为completed/success。changed_scope job区间05:20:50Z至05:47:04Z，gate step为05:21:50Z至05:46:58Z，即1508 s；7阶段PASS、两个顶层runner合计1220次执行／27skip（864／3skip与356／24skip），repository_integration为skipped，不是远端完整L2。

本记录保留原r4未闭合与两个integration FAIL，后节补充两轮原字节定向复核及原因未定位的边界。用户明确不新增或重跑L2；归档不追认该轮PASS。
原主TEMP精确目录codex_guide_wave1_20261028_f773196bc812465eb95e29625b8210a6已删除，fresh普通文件盘点1,116 files／27,696,328 B（其中164个一次性JSON、293个内部目录），核验及删除1.6914546 s。删除前69份已提交验收载荷再次全SHA核验，190条主稿与4处置记录均与其已暂存Git对象一致；所有Agent停止该目录消费，fresh正常用户CIM无其他exact引用，0 reparse。D09/D10此前已移除，不进入本次盘点。

上述四阶段合计4,413文件／53,308,716逻辑字节，没有重复计入两处嵌套诊断，也未测卷free净变化。原科学run、必要冻结输入、公共缓存、保护状态和中央账本未因此变更。

## 新CI真实负结果与最小测试合同修正

代码提交0f1df0f9的CI40816151259最终failure；changed-scope gate step为04:10:26Z至04:39:12Z，约1726 s。日志提取第一次通用gh调用受403拒绝，随后正常credential的job专属只读API可读取原失败，不把权限错误当测试根因。当前发现失败仅两处测试PID inequality：common/contracts/test_run_artifact_workflow.py原L467，以及common/simion/test_managed_process_completion.py原L192的三个子场景。

CI实际CPython3.11.9直接解释器未建venv。公共协议始终允许READY worker属于含launcher自身的初始family，严格核nonce、PID、创建身份及同handle，故同PID合法；本地venv shim使两PID不同，仅旧测试误把这种环境特征写成不变量。CI前置ownership／actual-exit／drain已通过；失败行之后的late-content、日志稳定与封存SHA断言未执行，不能冒称它们在失败CI通过。

最小修改仅让test worker独立自报os.getpid，并与receipt.worker_process_id相等；launcher保持正ID与真实退出，原ACK拒绝、原错、晚日志／封存检查均保留，不改生产代码、不skip CI、不增加防御框架。

修复前直接Python3.11的两方法真实RED为4个断言失败／12.513 s。修后直接解释器两方法PASS／12.237 s，真实venv两方法PASS／12.784 s；这些是同两方法在两种环境的执行，不叠加为四个独立方法。实际worker marker证明直接workflow的launcher/worker/marker均为13760，venv workflow则为19924/13444/13444；normal0、normal7及ACK错误分支也分别核真实marker，sample_error仍保持worker/marker未知，没有补造身份。
两个所属模块完整回归为22 tests／0skip／PASS，unittest body 202.860 s。它与上述focused及后续L1是不同执行，不累加为唯一测试数量；202.860 s不是公共GATE准入、cleanup或外层进程总墙钟。原记录见本报告同名载荷目录的pid_contract_review.txt、red_base.log.txt、green_base.log.txt、green_venv.log.txt和full_venv.log.txt。

改动L1原parent3596自然exit 0；摘要2026-10-29T04:51:37.4109000Z至05:19:44.0656193Z，1686.655631 s。仅两个测试文件触发repository_hygiene、repository_text_bytes、development_standards、ruff_changed_python、common_contracts、simion_common六阶段，6 PASS／36 NOT_APPLICABLE；不是先前23阶段的广范围L1。两个顶层runner合计1220次测试执行／7skip／0failure／0error，不重复计算嵌套fixture回放，也不称为去重方法数。

| 当前L1 runner | unittest body | stage elapsed | parent-observed child process elapsed | tests /skip |
|---|---:|---:|---:|---:|
| common_contracts | 1659.930 s | 1664.580591 s | 1666.339774 s | 864 /1 |
| simion_common | 133.956 s | 138.496536 s | 140.244204 s | 356 /6 |

摘要1686.655631 s是整轮L1区间；上表process是阶段子进程观察值，不是L1外层进程墙钟。body、stage、process和resource wait/cleanup是嵌套边界，阶段并行，不能相加补造总墙钟。本报告配套l1_pid_fix_observation.txt保存六阶段细分、原raw身份及释放记录：每个实际GATE owner为released，父进程已消失、中央records=[]，两测试源码SHA在终态复核不变。

| 181e冻结测试源 | bytes | SHA-256 |
|---|---:|---|
| common/contracts/test_run_artifact_workflow.py | 38811 | `83a73c57f04d1fba2aa8fba42a2a172ea147da80a6925ae5d8c43cea70427e0c` |
| common/simion/test_managed_process_completion.py | 18133 | `fc317362f3e6bf89d6b1a65117220d3064716802d0b2d418dd8ba747edb00acf` |

181e新push CI已取得真实success，改动L1及上述focused为已完成证据。181e只改两个测试、无生产变更；用户明确无需再新增或重跑完整L2。r4保留其未取得终态的原摘要和两个具名FAIL，不能据取消补跑而填整轮PASS、FAIL或新墙钟。

## CI测试修正的原始验收记录

以下12份原字节记录承接两拓扑、22方法、L1、精确提交CLOC及新CI真实终态；与前述5份处置记录合计17份，后节另列中断、定向复核和最终清理／文档验收记录，同名载荷目录最终共33份。不将r4未闭合记录称为仍在健康运行，不修改既有69文件冻结包。

| 只读载荷 | bytes | SHA-256 |
|---|---:|---|
| [ci_pid_fix_l1_console.log.txt](20261029__system-guide-complete-review/ci_pid_fix_l1_console.log.txt) | 16090 | `3B01CFFABD17121FBE159EB703BADA0BF70A346C5DED8B9B4BD3D2B7F0FE06E4` |
| [ci_pid_fix_l1_summary.json.txt](20261029__system-guide-complete-review/ci_pid_fix_l1_summary.json.txt) | 33301 | `A947DE19AFD2D65C6DFDC4613BBBA217346B0A02A3D0E115E2BF9A02E2905B67` |
| [l1_pid_fix_observation.txt](20261029__system-guide-complete-review/l1_pid_fix_observation.txt) | 2957 | `002C1A632564705072EAE93DD6813071F4C0C1FA34C963A6EFE590C29FC553E2` |
| [cloc_pid_fix_exact_commit.txt](20261029__system-guide-complete-review/cloc_pid_fix_exact_commit.txt) | 14283 | `8B4B31EEBAE85D5E05973DA1900BA144248C29A16706A638CE6F1671500D3898` |
| [cloc_pid_fix_exact_commit_release.txt](20261029__system-guide-complete-review/cloc_pid_fix_exact_commit_release.txt) | 78 | `6D3FE1EB2C1F3DA3078C93050167F415D61758497C05D0BD32C13205CB12EB32` |
| [pid_contract_review.txt](20261029__system-guide-complete-review/pid_contract_review.txt) | 4212 | `C58BC42D32B7E28844B06D7601254D9AC35788B607645BEA894E6D91C1F9D162` |
| [red_base.log.txt](20261029__system-guide-complete-review/red_base.log.txt) | 6707 | `2F25FD04DC38E636AEC6BAF889716334AA65826419D8A193E421B82D2AA4E3AF` |
| [green_base.log.txt](20261029__system-guide-complete-review/green_base.log.txt) | 2932 | `F34DAE427BFB0C3DD60A372B6559D71882657311DD0A166AE5C144872E495D40` |
| [green_venv.log.txt](20261029__system-guide-complete-review/green_venv.log.txt) | 2970 | `BDAC6C80B35AFAC2FD195E39ADFBCB098ED03B41CF4A7ACDB1BD38D15128DED9` |
| [full_venv.log.txt](20261029__system-guide-complete-review/full_venv.log.txt) | 128 | `FF942056432E7448358630394D16F10FB29BC2047FC76210CCDEEC21F06FAC23` |
| [ci_181e_terminal.json.txt](20261029__system-guide-complete-review/ci_181e_terminal.json.txt) | 2803 | `91F35C3C5C2FE0DBE3985A4BEDF6FA87F8A90BFDD7F45DDB44CD97254A54127E` |
| [ci_181e_test_results.txt](20261029__system-guide-complete-review/ci_181e_test_results.txt) | 7966 | `13C3CD3EF284675B05E8D25F30710F2B5CCEA65EEDFD5625C02052700E2BE477` |

## CI终态与L2 r4原记录边界

新CI40822854689为exact181e的completed/success，范围和时间见上节及已保全的原始API/日志摘录。没有将其7阶段changed-scope通过外推为37阶段完整L2。

L2 r4原parent15292、session42897；运行前Git干净，2358文件／204035238 B整体SHA6c16e71145f4613af44aa0c883279a8672ab0ef8ba189c246532a5a3d54ce505。后续实际系统重启时间为2026-10-29T05:37:01.5Z；Agent2核对session为Unknown、parent15292已不存在。原summary仍为RUNNING，33 PASS／4 RUNNING，started_at=2026-10-29T05:23:26.5104099Z，finished_at/elapsed_seconds均null。缺终态不能改判为整轮PASS或FAIL，也不能补造耗时或把旧33阶段结果当全量完成。

原RUNNING四阶段为common_contracts、instrument_assembly_integration、parallel_mirror_dual_stripe_mr_tof_static及single_reflection_oa_tof_mass_analyzer_static。integration原日志`C:\Users\Liao\AppData\Local\Temp\repository_integration_gate_74bbec25b8574bbf8c7be54692dbaef7\24_instrument_assembly_integration.log`实读80077 B，重启前已出现以下两项具名FAIL：

- L385–386：`test_native_model_facts_survive_removal_of_run_execution_junction`。
- L390–393：`test_owner_retention_and_terminal_boundaries_close_success_and_failure`，子场景`outcome='failed'`。

二者均属于`integrations.tests.test_paired_accelerator_static_field_execute.PairedStaticExecutionTests`；原日志没有该轮延后输出的traceback，无法恢复具体失败断言。原字节、相同解释器及公共中央GATE下，仅对这两个方法独立复测两轮，分别2 tests／9.033 s和2 tests／7.244 s，均PASS；生命周期方法的success和failed两臂均完成原终态、原错误与retention/ledger检查，junction方法验证移除别名后的永久模型身份。两轮未改源码、未启动供应商进程，资源正常released。这里只得出当前两次未复现的结论，不声称已定位或修复旧根因，也不将重启当作两项失败的原因。原r3全37 PASS仍是历史证据，原r4两项FAIL观察与未完成摘要原样保留。

用户明确不要求新增或重跑L2，已取消的补跑不留为待办。对缺失原trace的历史失败采用上述有边界的复核结论归档，不编造根因或为制造修复而改代码。整轮r4不授予PASS；当前测试修正采用实际L1与CI、两项补充focused及既有全L2历史共同说明验证范围。报告归档、临时文件清理和文档提交的实际结果另列。

## 中断记录与定向复核原始证据

以下只读TXT保留原字节，不作为活动JSON或可执行脚本；原r4摘要未改写。源码前后2358文件记录相等，整体身份6c16e711…e505；完整清单算法见preflight记录。定向复核不覆盖原整套顺序与并发背景，因此不排除上下文相关影响。

| 只读载荷 | bytes | SHA-256 |
|---|---:|---|
| [l2_r4_summary.json.txt](20261029__system-guide-complete-review/l2_r4_summary.json.txt) | 41833 | `1A3F1BA654573D3F058FD7F866896D184168F226369D06FEC265E70AEB803D8B` |
| [l2_r4_console.log.txt](20261029__system-guide-complete-review/l2_r4_console.log.txt) | 32354 | `CAFFB14C7EFDBEDF355F99FD3B4067D70F22581983501F3F47F04384FDBF73DD` |
| [l2_r4_launch.json.txt](20261029__system-guide-complete-review/l2_r4_launch.json.txt) | 478 | `1DD4BA48537D6B5D8C8D7F3A53A60B2D350B7325F3DDA03840633418375AED97` |
| [l2_r4_preflight_source.json.txt](20261029__system-guide-complete-review/l2_r4_preflight_source.json.txt) | 517899 | `E76C42D970FCEAC7D0AFF6C0DF0D31CC60A8635FA73A4BD6E2B80DAA81978192` |
| [l2_r4_integration_incomplete.log.txt](20261029__system-guide-complete-review/l2_r4_integration_incomplete.log.txt) | 80077 | `7235ACC1A608605581CAF997711AF52B64C0F0331A0CCF356D8AFDD19090595D` |
| [paired_static_focus.log.txt](20261029__system-guide-complete-review/paired_static_focus.log.txt) | 911 | `83B2E945C21CD8FA9C5B523A9FFDD59C57771A238643A309A8C48DF397E2DE38` |
| [paired_static_focus_repeat.log.txt](20261029__system-guide-complete-review/paired_static_focus_repeat.log.txt) | 910 | `609115A495C02D2A80C5505790E70CB10E4A9A3EABFB568CDCA766308300B773` |
| [paired_static_focus_closeout.txt](20261029__system-guide-complete-review/paired_static_focus_closeout.txt) | 5369 | `7FDADCA517E473D4E5012E21FC37B406C2972D23230968B47FACD65823AD0776` |
| [l2_r4_closeout.txt](20261029__system-guide-complete-review/l2_r4_closeout.txt) | 17579 | `8DC30F754AE841CDC2EF7E4BC92F4D7DF0C16D29F10B18B0107CD0D14576B0AC` |
| [l2_r4_post_source.json.txt](20261029__system-guide-complete-review/l2_r4_post_source.json.txt) | 458 | `4056094BAE09D71BCF2F86380595912D01E2471C7FB53537994DD233FF05D070` |
| [l2_r4_common_contracts_incomplete.log.txt](20261029__system-guide-complete-review/l2_r4_common_contracts_incomplete.log.txt) | 4977 | `AD24D0EFBF8EBD407AF44A61AADC72397CCBE51A3608C465F0A205006139472B` |
| [l2_r4_mr_incomplete.log.txt](20261029__system-guide-complete-review/l2_r4_mr_incomplete.log.txt) | 508 | `81B8A8C417A0073EAD94F3DED839FDE2C78B25B0A55A24FAD4C9DC235391546E` |
| [l2_r4_oatof_incomplete.log.txt](20261029__system-guide-complete-review/l2_r4_oatof_incomplete.log.txt) | 3892 | `ADB798DB433C7611FFF56D4553A1CDC1D9CB9CB7DEF387C1F786FFABD61CD95B` |

原L2的24个已完成runner记录1,900次测试执行／6skip，仅为部分范围。前后源码2358文件／204,035,238 B逐record一致；中央host状态为空不等于中断owner正常release。90份容量lease以相同读取路径比较无变化；最初15份日期字符串末尾零差异只是读取序列化表示，未改lease，未将此比较冒充原字节哈希。详见上述closeout。

## 最终临时文件清理与交付边界

最后任务TEMP与被重启中断的L2诊断目录，在30份必要raw与暂存Git blob逐字节相同、全部Agent已交回、正常用户CIM无消费者、精确普通文件库存和无reparse复核后实际删除。
本批101文件／1,463,504逻辑B，其中40个活动JSON；删除0.0652126 s，两精确根均不存在。门禁诊断沿公共Remove-GateTemporaryDirectory，任务TEMP按已确认归属精确删除；不动正式run、published cache、pin或容量／主机账本。
连同前四批临时文件，累计4,514文件／54,772,220逻辑B；此数不包括另列B85和GUI r3的重型退役，不是卷free增量。必要原始JSON仅以清单绑定的只读TXT快照保存，非活动配置；一次性作者、候选和中间JSON均未纳入活动源码。

| 实际清理记录 | bytes | SHA-256 |
|---|---:|---|
| [final_task_temp_cleanup.txt](20261029__system-guide-complete-review/final_task_temp_cleanup.txt) | 691 | `64D6AEF90397BA9694312B170153BE9D9A0BDE98F1892DA8604F0D965670458D` |

最终代码身份仍为181e411950bb0f1da8c5528ecfeda95641932204；本次后续交付仅修改文档与历史只读载荷，官方CLOC代码计量保持该身份及过滤口径。190项及正文主题的决定已完成；GUI按用户取消，旧r4未完成与两FAIL／当前不复现边界保留。最终文档门禁和普通提交推送按仓库入口执行，不追加L2。

## 最终文档验收

StructureOnly实际exit 0：308份Markdown／166份history／9个authority，0 errors；112条review为既有只读历史断链或人工篇幅等提示，不是新增阻断。
最终纯文档L1实际exit 0，3阶段PASS，摘要22.450428 s；hygiene 5.221600 s、受管文本3.419457 s、documentation 13.755068 s，中央GATE逐阶段released。它不执行软件测试或商业求解器，不冒充L2。
本轮补正集成状态页中已过期的“三工作点尚未执行”表述，指向原真实小PA run及其资格限制，没有改变功能或数值输入。
两个最后的具名L1临时记录已按源／归档SHA相同、正常用户CIM无消费者、普通文件检查后精确删除：2文件／25,331 B，其中1个JSON。连同此前批次，本任务临时文件累计4,516文件／54,797,551逻辑B；不包含另列重型资产退休，不作卷free声明。

| 文档验收原始记录 | bytes | SHA-256 |
|---|---:|---|
| [final_documentation_l1.json.txt](20261029__system-guide-complete-review/final_documentation_l1.json.txt) | 3252 | `9D9B2AE1A0BAE7608CB19F71273C37104C487D1B7CB7DA66D9A6B9C347899F3B` |
| [final_documentation_l1.log.txt](20261029__system-guide-complete-review/final_documentation_l1.log.txt) | 22079 | `210C1F8EE241AC59310E365E2632CDE02BE746FBCB6D274A991AC1C58176C598` |

本记录的提交及普通push前分别报告历史／当前耗时；后续同主题提交仅承接本只读报告与导航，不改变代码身份或原始验收状态。远端检查终态以对应提交的Actions记录为准，旧绿灯不外推到后继提交。
