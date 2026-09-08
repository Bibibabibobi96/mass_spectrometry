# COMSOL 气流最小层

## 结论与范围

本层定义一个用于首轮筛选的二维轴对称、稳态、全可压缩氮气模型。入口为总压和总温，出口为静压；物理接口限定为 COMSOL **High Mach Number Flow**。它只产生供后续 SIMION 单向读取的规则 `r-z` 气体场，不求解离子，也不把离子反作用传回气体。

这是 `prototype_axisymmetric_empty_enclosure_gas_flow`，不是实机定量 CFD。轴对称代理明确排除了两组四极杆、泵口、级间透镜以及未确认的锥口圆角。因而它可以暴露喷流、阻塞流和连续介质失效风险，却不能证明实际杆区压力或质量流量。

入口与出口压比为 `400 / 101325`。对声明的理想氮气 `gamma=1.4`，该比值远低于临界压比，因此小孔附近可能阻塞并出现跨声速或超声速区。这里不能用只适合低马赫数的简化层流接口替代 High Mach Number Flow。

## 单一事实源

- `config/resolved_geometry.json`：经解释后的几何尺寸和坐标系。
- `config/gas_flow_science.json`：气体性质、边界条件、连续介质判据及字段语义。
- `config/comsol_solver_numerics.json`：网格、压力延拓、容差、规则导出网格和产物名。

MATLAB 源码中没有隐藏入口压力、出口压力、温度、分子直径或网格尺寸。模型保存后，这些量也作为 COMSOL 全局参数可见。

## 运行

要求 COMSOL 6.4、CFD Module、LiveLink for MATLAB，以及能创建 `HighMachNumberFlow` 的有效许可。先设置一个明确的产物目录：

```powershell
$env:DUAL_CONE_GAS_FLOW_OUTPUT_DIR = 'C:\absolute\path\to\gas-flow-output'
comsol mphserver
matlab -batch "addpath('projects/dual_cone_tandem_quadrupole_ion_interface/comsol'); run_axisymmetric_gas_flow"
```

实际 COMSOL 批处理启动方式会随安装方式改变；也可从已连接 COMSOL Server 的 MATLAB 会话运行入口脚本。入口脚本任何异常都会写 `comsol_run_report.txt` 的 `STATUS=FAIL` 并重新抛出，不会切换到其他物理接口、伪造 CSV 或留下通过状态。只有求解、插值和质量守恒检查全部通过才写 `STATUS=PASS`。

本机已确认 COMSOL 6.4 Build 293 与 LiveLink 可以启动，并实际执行到稳态求解器。模型构建、连通流体域、High Mach 边界节点和网格均已越过 API 验收；当前压力延拓在初始参数仍达到 Newton 最大迭代数，因此没有合格 `.mph`、CSV 或可供 SIMION 使用的气体场声明。失败报告保留在工作区 artifacts，入口严格保持 `STATUS=FAIL`。

下一次数值工作应从 COMSOL 的 Stationary with Initialization / 瞬态预初始化着手，而不是向仓库写入规定压力曲线或用 Python 轨迹替代。只有产物目录中出现 `STATUS=PASS` 且独立校验通过，才允许编译 SIMION 气体场。

## 几何与边界

流体域由两个相交的轴对称多边形构成：上游 2 mm 直管、第一锥内表面至第二锥平面、第二孔外侧不可穿透挡板，以及从第二孔沿第二锥张开到半径 23.5 mm 后延伸至 `z=108 mm` 的空圆柱。几何边界通过坐标选择，不依赖 COMSOL 自动编号。

- 上游平面：亚声速总状态入口，`p0=101325 Pa`、`T0=300 K`。
- 下游平面：亚声速静压出口，目标 `400 Pa`。
- 其余非轴边界：首轮采用滑移、绝热壁，明确忽略黏性边界层；这是为快速筛选喷流与压降保留的最简封闭。
- 轴线：二维轴对称接口自动处理。

求解按 JSON 给定的出口压力序列逐步下降，任一步不收敛即失败。模型采用层流作为首版封闭假设；这不是对真实湍流状态的确认。

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

规则矩形网格中流体域外的物理量全部为 `NaN` 且 `fluid_mask=0`。元数据记录 CSV 与三个源合同的 SHA-256、网格轴、坐标系、请求出口压力、进出口质量流量、质量守恒误差、最大马赫数和最大孔径 Knudsen 数。SIMION 只能在 `fluid_mask=1` 内做双线性插值，禁止外推；轴对称映射采用 `r=sqrt(x^2+y^2)`。

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

1. 静态测试确认源码确实创建 `HighMachNumberFlow`、二维轴对称几何、压力延拓、`mphinterp` 导出和失败关闭报告。
2. 合同夹具验证规则 `r-z` 字段可以通过独立 Python 校验，哈希篡改会失败。
3. 在有许可的机器上首次真实运行时，还必须人工检查网格收敛、喷口附近激波/梯度分辨率、进出口质量守恒、最大 Mach 与 Kn 分布。
4. 在加入泵口与杆几何并用实测压力或泵速校准前，不提升到 `Validated`，也不据此给出仪器绝对传输率。

COMSOL 接口依据：[Compressible Flow for All Mach Numbers](https://doc.comsol.com/6.4/doc/com.comsol.help.cfd/cfd_ug_fluidflow_high_mach.08.45.html) 与 [High Mach Number Flow 的 Outlet](https://doc.comsol.com/6.4/doc/com.comsol.help.cfd/cfd_ug_fluidflow_high_mach.08.21.html)。
