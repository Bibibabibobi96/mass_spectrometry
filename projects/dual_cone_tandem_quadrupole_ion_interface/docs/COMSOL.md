# COMSOL 气流最小层

## 结论与范围

本层定义一个用于首轮筛选的二维轴对称、全可压缩氮气模型。上游储气腔明确为纯 `N2`、`101325 Pa`、`300 K`，出口静压通过参数 continuation 降至 `400 Pa`；物理接口限定为 COMSOL **High Mach Number Flow**。最终稳态只有通过质量守恒阈值才产生合格场。它只产生供后续 SIMION 单向读取的规则 `r-z` 气体场，不求解离子，也不把离子反作用传回气体。

这是 `prototype_axisymmetric_empty_enclosure_gas_flow`，不是实机定量 CFD。轴对称代理明确排除了两组四极杆、泵口、级间透镜以及未确认的锥口圆角。因而它可以暴露喷流、阻塞流和连续介质失效风险，却不能证明实际杆区压力或质量流量。

入口与出口压比为 `400 / 101325`。对声明的理想氮气 `gamma=1.4`，该比值远低于临界压比，因此小孔附近可能阻塞并出现跨声速或超声速区。这里不能用只适合低马赫数的简化层流接口替代 High Mach Number Flow。

## 单一事实源

- `config/resolved_geometry.json`：经解释后的几何尺寸和坐标系。
- `config/gas_flow_science.json`：气体性质、边界条件、连续介质判据及字段语义。
- `config/comsol_solver_numerics.json`：网格、稳态伪时间压力 continuation、规则导出网格和产物名。

MATLAB 源码中没有隐藏入口压力、出口压力、温度、分子直径或网格尺寸。模型保存后，这些量也作为 COMSOL 全局参数可见。

## 运行

需要 CFD Module、LiveLink for MATLAB 和有效的 `HighMachNumberFlow` 许可。工具版本与连接
生命周期统一见[仓库操作指南](../../../docs/OPERATIONS.md)。以下命令在仓库根的 PowerShell Core 中
执行，先将 `<run_id>` 替换为预登记的新运行身份：

The production operation is installed as `msplatform.backends.comsol.solve_axisymmetric_gas_flow`.
It accepts four explicit scientific paths and an `ExecutionContext` from `execution.load_environment`.
The two MATLAB functions live only in `msplatform/backends/comsol/matlab`; neither reads a project root
or `DUAL_CONE_*` environment variables. Physical equations, High Mach interface, paired continuation,
terminal pressure/stabilization, lower-limit rejection and mass-balance checks retain their existing meaning.

```python
from pathlib import Path
from msplatform.execution import load_environment
from msplatform.backends.comsol import solve_axisymmetric_gas_flow

context = load_environment(Path("deployment/machine.json").absolute(),
                           workspace=Path("study").absolute(), profile="local")
field = solve_axisymmetric_gas_flow(
    Path("inputs/baseline.json").absolute(), Path("inputs/resolved_geometry.json").absolute(),
    Path("inputs/gas_flow_science.json").absolute(), Path("inputs/comsol_solver_numerics.json").absolute(),
    context=context,
)
print(field.reference)
```

The selected stage policy must declare `solve_gas_flow`, with the existing explicit process limits,
zero automatic retries and a retention class allowing `solver_native_binary`. Machine tools must name
`python`, `powershell`, `comsol_launcher` and `matlab_root`. No default commercial installation or
repository-local Python is searched. Initial native budgets need an explicit assessment; software fixtures
are not resource measurements.

The installed CLI is `python -I -m msplatform.backends.comsol.gas_flow`; use `--help` for its explicit
scientific/deployment arguments. The registered research profile still transports `RunId` and its four
frozen scientific definitions. It now requires `deployment_path`, `workspace` and `engineering_profile`
bindings through the existing execution compiler. Its PowerShell file only invokes the installed CLI;
it no longer creates another run owner, capacity session or launcher.

