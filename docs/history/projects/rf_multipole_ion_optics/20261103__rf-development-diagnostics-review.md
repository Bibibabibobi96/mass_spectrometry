# RF开发期诊断与负结果整理

DOC_STATUS: ARCHIVED_READ_ONLY

本记录于2026-11-03整理2026-10-30至31的既有开发诊断，返回[历史索引](README.md)或[当前状态](../PROJECT.md)。
它保存源分组、冷提取与节点机制演进所需的失败、负结果和资格边界，不是新的执行报告或当前待办。

## 来源与本次审阅边界

来源是本次审阅时尚未提交的 `projects/rf_multipole_ion_optics/docs/PROJECT.md` 中“开发期诊断记录”段。
整理前整个文件SHA-256为 `fa109f4bb00d955f6f3792825b63af1b9debce92e420ec676fdc1cf38697f01d`；
本次审阅的仓库基线为 `5b6c3a7cd35749dc46131251a374928ee2969087`。该段不属于此基线已提交内容，
不能据Git作者或文件时间推断其原作者；本记录也不把旧运行改写成本次新实测。原记录段落与全部数字保留如下。

本次只读核对了具名run的summary、manifest及部分probe_summary小证据：030000为checkpoint，040000和050000为failed；
070000和071000为success但UNQUALIFIED；055255与055454为API_MECHANISM_ONLY且solve_calls=0；
202302、210920、220507均为DEVELOPMENT_MECHANISM_ONLY，210550为failed。
其中202302的6D差、210920的节点峰值和220507的显式Study Compute字段与下述记录吻合。
未重新执行测试或商业求解，也未重新逐标量复算全部墙钟、网格、源表、轨迹与内存数字，未打开或重新哈希MPH/MAT等大载荷。
旧170007/170201等失败的完整原始现场不在此次逐文件复核范围，不新增根因裁决。

原运行小证据的本机定位为工作区 `artifacts/projects/rf_multipole_ion_optics/runs/<下文完整run_id>/` 中的
`summary.json`、`run_manifest.json`、`results/probe_summary.json`（如有）和原日志；它们不随公开Git仓库发行，
这里的定位不表示远端存在同名artifact下载链接。原计时与源对照仍须按原run或其具名scratch小报告解释，不能用summary累计值替代公开命令外墙。

本次整理没有升级科学、数值、GUI/CAD、Candidate或Formal资格。下文“GUI Compute”指小开发模型的显式Study重算证据，
不能替代项目桌面GUI与CAD门禁；“当前”“待收口”“尚未验收”等按原记录时点解释，后续状态只查PROJECT。

## 原时点开发记录

以下段落保留开发时点的原始失败、机制探针及其当时限制；其中“尚未验收／待收口”仅指该时点，不覆盖后文已经取得的正常N100、GUI与最终冷提取证据。

2026-10-31粗网格N=100对照首臂`20261031_030000__test__comsol__rf-volume100-domain-before-8us`
经普通COMSOL入口完成冻结和源准入，但在vacuum mesh复合检查处退出，公开命令墙钟81.925秒。
该轮未取得场/粒子求解或性能对照结论；启动层失败报告覆盖了此前诊断，具体mesh失败项仍待定位。
随后收尾在completion阶段失败：项目科学配置重写丢失公共包的容量生命周期字段。
当前源码保留原包字段，回归覆盖真实配置重写后的成功/失败收尾；该修复不补造旧run元数据，
原小Result仍保留主错误及独立收尾错误，terminal/容量收尾未完成，不冒称已安全封存。

新建mesh-only诊断`20261031_040000__test__comsol__rf-volume100-mesh-diagnostic`沿同一正常campaign入口
只构几何和网格，原N=100源、domain[-3,82.1]mm与auto9/hmax2mm不变。87.411秒后原mesh门禁拒绝：
global/vacuum均非空且complete，元素数23088/15342；唯一FTET1消息为薄区域小于指定最小单元尺寸，
`hasproblems=1`，不能把完整网格当作接受通过。未创建场/粒子求解。
本轮实际失败收尾完成：小Result的stage=complete、status=failed，终态发布、容量封存、租约释放及writer确认均成立；
主mesh错误保留。该证据验证新运行的失败收尾接线，不改变030000旧run，也不证明传输或科学资格。
同一040000原CLI再次执行`-ResumeFinalization -RunId`返回`WORKFLOW_TERMINAL=REUSED`；
manifest、原生completion与resource usage小证据逐字节不变，仍保留原failed状态，没有新增原生调用。

