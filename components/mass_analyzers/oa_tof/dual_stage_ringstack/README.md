# oa-TOF 双级环栈反射镜组件

本目录管理当前 oa-TOF 质量分析器子组件的可复现源文件。它不是完整质谱仪项目；离子源、
离子导向器、电子枪及未来整机装配均在各自组件或系统目录中维护。

## 权威入口

- 当前状态、参数、历史结论与开放问题：
  [`docs/项目_oaTOF双级环栈反射镜.md`](docs/项目_oaTOF双级环栈反射镜.md)
- 正式 COMSOL 建模脚本：
  [`comsol/ms_oaTOF_two_stage_ringstack_reflectron.m`](comsol/ms_oaTOF_two_stage_ringstack_reflectron.m)
- CAD 导出入口：
  [`cad/ms_export_oatof_to_solidworks.m`](cad/ms_export_oatof_to_solidworks.m)
- SIMION 实施与验证记录：[`simion/docs/README.md`](simion/docs/README.md)
- MATLAB R2025b LiveLink静态/全链路测试：
  [`tests/comsol/verify_oatof_comsol_sync.m`](tests/comsol/verify_oatof_comsol_sync.m)、
  [`tests/comsol/test_oatof_r2025b_full_chain.m`](tests/comsol/test_oatof_r2025b_full_chain.m)
- 跨求解器几何门禁：
  [`tests/cross_solver/verify_geometry_contract.ps1`](tests/cross_solver/verify_geometry_contract.ps1)。
  COMSOL/SIMION联动统计前必须先通过；它检查共享基线、参数派生、正式Lua哈希、IOB实例
  位置以及PA尺寸/网格。
- 路径解析契约：[`oatof_paths.m`](oatof_paths.m)

当前唯一正式COMSOL基线（2026-07-14，MATLAB R2025b/COMSOL 6.4）：N=1000、1000/1000到达，
平均TOF 31.4478763926 µs、σ=0.897802250264 ns、`R=t/(2σ)=17513.8102`。详细条件和历史值
边界见项目主文档§6.26；不得用旧几何的18741.7或一级5环的17595.3替代当前基线。

修改正式脚本前必须先读项目主文档。`oatof_paths.m`从本文件夹位置推导工作区，不得在
MATLAB 正式入口中重新加入用户目录硬编码。

## 目录职责

```text
dual_stage_ringstack/
├─ analysis/          # 与求解器无关的轻量计算/解析工具
├─ cad/               # COMSOL→STEP→SolidWorks 可复现导出代码
├─ comsol/            # 正式 COMSOL/MATLAB 生产脚本
├─ config/            # 跨求解器共享的轻量参数和表格
├─ docs/              # 项目状态、理论资料与决策记录
├─ simion/            # 可复现的 GEM/Lua/FLY2 文本源与 SIMION 文档
└─ tests/             # 长期测试基线；一次性代码只放 tests/scratch
```

大型产物位于工作区镜像目录：
`artifacts/components/mass_analyzers/oa_tof/dual_stage_ringstack/`。

- `models/comsol/formal/`：当前唯一权威 COMSOL 模型。
- `models/comsol/archive/`：被替代但保留溯源的 MPH。
- `models/simion/workspace/`：可由 SIMION GUI 直接打开的完整运行时工作区。
- `cad/formal/`、`cad/archive/`：正式与历史 CAD 交付。
- `results/`、`runs/`：结果与可追踪运行记录。
- `scratch/{comsol,simion,cad,comparisons,cache}`：可重建临时产物。

SIMION Lua 构建脚本使用相对于`04_workbench/`（或其`formal/`子目录）的文件名，避免绑定
用户名和盘符。运行脚本时应从其所在目录启动；迁移后仍需扫描 IOB/PA 元数据中的缓存文件名，
不能只验证 Lua 文本。
