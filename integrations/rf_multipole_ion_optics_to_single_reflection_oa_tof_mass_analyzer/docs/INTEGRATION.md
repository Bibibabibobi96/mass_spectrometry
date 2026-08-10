# RF多极杆离子光学到单次反射oaTOF集成

本文件是四、六、八极杆到单次反射oaTOF连接的当前状态权威。项目自身资格分别由各项目
`docs/PROJECT.md`维护；完整运行表、失败链和被取代方案只查日期化history。

## 当前身份

- integration ID：`rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer`。
- 唯一公开执行入口：
  [`workflows/family_source_closure/execute.ps1`](../workflows/family_source_closure/execute.ps1)。
- 调用者只选择campaign和`ExperimentId`；源项目、求解器、工况、母样本、resolved design和数值设置
  必须从冻结的source run派生，不能在CLI重复声明。
- 四、六、八极杆分别选择模式中性的direct-mating connection profile；连接器、位姿、公共电位、
  时钟和场责任区由resolved connection决定。
- 当前结果均为功能或诊断证据，不授予连续相空间、数值收敛、优化、Candidate或整机Formal资格。

## 机器权威

| 职责 | 入口 |
|---|---|
| 连接拓扑与端口 | [`connection_profiles.json`](../config/connection_profiles.json) |
| 声明式实验 | [`experiment_campaign.json`](../config/experiment_campaign.json) |
| 执行适配 | [`execution_adapter_profiles.json`](../config/execution_adapter_profiles.json) |
| 单流程布局 | [`single_flight_layout_profiles.json`](../config/single_flight_layout_profiles.json) |
| runtime bindings | [`config/*_runtime_binding.json`](../config/) |
| 依赖与实现身份 | [`family_runtime_dependencies.json`](../config/family_runtime_dependencies.json)、[`family_runtime_implementation.json`](../config/family_runtime_implementation.json) |
| oaTOF可调变量 | [oaTOF `design_variables.json`](../../../projects/single_reflection_oa_tof_mass_analyzer/config/design_variables.json) |
| oaTOF优化包络 | [oaTOF `optimization_envelope.json`](../../../projects/single_reflection_oa_tof_mass_analyzer/config/optimization_envelope.json) |

repository-text SHA由`runtime/refresh_family_repository_bindings.py`单向刷新；campaign source SHA由
`workflows/family_source_closure/refresh_campaign_source_bindings.py`冻结。已发布终态manifest的
campaign不得改写。

## 两种执行策略

campaign的`execution_strategy`显式选择下列一种策略：

| 策略 | 物理流程 | 适用边界 |
|---|---|---|
| `staged_three_stage` | COMSOL接口运输 → COMSOL脉冲捕获 → SIMION分析器 | 既有分阶段campaign；未声明策略时的兼容默认 |
| `simion_single_flight` | 同一次SIMION Fly连续完成多极杆、连接器、脉冲加速、无场漂移、反射和检测 | 当前八极杆整体前端及参数化布局候选 |

`simion_single_flight`中的`multipole_handoff`、`pre_pulse_state`和
`local_accelerator_exit`只是同一轨迹的checkpoint，不是导出、重新释放、时间清零或第二次Fly。
任何文档或分析把它们解释为三段重启，均与当前流程冲突。

## 单流程PA与屏蔽

当前单流程仍使用四个Workbench实例：

| 槽位 | PA角色 | 说明 |
|---:|---|---|
| 1 | flight tube | 接地无场管 |
| 2 | reflectron | 双级反射器 |
| 3 | combined frontend | 多极杆、整体屏蔽、连接器和oaTOF加速器组成一个PA |
| 4 | detector | GUI可见数值终止层 |

多极杆和加速器不是两个相互重启的PA。圆形多极杆罩、接地圆套筒、带孔法兰和加速器罩形成连续
`0 V`屏蔽；任一profile声明非零屏蔽都会在GEM/Program生成前失败关闭。

combined frontend当前电极映射为：

| 电极号 | 角色 |
|---:|---|
| 1–8 | 八极杆杆组 |
| 9 | 连续接地屏蔽罩与连接器 |
| 10–17 | oaTOF加速器功能电极 |
| 18 | 入口参考套筒 |
| 19 | 入口板 |

每个run生成的`single_flight_frontend_contract.json`是编号和几何的机器权威；本文只提供识别性摘要。
加速器电极不能再按“10–17且没有18/19”解释。

## 参数合同与自动重构

单流程布局profile的`design_overrides`只能引用oaTOF变量目录中登记的变量：