后续`20261031_050000__test__comsol__rf-volume100-hmin-mesh`只将同一开发数值profile的最小网格尺寸
显式设为0.2mm；实际Size读回证明其他控制不变。原生网格通过：global/vacuum元素45706/28272，
complete且无problems；未创建场/粒子求解。公开命令88.713秒后因解析器误要求hybrid策略字段而failed，
其失败终态、容量和租约均已收尾。当前解析器按冻结strategy校验，9项回归通过（9.521秒），
并只读验证该封存报告通过，零新增原生调用；原run仍为failed，不能把报告重验改写成该run成功。
finite单序列出口图允许有效源零出口时明确not_applicable，不产生虚假PNG；19项回归通过（6.531秒），
坏数据继续失败。这不证明尚未执行的8µs对照有无出口，也不授予传输或科学资格。

2026-10-31有限三维正常campaign入口的N=100对照`20261031_070000__test__comsol__rf-volume100-hmin-before-8us`
与`20261031_071000__test__comsol__rf-volume100-hmin-after-8us`均成功封存；相同原始体积源、
domain[-3,82.1]mm、auto9/hmax2/hmin0.2mm、1.1MHz／每组零峰值139.81792V（相位0）、每周期80步与8µs范围，
仅单粒子释放改为精确birth分组。
每臂实际场求解1次、粒子求解2次；源构造100节点/30.967秒→1节点/0.485秒，
公开命令157.443→102.883秒，进程树峰值3618435072→3588435968字节。这是单次同环境对照，不能推算所有源或全程性能。
原100 IDs、事件、存储时刻和接受分区一致，初始XYZ/时刻可由原生轨迹核对；canonical源行由输入生成，
不能称为原生初速度独立回读。原源未记录weight，权重指标not_computable，不补造等权。
两case各100粒子均unknown/time_window_end；RF-on另有同19个接受包络拒绝，不能把unknown当物理损失。
无rod_exit/handoff；这是入口段源/数据/性能证据，不证明完整传输、场精度或科学资格。
RF-on末态位置/速度差最大1.1682e-10mm/3.3210e-7m/s，仅报告诊断值，未预注册N=100轨迹等价容差，
不据此授予等价资格。该已保存解的MPH重提取实测见上文；第二消费者规模收益仍未闭合。

不同birth的100节点构造另用无网格／无Study的API探针比较：
`20261031_055255__test__comsol__rf-update-base2`与`20261031_055454__test__comsol__rf-update-deferred`
仅改变release构造期间的自动更新开关，计时包含最终刷新。构造20.259→17.091秒，
公开命令85.240→85.038秒，未测得明显整体提速；两臂实际求解均0。
100个节点、原birth／六列源文件绑定、完整模型保存冷重开及第50节点注入异常后的更新状态恢复均通过。
该证据仅验证官方API机制，不证明生产入口性能、粒子轨迹或GUI Compute；两个生产消费者的完整验收边界不因此缩减。
确定性四极solver的真实release循环已接该开关，刷新后才可保存或推进，恢复错误作为原异常的附加原因。
现四极数值编译器支持显式授权的`core_flow_development_coarse`，默认baseline不变；实际编译／授权拒绝3项
回归通过（3.776秒），MATLAB检查无代码错误。尚未运行该消费者的新场／粒子对照；auto9薄缝网格是否接受未知，
不会自动回退精细场。当前接口CLI的预算与公共owner接线仍待收口，不能将该参数准备当作可启动的生产验收。
两臂所需新源已由现有公开generator在77文件冻结闭包中生成并通过同一validator，禁止活动源码回退；
实际仅N100、100个不同birth，全部100×11数值与原official100相同，新bundle绑定当前政策与设计209F6FAA…。
这是从声明的入射分布创建新源，不是上游飞行或状态接续；canonical10本身无weight列，CWF=1仅由原ION11证据保留。
该纯软件准备未执行原生，不证明粗网格、轨迹或GUI资格；源准备证据位于本轮deterministic开发scratch的source_prepare_v1。
此前一次探针缺公共路径模块在启动前失败；另一次冻结遗漏comsolstartup.m，199.452秒后按精确身份
收尾错误启动，未进入任务或求解。原失败记录保留；已补冻结.m闭包及启动前检查，未改写失败run或重用其身份。

