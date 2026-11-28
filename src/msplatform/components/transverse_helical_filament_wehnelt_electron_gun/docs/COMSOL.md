# 横置螺旋灯丝Wehnelt电子枪：COMSOL实施与验证

本文只说明COMSOL三阶段模型、活动入口和GUI验收。当前组件资格与开放任务只见
[`PROJECT.md`](PROJECT.md)；历史选型与旧数值见[`../../../../../docs/history/projects/transverse_helical_filament_wehnelt_electron_gun/PROJECT_HISTORY.md`](../../../../../docs/history/projects/transverse_helical_filament_wehnelt_electron_gun/PROJECT_HISTORY.md)。

## 活动入口

- 受治理商业入口：`python -m msplatform.cli wehnelt-build-only --compiled-inputs <bundle> --execution-environment <deployment> --environment-profile <profile> --workspace <directory> --artifact-root <store>`；正常调用由注册 profile 编译这些参数，运行身份由后端 Store 生成。
- Installed Python operation: `msplatform.backends.comsol.build_wehnelt_model` uses the same managed owner and LiveLink launcher as the EI operation. The CLI supplies the explicit `ExecutionContext` and `ArtifactStore`; neither entry adds a second scheduler or publisher.
- 几何：[`phase1_geometry_coil_transverse.m`](../../../../../src/msplatform/backends/comsol/matlab/phase1_geometry_coil_transverse.m)
- 静电：[`phase2_electrostatics_coil_transverse.m`](../../../../../src/msplatform/backends/comsol/matlab/phase2_electrostatics_coil_transverse.m)
- 热发射CPT：[`phase4_thermal_emission_coil_transverse.m`](../../../../../src/msplatform/backends/comsol/matlab/phase4_thermal_emission_coil_transverse.m)
- 合同绑定：[`apply_wehnelt_contract_parameters.m`](../../../../../src/msplatform/backends/comsol/matlab/apply_wehnelt_contract_parameters.m)
- Run paths: each canonical stage requires `(resolvedContractPath, runDirectory)` from the existing owner; no environment or checkout discovery.
- Read-only cold verification: [`verify_wehnelt_model.m`](../../../../../src/msplatform/backends/comsol/matlab/verify_wehnelt_model.m) targets only the final unsolved phase4 MPH and never sets parameters, Compute or saves it.
- 组件门禁：`src/msplatform/workflows/resources/wehnelt_verify.ps1`

版本与启动见[操作指南](../../../../../docs/OPERATIONS.md)。三阶段脚本不包含COMSOL安装路径或`mphstart`，只能由仓库统一
LiveLink入口调用。

## 合同与阶段边界

注册编译器冻结`baseline + numerical modes + resolved + mode`并写入带逐项身份的记录。Python适配器
复核实际副本的路径、bytes和SHA-256，再沿唯一resolver重算并逐字段比较resolved；缺失、重复、过期、
越界或身份不匹配均在商业启动前失败关闭。三阶段显式接收managed owner写入的同一resolved路径；
旧环境变量任务适配器和checkout路径发现已删除。实际MATLAB/launcher资源由现有native source freezer
从所选安装包冻结并保护，不从checkout补齐。测试、仓库构建配置与门禁工具不属于科学输入。

| 阶段 | 职责 | build-only允许 |
|---|---|---|
| phase1 | 横置灯丝、Wehnelt、阳极几何 | 建几何并保存中间MPH |
| phase2 | 材料、选择集、静电、网格、Study和结果节点 | 构建树，不运行静电求解 |
| phase4 | 热发射CPT、瞬态Study、粒子数据集和轨迹图 | 构建树，不运行粒子求解 |

编号保留phase1/2/4以维持实验谱系；旧phase3冷发射不属于活动流水线。

## 运行证据

`msplatform.cli wehnelt-build-only`是当前唯一注册的商业入口。显式`ArtifactStore`在准入前登记运行，
现有`run_managed_stage`持有writer锁、捕获入口源码、保存冻结输入和checkpoint，并在真实native writer
与资源释放证据闭合后发布成功或失败；CLI不再写第二份终态、manifest或恢复记录。启动、原生异常、
报告不匹配、输出缺失及冷读篡改均失败关闭，失败run不包含`prepared_model`产品。

成功产品包含三个原始MPH、build/verify报告及resolved合同；build-only不调用`.runAll`，不执行静电
或粒子求解。独立冷读必须为第二个native operation，确认解数据为空、Compute为零且源MPH未改写。
发布中断和失联writer分别沿用Store的`recover_run_publication`／`recover_interrupted_runs`合同；
本组件没有旧PowerShell `ResumeFinalization`旁路。当前证据与未运行的求解层级见
[PROJECT 的资格状态](PROJECT.md#资格状态)。

## GUI与功能验收

未来`functional_reference`至少必须：

1. 冻结N=100可复现粒子源和seed；
2. 运行静电Study与CPT Study；
3. 保存并重开最终MPH；
4. 由GUI `Study → Compute`等价复算；
5. 核对电子质量、电荷、发射分布、`Freeze`壁面、收集面和完备终态；
6. 输出逐粒子状态、summary、manifest与资产SHA。

在这些步骤完成前，build-only不得表述为Candidate、Formal、收集效率或性能闭合。