The normal owner freezes selected MATLAB/launcher/execution sources and input bytes, records the actual
native exit/release facts, and validates the exported field before publishing a `gas_field` product.
This product contains CSV, metadata and original scientific contracts; offline reading does not require
or hash the MPH. The model is a separately identified manifest output. Native execution and qualification
remain unverified until a new governed run supplies evidence.

Explicit reexport of a converged model uses `resume={"manifest": ..., "model": ..., "completion": ...}`
file records. The reader requires completed terminal publication, exact published model/writer-completion
membership, matching original scientific inputs, actual native exit and resource release. A failed export
can qualify only through those facts; a missing CSV is not a circular prerequisite. The existing MATLAB
stored terminal-tuple checks still run. This is reexport, not native checkpoint continuation or automatic
recompute. Original model bytes remain protected and are never saved by this path.

## 几何与边界

流体域是一个无内部接缝的轴对称多边形：上游短储气腔、第一孔 `0.25 mm` 轴向孔筒、两锥之间的空间、第二孔 `0.5 mm` 轴向孔筒，以及沿第二锥张开到半径 `23.5 mm` 后连续延伸至 `z=120.00 mm` 的空圆柱，整个位于 `z=120.00 mm` 的后端面施加 `400 Pa`。圆四极杆和位于 `z=110.22..110.72 mm` 的孔板均不作为 CFD 阻塞物；这是最简空包络气流代理。孔板仍保留在 SIMION 电极和撞壁几何中，因此能筛选离子是否通过，但本模型不声称预测板前积压、孔内射流或板后膨胀。使用单一轮廓避免零面积接触产生退化自由度；几何边界通过坐标选择，不依赖 COMSOL 自动编号。

- 上游储气腔整个前平面：Subsonic 压力入口，静压 `p0=101325 Pa`、温度 `T0=300 K`。入口速度由内部解决定，不规定马赫数或质量流量。
- 下游大腔整个末端平面：Subsonic 静压出口，目标 `400 Pa`，代表理想恒压后端。
- 其余非轴边界：首轮采用无滑移、绝热壁；不加入湍流、传热固体、杆或泵口。
- 氮气黏度与导热率采用 300 K 常数 `1.76e-5 Pa*s` 和 `0.02583 W/(m*K)`；不使用温度相关 Sutherland 幂律，从而避免非线性试探步越出温度定义域。
- 稳态求解使用阻尼 segregated 迭代和 COMSOL 的伪时间 CFL 控制；出口压力从易收敛状态逐级降至 `400 Pa`，同时把 High-Mach 人工各向同性扩散从 `0.5` 降至合同记录的终态 `0.1`。中间级只传递初值，不导出、不规定腔内压力分布；终态稳定化值随元数据公开，因此结果仍限于 Prototype。
- COMSOL `LowerLimit` 将迭代试探值限制为 `T>=1 K`、`p>=1 Pa`；限制仅防止声速等中间表达式进入无定义域，任何触及该下限的收敛终态仍由温度、压力和质量守恒校验拒绝。
- 轴线：二维轴对称接口自动处理。

求解按 JSON 给定的出口压力序列作稳态参数 continuation，最终到达 `400 Pa`；任一级伪时间迭代失败或最终质量守恒不合格即失败。模型采用层流作为首版封闭假设；这不是对真实湍流状态的确认。

## 输出合同

成功运行应产生：

- `comsol/axisymmetric_gas_flow.mph`
- `comsol/gas_field_rz.csv`
- `comsol/gas_field_metadata.json`
- `comsol_run_report.txt`

CSV 必须按 `z` 主序、`r` 次序排列，列顺序严格为：

```text
z_index,r_index,z_mm,r_mm,p_pa,temperature_k,u_z_m_per_s,u_r_m_per_s,rho_kg_per_m3,mach,knudsen_aperture,fluid_mask
```