此前2026-10-30的N=3开发探针保留了原ID、不同birth及权重，
保存参考与两个分块解；`170007`冷读位置差最大5.758e-10 m，但实际速度全NaN，原聚合的零最大差不能作为6D通过。
`170201`在任务报告创建前发生JVM GC线程崩溃，现有证据不能归因于粒子读取API；不将其分类为可自动重试瞬态。
新建`20261030_202302__test__comsol__rf-coldread6d-r3-n3`只读冷读run，保持原预算、原MPH保护和零求解，
使用官方`mphparticle(...,'velocities','on')`的`pd.v`与实际physics identifier速度变量交叉核对，并拒绝空值、
活跃状态NaN及生命周期不一致。该新run已完成：三个ID的活跃状态掩码相同，最大位置差5.757810654e-10 m、速度差4.186895520e-4 m/s，
分别低于冻结1e-9 m与1e-3 m/s；`pd.v`与实际identifier速度变量交叉差为零，活跃状态无NaN。
原生冷读区间92.526秒、进程树峰值2,536,628,224 B，新增求解为零；实际退出、终态发布、容量封存与租约释放均完成。
该证据仅关闭已有解析RF小模型的N=3分块6D读取机制，不具备N=100功能或源构造规模收益资格。
原producer `20261030_165218__test__comsol__rf-release-chunks-n3`整体仍为failed（当时活动掩码断言失败）；
本次只在新run重开其已保存模型并验证实际绑定，没有改写父终态或重飞。只读元数据复核显示，
新run绑定的模型bytes/SHA与producer输出manifest相同，该复核不再读取MPH载荷。
这条开发诊断不修改正式物理设置或父终态，也不能用位置通过替代完整状态通过。

顺序节点退役探针`20261030_210920__test__comsol__rf-sequential-r2-n3`已完成：同一已加载解析RF参考，
按原源行[1,3]与[2]推进，执行阶段峰值release=2、physics=1、solution=1；参考模型加载时3个release另列。
每块提取后按依赖次序移除本块结果、解、study及physics，再重建同一角色；两个块推进2.0005／0.6305秒，
整个原生区间39.535秒、进程树峰值2,663,436,288 B，ID、权重、不同birth与原容差保持。
无场／参考重求，也未保存或改写原MPH；正常公共收尾完成。首次探针`210550`因空tag列表MATLAB循环错误
在推进前失败，原失败终态保留。该机制仍未接入生产规模，亦不证明逐块保存／失败恢复和完整GUI交付。

同精确birth多行释放开发探针`20261030_220507__test__comsol__rf-multirow-n3`通过：官方`ReleaseFromDataFile`
多行API在解析RF小模型将3个release合成2组，实际native顺序[1,3,2]映射回原ID[41,7,93]；不同6D、birth与权重保持。
相对本次同源逐粒子参考，完整三粒子MPH保存冷重开及显式Study Compute后位置／速度最大差均为0；
本次明确执行3次粒子求解、0次场求解，没有重算原父模型。三个推进区间1.0786／0.5925／1.0260秒，
公共owner摘要区间46.9506秒，进程树峰值3,087,745,024 B；正常封存与租约释放完成。
该证据只验证N=3同birth多行机制和完整母群保存，不代表生产入口已完成原生验收、一般不同birth节点减少或N100端到端提速。
官方方法、目标版本与采用边界见[Release from Data File（COMSOL6.4）](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.27.html)，
2026-10-30查阅；每行独立粒子且位置／速度列索引分别0／3，合组不改变标量release时刻或RF绝对时钟。
