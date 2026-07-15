# oa-TOF 项目使用指南（AI 与人类共用）

本目录是独立的 oa-TOF 项目，不是某个“components”分类下的附属部件。当前分析器方案为
正交加速、双级环栈反射镜；离子源、多级杆和电子枪分别属于其他平级项目。

本文件既是入口，也是本项目的知识路由规则。开始任务时先读本文件，再按任务类型选择一份
权威文档；不要默认从COMSOL、SIMION或历史日志开始阅读。

## 固定阅读顺序

1. 所有任务先读[`docs/PROJECT.md`](docs/PROJECT.md)，确认当前参数、正式/候选状态和开放任务。
2. 操作COMSOL时再读[`docs/COMSOL.md`](docs/COMSOL.md)。
3. 操作SIMION时再读[`docs/SIMION.md`](docs/SIMION.md)。
4. 操作STEP/SolidWorks时再读[`docs/CAD.md`](docs/CAD.md)。
5. 只有追溯旧结论时才进入`docs/history/`；历史文件不能覆盖当前项目结论。

历史入口仅由本文件提供：`docs/history/PROJECT_HISTORY.md`和
`docs/history/SIMION_VALIDATION.md`。四份日常文档不再横向链接历史。

## 新知识写到哪里

|新信息的性质|写入位置|
|---|---|
|当前统一几何、粒子源、质量、FWHM定义、正式状态、跨软件结论、下一步|`docs/PROJECT.md`|
|COMSOL节点、网格、求解器、LiveLink、COMSOL独立验证和错误|`docs/COMSOL.md`|
|SIMION PA/GEM、Program、GUI、Fly2、网格、SIMION独立验证和错误|`docs/SIMION.md`|
|STEP、SolidWorks零件/装配体、坐标和保存验证|`docs/CAD.md`|
|已经失效但仍需追溯的长过程|`docs/history/`|
|换一个项目仍成立的API或方法|仓库根`docs/`对应通用文档|
|机器必须读取的统一参数|`config/baseline.json`|

软件文档之间不建立横向引用。COMSOL、SIMION和CAD文档都只返回引用`PROJECT.md`；只有完成
输入对齐和交叉验证的结论，才能从软件文档提升到`PROJECT.md`。同一参数不得在多个文档中
分别维护不同数值。

## 权威入口

- 统一机器契约：[`config/baseline.json`](config/baseline.json)
- SIMION候选实现冻结清单：[`config/simion_stable_entry.json`](config/simion_stable_entry.json)。它只冻结
  IOB/PA/Program/Fly2的实现资产与哈希，不定义或替代统一物理baseline。
- 正式COMSOL生产脚本：
  [`comsol/ms_oaTOF_two_stage_ringstack_reflectron.m`](comsol/ms_oaTOF_two_stage_ringstack_reflectron.m)
- SIMION正式文本入口：
  [`simion/workbench/formal/oatof_ideal_grounded.lua`](simion/workbench/formal/oatof_ideal_grounded.lua)和
  [`simion/workbench/formal/oatof_ideal_grounded.fly2`](simion/workbench/formal/oatof_ideal_grounded.fly2)
- CAD正式入口：[`cad/ms_export_oatof_to_solidworks.m`](cad/ms_export_oatof_to_solidworks.m)
- 跨求解器门禁：
  [`tests/cross_solver/verify_geometry_contract.ps1`](tests/cross_solver/verify_geometry_contract.ps1)
- 路径解析：[`oatof_paths.m`](oatof_paths.m)

## 当前状态速览

- 自2026-07-15起标准质量为524 amu，+1电荷，初始能量`5±0.4 eV`。
- 质量分辨率只按`R=m/FWHM_m`定义；窄峰时间域等价式为`R=T/(2*FWHM_t)`。
- SIMION常规统计使用N=5000；COMSOL快速闭合可使用较小但固定的同源粒子表。
- 紧凑加速器和细z检测器数值终止层是稳定候选，尚未成为正式COMSOL/CAD几何。
- 当前科学优先级是用全三维COMSOL在524 amu下闭合SIMION，不继续无目的压缩SIMION网格。

精确数值、候选/正式边界和开放任务以`docs/PROJECT.md`为准。

## 工具链基线

本项目所有MATLAB/COMSOL脚本只允许通过MATLAB **R2025b**运行；所有STEP、零件和装配操作只允许
使用**SolidWorks 2022**。不为MATLAB R2022或SolidWorks 2013保留兼容入口。现有正式CAD导出报告
已记录SolidWorks revision `30.5.0`（2022）；候选几何转正时仍须在同一版本重新完成装配门禁。

## 目录职责

```text
oa_tof/
├─ README.md          # 本文件：项目入口和知识路由
├─ config/            # 跨软件机器参数契约
├─ docs/              # PROJECT/COMSOL/SIMION/CAD及只读历史
├─ comsol/            # COMSOL/MATLAB正式生产源码
├─ simion/            # GEM、Lua、Fly2及构建/分析源码
├─ cad/               # COMSOL→STEP→SolidWorks可复现源码
├─ analysis/          # 与求解器无关的轻量分析
└─ tests/             # COMSOL、SIMION、CAD和跨求解器长期门禁
```

大型模型和结果位于工作区同级的`artifacts/projects/oa_tof/`，不进入Git。正式模型、候选模型、
运行记录、提升后的结果和临时文件必须分别进入`models/`、`runs/`、`results/`和`scratch/`，
不得重新创建旧的`artifacts/components/...`路径。

## 项目硬规则

- COMSOL与SIMION联动时必须使用同一几何、坐标、有效探测面、粒子表和FWHM定义。
- 正式或候选的几何尺寸必须参数化联动，禁止手工移动一个器件后遗漏相关选择集、屏蔽件或探测面。
- 正式机械几何一旦确认，必须在同一任务更新COMSOL正式MPH和SolidWorks零件/装配体；未完成CAD
  保存与坐标验证前不得称为正式完成。
- SIMION第4实例是GUI可见的数值终止层，只表示有效面和口径，不等于机械检测器厚度。
- Program与Data Recording必须同时开启；关闭Program对话框不等于禁用Program。
- 影响物理或数值结果的设置必须能在目标软件GUI中查看、修改、保存和重算。
- 删除MPH、PA、IOB、CAD或结果前必须取得明确许可；一次性源码只在结论已写入文档后删除。

## 修改后的最低检查

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tests\cross_solver\verify_geometry_contract.ps1 -SkipRuntime
git diff --check
git status --short --branch
```

正式COMSOL、SIMION或SolidWorks入口发生变化时，还必须执行对应软件文档规定的运行时验收。
