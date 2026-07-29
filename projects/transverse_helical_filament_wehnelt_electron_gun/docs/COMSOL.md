# 横置螺旋灯丝Wehnelt电子枪：COMSOL实施与验证

本文只说明COMSOL三阶段模型、活动入口和GUI验收。当前项目资格与开放任务只见
[`PROJECT.md`](PROJECT.md)；历史选型与旧数值见[`history/PROJECT_HISTORY.md`](history/PROJECT_HISTORY.md)。

## 活动入口

- 受治理商业入口：`../run_build_only_smoke.ps1 -RunId <run_id>`
- 几何：`../phase1_geometry_coil_transverse.m`
- 静电：`../phase2_electrostatics_coil_transverse.m`
- 热发射CPT：`../phase4_thermal_emission_coil_transverse.m`
- 合同绑定：`../apply_wehnelt_contract_parameters.m`
- MATLAB路径：`../egun_paths.m`
- 项目门禁：`../verify_project.ps1`
- build-only生产任务：`../comsol/build_only_smoke.m`

版本与启动只采用仓库根README。三阶段脚本不包含COMSOL安装路径或`mphstart`，只能由仓库统一
R2025b/COMSOL入口调用。

## 合同与阶段边界

入口冻结`baseline + numerical mode → resolved`及实际MATLAB源码。三阶段都必须显式接收同一resolved
路径；缺失、过期或身份不匹配时失败关闭。

| 阶段 | 职责 | build-only允许 |
|---|---|---|
| phase1 | 横置灯丝、Wehnelt、阳极几何 | 建几何并保存中间MPH |
| phase2 | 材料、选择集、静电、网格、Study和结果节点 | 构建树，不运行静电求解 |
| phase4 | 热发射CPT、瞬态Study、粒子数据集和轨迹图 | 构建树，不运行粒子求解 |

编号保留phase1/2/4以维持实验谱系；旧phase3冷发射不属于活动流水线。

## 运行证据

`run_build_only_smoke.ps1`是当前唯一注册的商业入口。run目录建立后先写可复核的`interrupted`三件套，
明确异常才转为`failed`，全部报告判据通过才转为`success`。输入、输出、公共COMSOL入口、Static gate、
execution profile和manifest机制均冻结并校验SHA。

当前闭合证据完成了真实MATLAB R2025b/COMSOL 6.4三阶段build-only，三个MPH非空，GUI参数绑定和
模型树通过；未运行静电或粒子求解器。历史超时、空manifest、缓存污染和clean retry过程只见
[`history/20260728__pre-document-consolidation-project.md`](history/20260728__pre-document-consolidation-project.md)。

## GUI与功能验收

未来`functional_reference`至少必须：

1. 冻结N=100可复现粒子源和seed；
2. 运行静电Study与CPT Study；
3. 保存并重开最终MPH；
4. 由GUI `Study → Compute`等价复算；
5. 核对电子质量、电荷、发射分布、`Freeze`壁面、收集面和完备终态；
6. 输出逐粒子状态、summary、manifest与资产SHA。

在这些步骤完成前，build-only不得表述为Candidate、Formal、收集效率或性能闭合。