- `continuous`变量在目录安全范围和适用优化包络内可直接给值；
- `integer`变量是离散设计量，必须为合法整数并触发相应拓扑重建；
- 理论派生字段不得直接覆盖，由时间聚焦和加速器—反射器耦合编译器重算；
- 拓扑变化必须使用专用编译路径，不能伪装成连续标量；
- 网格、trajectory quality和时间步属于数值合同，不反写物理设计。

当前单流程编译顺序为：

`layout profile + design overrides → candidate baseline → theory closure → resolved geometry → PA rebuild plan`

理论闭合自动更新所影响的加速器、无场区、反射器、检测器对称位置、能量包络和电压。运行时只在
run-local目录重建`frontend_pa`、`flight_tube_pa`或`reflectron_pa`中实际变化的PA，并把resolved
值绑定到Lua；不修改oaTOF Formal资产，也不允许SIMION实现反向改写参数。

范围校验只证明可编译，不证明候选可行或更优。每个候选仍须重新完成PA贯通、孔外接地guard、
电极映射、真实Fly和数值敏感性检查。

## 当前连续单流程结论

当前1.5 mm入口参考套筒、10 eV目标注入的N=1000八极杆连续基准为
`1000→968→950→948→948`，总检测传输94.8%；`pre_pulse_state`能量为
`10.01783±0.05134 eV`。handoff正交加速方向角度σ为`1.81390°`，脉冲前σz为
`0.54583 mm`，因此已闭合的是高传输和目标能量，不是角度或z方向展宽。

首个参数化候选把理论源z全宽从1.0 mm改为2.2 mm。编译器自动扩大能量包络并重算反射器二级长度和
背板电压，run-local只重建受影响PA。真实八极杆输入未改变，传输仍为948/1000，分辨率变化−0.30%，
没有性能收益；该结果只证明参数合同与自动重构链工作。完整数值、run索引和声明边界见
[2026-08-10候选记录](../../../docs/history/20260810__oatof-source-z22-auto-rebuild.md)。

绝对RF时钟稳态源的5×200诊断为1000→1000→1000→996。初次聚合把oaTOF基础Program输出的原生
`ion_time_of_flight`误标成绝对探测时刻，得到的`R=49.54`及基于该时刻的x条件筛选结论均已失效；
逐粒子补回`source_release`仪器时刻后，同一真实轨迹为直接FWHM `1.97584 ns`、`R=19417.37`。
修正后能散与单独角度的线性解释量均约1%或更低，位置三分量为6.63%；完整`xyz-vxyz`相空间为
22.67%。当前主要物理嫌疑是加速方向`z-vz`相空间相对理论时间聚焦接受线的残差，而不是总能散、
单独x宽度或总发散角。该结果仍缺相邻PA网格、RF时间步和当前样本的逐因素SIMION重放，只是
`DIAGNOSTIC_ONLY`。

目标能量只能在连续链`pre_pulse_state`、且粒子位于repeller与grid1之间时验证。
`terminal`或`multipole_handoff`能量只作接口诊断。

## 证据路由

- 当前10 eV、1.5 mm套筒N=1000基准：
  [history](../../../docs/history/20260805__octupole-terminal-15mm-sleeve-single-flight-n1000.md)
- 入口套筒与加速器内目标能量修正：
  [history](../../../docs/history/20260805__octupole-15mm-sleeve-accelerator-energy.md)
- 早期10 eV布局诊断：
  [history](../../../docs/history/20260805__octupole-10ev-single-flight.md)
- 开孔离散、孔径选择和受控反事实等旧完整过程：以对应run manifest及根
  [history目录](../../../docs/history/)为准；current文档不复制多轮运行表。

## 开放任务

1. 对当前连续单流程补相邻PA网格和RF时间步，关闭孔边缘离散与峰宽敏感性；未完成前保持
   `INCONCLUSIVE_DIAGNOSTIC_ONLY`。
2. 若需要跨求解器结论，另行授权同几何、同源、同绝对时钟和同checkpoint的COMSOL连续前端。
3. 用修正后的绝对探测时钟对当前稳态母样本执行逐因素SIMION重放，优先比较`z`、`vz`、二者残差和
   组合臂；随后补第二母样本或预登记不确定度。
4. 新的2 mm、3 mm或其他源宽必须各自形成受治理layout profile并重建受影响PA；不能从2.2 mm
   无收益结果直接外推。

## 静态门禁

[`verify_integration.ps1`](../verify_integration.ps1)只验证连接、端口、profile、source/design冻结、
repository identity和失败关闭逻辑，不运行COMSOL、SIMION、MATLAB或CAD，也不替代物理资格。