规则矩形网格中流体域外的物理量全部为 `NaN` 且 `fluid_mask=0`。元数据记录 CSV 与三个源合同的 SHA-256、网格轴、坐标系、请求出口压力、进出口质量流量、质量守恒误差、最大马赫数和最大孔径 Knudsen 数。SIMION运行插值遵循`gas_field_interface.json`：普通单元双线性插值，切割单元仅对有效流体角点权重归一化；无有效支撑或越出治理域即拒绝，不作域外外推。轴对称映射采用`r=sqrt(x^2+y^2)`。COMSOL 二维轴对称分量固定为径向 `u`、周向 `v`、轴向 `w`；`u_z_m_per_s` 与质量流量使用 `w`，`u_r_m_per_s` 使用 `u`。

运行后必须执行独立验证：

```powershell
python -m msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field_validation `
  --csv C:\absolute\path\gas_field_rz.csv `
  --metadata C:\absolute\path\gas_field_metadata.json `
  --science projects\dual_cone_tandem_quadrupole_ion_interface\config\gas_flow_science.json `
  --numerics projects\dual_cone_tandem_quadrupole_ion_interface\config\comsol_solver_numerics.json `
  --geometry projects\dual_cone_tandem_quadrupole_ion_interface\config\resolved_geometry.json
```

验证器检查身份、哈希、字段与行序、规则网格、有限值、理想气体密度闭合、质量守恒和出口压力。`Kn > 0.1` 时仍可保留结果作失效诊断，但验证摘要会把定量连续介质声明标为不允许；这提示后续需要 DSMC/混合方法，而不是把连续介质结果当成可靠真值。

验证通过后，用项目工作流把 CSV 编译为自包含、带哈希的 SIMION Lua 场和严格 manifest：

```powershell
projects\dual_cone_tandem_quadrupole_ion_interface\workflows\gas_assisted_transport\build_gas_runtime.ps1 `
  -ComsolRunDirectory <published_run_directory> -InterfacePath <explicit_interface_json> `
  -OutputDir <explicit_output_directory> -PythonExe <installed_python>
```

编译器将径向速度映射到三维笛卡尔分量，切割单元按上述有效角点权重处理；无有效流体支撑或越出治理域时立即报错，不做域外外推或最近邻填充。

## 最小验收

1. 静态测试确认源码确实创建 `HighMachNumberFlow`、二维轴对称几何、稳态伪时间压力 continuation、`mphinterp` 导出和失败关闭报告。
2. 合同夹具验证规则 `r-z` 字段可以通过独立 Python 校验，哈希篡改会失败。
3. 在有许可的机器上首次真实运行时，还必须人工检查网格收敛、喷口附近激波/梯度分辨率、进出口质量守恒、最大 Mach 与 Kn 分布。
4. 在加入泵口与杆几何并用实测压力或泵速校准前，不提升到 `Validated`，也不据此给出仪器绝对传输率。

COMSOL 接口依据：[Compressible Flow for All Mach Numbers](https://doc.comsol.com/6.4/doc/com.comsol.help.cfd/cfd_ug_fluidflow_high_mach.08.45.html) 与 [High Mach Number Flow 的 Outlet](https://doc.comsol.com/6.4/doc/com.comsol.help.cfd/cfd_ug_fluidflow_high_mach.08.21.html)。

[返回项目状态](PROJECT.md)

## Migration validation boundary

The new installed operation and reader require ordinary-install and governed native acceptance.
Inert tests use explicitly marked synthetic files only; they do not establish COMSOL solve success,
High Mach license availability, convergence, grid adequacy, quantitative CFD or ion transmission.
Official COMSOL 6.4 High Mach documentation was reviewed on 2026-11-09; this migration changes input
transport/ownership and retains the existing physics/API expressions rather than substituting a new model.

## Current joint gas runtime projection

The existing validation CLI above remains the source-quality owner. Current
SIMION preparation then uses component `gas_field.prepare_cfd_gas_field` and
backend `gas_runtime.materialize_gas_runtime`; the PowerShell entry calls these
same functions. Explicit CSV/metadata/three source records remain supported,
without inventing a producer manifest. An optional actual published producer
reference is retained and checked; malformed or mismatched explicit references
do not fall back to direct data. Original CFD files, source EOS and raw axis
values are preserved. The current compiled interface is version2 with one joint
sample function and explicit per-source numerical policy; it does not reopen
COMSOL or change the field producer's original qualification.
