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

要求 COMSOL 6.4、CFD Module、LiveLink for MATLAB，以及能创建 `HighMachNumberFlow` 的有效许可。先设置一个明确的产物目录：

```powershell
$env:DUAL_CONE_GAS_FLOW_OUTPUT_DIR = 'C:\absolute\path\to\gas-flow-output'
comsol mphserver
matlab -batch "addpath('projects/dual_cone_tandem_quadrupole_ion_interface/comsol'); run_axisymmetric_gas_flow"
```

实际 COMSOL 批处理启动方式会随安装方式改变；也可从已连接 COMSOL Server 的 MATLAB 会话运行入口脚本。入口脚本任何异常都会写 `comsol_run_report.txt` 的 `STATUS=FAIL` 并重新抛出，不会切换到其他物理接口、伪造 CSV 或留下通过状态。只有求解、插值和质量守恒检查全部通过才写 `STATUS=PASS`。

本机已确认 COMSOL 6.4 Build 293 与 LiveLink 可以启动。默认全耦合 Newton 及瞬态压力缓降均在大压比下失败，因此当前实现采用 High Mach Number Flow 对稳态问题默认支持的伪时间/CFL continuation，并对出口压力作参数 continuation；只有最终 `400 Pa` 解完成并通过质量守恒检查才产生合格场。失败报告保留在工作区 artifacts，入口严格保持 `STATUS=FAIL`。

2026-09-08 的真实 COMSOL 6.4 运行已校正轴对称速度映射（径向 `u`、轴向 `w`），并依次验证阻塞入口、亚声速定压出口、压力 continuation、阻尼 segregated、CFL 伪时间和常数氮气输运。`20260908_axisymmetric_gas_flow_pseudotime6` 在强制全后端亚声速的出口附近产生速度残差 `NaN`，因此没有导出 CSV、没有 canonical 场，也没有下游 SIMION 轨迹声明。该失败只否定了不一致的全亚声速出口设置，不否定用户确认的理想 `400 Pa` 恒压储槽代理。

2026-09-10 又以同一全后端 `400 Pa` 边界真实运行 Hybrid outlet；API 与模型构建通过，但求解仍在后端附近产生 `u/w` 残差 `NaN`。该历史 run 保持失败关闭；`uniform_rear_gas_field.json` 规定的均匀后端场只作快速对照，不得称为 CFD 结果。

同日加入 `z=110.22..110.72 mm` 孔板的 CFD 解虽完成 continuation，但进出口质量流量差 `3.82%`，被 `1%` 门禁拒绝。按最简模型边界，随后只从 CFD 中排除孔板阻塞、仍将孔板保留在 SIMION；`20260910_z120_empty_cfd_comsol` 对纯氮气完成至 `z=120 mm / 400 Pa`，质量流量差 `0.848%`、最大马赫数 `4.52`，通过并导出带哈希的场。该结果只支持空包络 Prototype，不支持孔板气动效应声明。

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

- `axisymmetric_gas_flow.mph`
- `gas_field_rz.csv`
- `gas_field_metadata.json`
- `comsol_run_report.txt`

CSV 必须按 `z` 主序、`r` 次序排列，列顺序严格为：

```text
z_index,r_index,z_mm,r_mm,p_pa,temperature_k,u_z_m_per_s,u_r_m_per_s,rho_kg_per_m3,mach,knudsen_aperture,fluid_mask
```

规则矩形网格中流体域外的物理量全部为 `NaN` 且 `fluid_mask=0`。元数据记录 CSV 与三个源合同的 SHA-256、网格轴、坐标系、请求出口压力、进出口质量流量、质量守恒误差、最大马赫数和最大孔径 Knudsen 数。SIMION 只能在 `fluid_mask=1` 内做双线性插值，禁止外推；轴对称映射采用 `r=sqrt(x^2+y^2)`。COMSOL 二维轴对称分量固定为径向 `u`、周向 `v`、轴向 `w`；`u_z_m_per_s` 与质量流量使用 `w`，`u_r_m_per_s` 使用 `u`。

运行后必须执行独立验证：

```powershell
python projects/dual_cone_tandem_quadrupole_ion_interface/analysis/validate_gas_field.py `
  --csv C:\absolute\path\gas_field_rz.csv `
  --metadata C:\absolute\path\gas_field_metadata.json
```

验证器检查身份、哈希、字段与行序、规则网格、有限值、理想气体密度闭合、质量守恒和出口压力。`Kn > 0.1` 时仍可保留结果作失效诊断，但验证摘要会把定量连续介质声明标为不允许；这提示后续需要 DSMC/混合方法，而不是把连续介质结果当成可靠真值。

验证通过后，用项目工作流把 CSV 编译为自包含、带哈希的 SIMION Lua 场和严格 manifest：

```powershell
projects\dual_cone_tandem_quadrupole_ion_interface\workflows\gas_assisted_transport\build_gas_runtime.ps1 `
  -ComsolRunDirectory C:\absolute\path\to\gas-flow-output
```

编译器采用合同声明的轴对称双线性插值，把径向速度映射到三维笛卡尔分量；越出治理域或插值单元触及非流体网格时立即报错，不做外推或最近邻填充。

## 最小验收

1. 静态测试确认源码确实创建 `HighMachNumberFlow`、二维轴对称几何、稳态伪时间压力 continuation、`mphinterp` 导出和失败关闭报告。
2. 合同夹具验证规则 `r-z` 字段可以通过独立 Python 校验，哈希篡改会失败。
3. 在有许可的机器上首次真实运行时，还必须人工检查网格收敛、喷口附近激波/梯度分辨率、进出口质量守恒、最大 Mach 与 Kn 分布。
4. 在加入泵口与杆几何并用实测压力或泵速校准前，不提升到 `Validated`，也不据此给出仪器绝对传输率。

COMSOL 接口依据：[Compressible Flow for All Mach Numbers](https://doc.comsol.com/6.4/doc/com.comsol.help.cfd/cfd_ug_fluidflow_high_mach.08.45.html) 与 [High Mach Number Flow 的 Outlet](https://doc.comsol.com/6.4/doc/com.comsol.help.cfd/cfd_ug_fluidflow_high_mach.08.21.html)。

[返回项目状态](PROJECT.md)
