# 多极杆公共SIMION RF drive kernel与single-flight唯一回调收口

日期：2026-08-15

## 问题与边界

独立四/六/八极杆SIMION Program与RF—oaTOF single-flight Program曾各自维护杆电压公式。独立路径支持
sine/cosine、phase、RF/DC及轴向common-mode；integration路径只内联cosine，并未消费非零phase或DC。
当前活动八极杆工况恰为cosine、phase 0、DC 0，因此没有形成已发布结果漂移，但两份实现会在扩展工况时
分叉。integration还保留一个未使用的base efield callback名称，时钟则必须继续区别为独立飞行的局部
elapsed与连续整机的规范instrument time。

本轮只统一运行时代码权威和验证路径，不修改GEM、PA、网格、电场、粒子源、Formal资产或已发布run，
也不执行refine、Fly或任何场求解；因此不产生新的物理分辨率、传输或资格结论。

## 唯一实现

新增`common/multipole/simion_rf_drive.lua`作为纯Lua kernel。其配置一次性严格验证：

- waveform只能为`sine`或`cosine`，频率、`phase_rad`、RF幅值和scale必须为有限合法值；
- 两组DC键必须精确为1和2；电极ID必须为唯一的1..1000整数，group只能为1/2，polarity必须分别为
  `+1/-1`，电极表必须连续且无未知字段；
- 每个电极显式携带common-mode电位，公共scale、RF scale及`rf_steps_per_period`由调用者传入；
- kernel只返回`phase_at`、`differential_at`、`apply_static`、`apply_at`和预计算的timestep cap，不声明
  Workbench、segment、adjustable、PA、electrode setter或SIMION时钟。

两个调用方均在`initialize_run`编译一次drive，热路径只遍历预编译电极数组，不重新构造配置或公式表。
独立Program唯一传入`ion_time_of_flight`；integration的RF、pulse和跨系统checkpoint只传入
`birth + ion_time_of_flight`。独立runner直接透传canonical `phase_rad`，不再做rad→degree→rad往返。

single-flight不再把历史Formal、旧pulse和integration extension按覆盖链拼接。项目Candidate组件拥有
oaTOF实例、静态电压、基础场和detector行为；integration pulse/frontend hooks拥有规范instrument clock、
RF→pulse次序、边沿和基于SIMION官方`tstep_adjust`/`other_actions` callback机制的项目落面hook；
resolved-region hook只按冻结contract在选中区域覆盖
项目base field。最终assembler是唯一callback authority，只声明一次Workbench，并各声明一次`load`、
`initialize_run`、`efield_adjust`、`fast_adjust`、`instance_adjust`、`initialize`、`tstep_adjust`、
`other_actions`和`terminate`。所有被嵌入组件先经同一个纯边界校验器拒绝Workbench、callback、电极setter
和SIMION原生时钟。

规范instrument clock不替代solver-local elapsed的物理寿命语义。pulse、RF和跨系统checkpoint使用
`birth + elapsed`；项目组件的timeout、return-plane和detector crossing显式接收`elapsed_us`，从而保留
历史detector日志由分析器再执行`birth + local elapsed`的单权威换算。审计同时发现生产pulse parser未接受
旧Program一直输出的`ion=<id>`字段；parser现兼容该冻结格式及无`ion`历史格式，Program输出未改。

## 冻结与依赖闭包

独立三项目公开wrapper仍只委托`common/multipole/project_transport_launcher_support.ps1`，再进入同一个
`run_simion_finite_3d_transport.ps1`。公共runner把kernel用`Copy-VerifiedRunInput`复制到本run的
`inputs/multipole_rf_drive_kernel.lua`，Program只经环境变量加载该冻结副本。

integration在run package创建后把同一源文件冻结为`inputs/simion_rf_drive.lua`，builder只读取该run-local
副本并把字节嵌入生成Program；metadata记录kernel SHA。依赖清单新增
`common_multipole_simion_rf_drive_kernel`，官方`refresh_family_repository_bindings.py`更新7份派生绑定，
随后`--check`通过。生产运行时没有从活动仓库二次读取kernel。

同一run还冻结项目analyzer component及integration pulse/frontend hooks；builder四个Lua输入均为必需参数，
不存在live-repository fallback。旧Formal与旧pulse继续只服务仍活动的staged `analyzer_transport`；
`single_flight_transport`的runner、依赖consumer和Program metadata均不读取它们。历史文件字节未修改。

## 旧链表征与唯一汇编器等价边界

迁移前先冻结完整旧Program：51,757 bytes，SHA-256
`CB81D2EF2CFE8825067F781C35196C98CFAB2D3F6C21E9999C2DEE079BC4B1A9`。其中Workbench一次，但九类
callback共有19个定义：`initialize_run=3`、`fast_adjust=2`、`efield_adjust=2`、`initialize=2`、
`tstep_adjust=3`、`other_actions=3`、`terminate=2`，其余三类各1。历史Formal SHA为
`2E15EF94CC5ABEEA4E64E6C93FC9C0077B267C94300D2E6EFEDCCDBF5719B379`，旧pulse SHA为
`3497ABEFA378DC5D717E3EA7EA383826C09E53A664DBF12624219D4EECBF9CF8`。

最终repository-only successor为59,100 bytes，SHA-256
`F552F881DBE98A886013D72F7EB821896AD7643B0994A26E0C88833ABF173346`；Workbench与九类callback均恰好
一次。官方SIMION Lua CLI mock覆盖旧12项callback行为，并增加非零birth下local timeout/detector时钟、
full-domain ideal write-set、overlay启用及grid2 landing/唯一zero-step。resolved-region direct test另证明
real-PA区原样返回项目base write-set，analytic/zero区才覆盖。这里的等价结论限于活动物理主链与生产
observable合同；旧Formal仅供人工调试、且无生产consumer的stride step/native-grid/raw-splat TRACE未逐字迁移。
旧callback-chain构造函数也已从生产builder移入`tests/test_support/legacy_single_flight_program.py`，只服务冻结
旧SHA与回归表征；生产模块不导入tests，活动入口中不存在第二构造路径。职责迁移前后旧Program与successor
的bytes/SHA均保持不变。

## 兼容性与直接数值验证

改动前最小integration extension（cosine、phase 0、DC 0、birth 0.25/1.0 us）SHA-256为
`da428f426e7a89750bd009678c3695e545e617a2be07d48fc26fbfd229221fec`，18031 bytes；改动后含冻结kernel的
同一最小extension SHA-256为`934783f95ee444aa3120843733cfd31d45c7dcbe255910a9dafef5f477968954`，
24373 bytes。字节变化来自共享kernel嵌入和严格合同；活动cosine/phase-0/DC-0杆电压由专项解析点直接
确认等价。改动前独立`simion_transport.lua`字符SHA为
`57d9902ac7b350f7ac82268d00a370ec5f79c1cbb1e200e8a9ecf2eec1c2e4fb`。

数值正确性不由Python复制一套通用公式宣称。正式专项沿用本机SIMION 2020官方examples中的
module+self-test做法，通过官方batch入口：

```powershell
& 'C:\Program Files\SIMION-2020\simion.exe' --nogui --noprompt lua `
  common\multipole\test_simion_rf_drive.lua common\multipole\simion_rf_drive.lua
```

该命令只启动SIMION内置Lua解释器，脚本仅`dofile + assert + PASS`，不声明Workbench，不加载IOB/PA，
不调用refine、Fly或solver。0.6 s内输出`SIMION_RF_DRIVE_KERNEL_TEST=PASS`。解析期望只选0、π/2、π及
简单整数电压，覆盖sine/cosine、phase、RF scale、两组DC、common-mode scale、160/320步timestep、
birth+elapsed等价、静态电压和非法waveform/steps/polarity/重复ID/未知字段。官方模式依据为本机
`examples/multipole_expansion/multipole_expansion.lua`及其README；仓库Python discovery仅负责调用该
官方CLI、检查退出码并验证kernel没有clock/callback权威。

## 验证收据

- RF kernel与唯一assembler focused均PASS，其中assembler联合32/32；修改的PowerShell入口均通过parser；
  repository bindings `--check` PASS。
- common/multipole full suite：328/328 PASS；integration full suite：371/371 PASS。
- 两份活动schema-v3 successor逐行`ValidateOnly`：5/5与24/24，共29/29 PASS，101.5 s；只做准备和
  合同核验，未启动求解器。
- `common/verify_changed.ps1` L1在迁移中两次PASS（111.5 s、117.5 s），旧helper移出生产并刷新绑定后的
  最终复跑再次`CHANGED_GATE=PASS`（110.5 s）；其中common 328/328、integration
  371/371、oaTOF项目206/206、hexapole 22/22与octupole 28/28均PASS，其余适用静态门禁同样PASS。
- CLOC 2.10相对`f022bb490c1f30cc63ff4e838abbf05ce43311af`：total code
  `172997→178908`（+5911），production `126743→130878`（+4135），tests `46224→48000`
  （+1776），unclassified保持30。production增加主要为官方repository binding重冻结JSON +3470、
  唯一回调/纯组件Lua +731及runner PowerShell +32；生产Python净减98，反映旧chain移出活动builder。
  tests增加Python +1180、Lua +548、fixture JSON +48。分类器仍只警告三个既有SIMION probe文件，
  未新增unclassified。

本记录只授予共享RF运行时代码、冻结依赖、时钟边界和直接Lua回归的实现证据，不授予任何新物理结果。
