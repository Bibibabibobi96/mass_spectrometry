# SolidWorks公共实现与验证

本目录只保存跨项目的 STEP 导入、原生零件/装配生成和引用验证入口；项目几何、参数与资产资格仍写入
对应项目文档。工具链版本与正式执行入口统一见[操作指南](../../docs/OPERATIONS.md)。

## 按任务查阅

| 任务 | 入口与职责 |
|---|---|
| 解析受支持的安装 | [PowerShell 解析器](resolve_solidworks_2022.ps1)、[Python 解析器](installation.py) |
| 从 MATLAB 导入 STEP 并保存零件／装配 | [MATLAB 桥接](import_step_to_solidworks.m)，通过临时 JSON manifest 调用同目录 Python 模块 |
| 从 Python 导入 STEP，或复用保存、变换操作 | [Python 桥接](import_step_to_solidworks.py)：`import_steps`、`save_native_document`、`create_transform`、`document_title` |
| 仅查看已发布 STEP，不保存或转存 | `msplatform.api.open_model(..., application="solidworks")`；[阶段参数](../README.md#科学核心发行与旧入口)，当前验收范围查集成正文 |
| 核对项目几何、交付及资格 | 项目 README → `docs/CAD.md`；当前资产与资格只查 PROJECT 和 manifest |

## 调用边界

MATLAB 的 `import_step_to_solidworks` 接收配对 STEP／SLDPRT 路径、可见性、可选装配路径及每件的毫米平移。
Python 的 `import_steps` 消费同样的显式输入；CLI 的 `--manifest` 适合完整装配，避免命令行长度限制。
桥接不生成器件几何，也不决定项目坐标或目标路径。oa-TOF 使用完整导入桥接，MR 的 CAD 导出器复用
原生保存和变换 helper；调用方仍须按各自几何合同验收。

返回值包含逐件导入／保存错误与警告、零件数，以及可选装配的组件数、平移和世界中心。
这些是实际 API 回执；调用方还须检验引用、坐标、冷重开与项目判据，不能用 `partCount` 或文件存在代替验收。
`save_native_document` 返回保存错误／警告；它不是独立的 Formal 发布入口。

桥接通过 pywin32 COM 调用原生软件，临时设置导入选项和模板，在结束时恢复用户设置；
只关闭自己打开的文档，并只在本次创建应用时退出该应用。执行所需权限和预检沿操作指南，
不在项目复制安装发现或修改用户的永久模板配置。

公开只查看动作独立于上述导入并保存桥。2022 的默认零件与装配模板分别由
`swDefaultTemplatePart=8`、`swDefaultTemplateAssembly=9`管理；`swAlwaysUseDefaultTemplates=111`
使用这两种默认值。装配STEP不能仅设置零件模板后就宣称不再需要装配模板。
新查看请求显式提供`part_template`与`assembly_template`，复制、记录并保护实际模板，临时设置后逐项恢复；
文件存在不证明模板无附加几何或适合全部导入任务，实际冷打开仍需验证。
这些COM调用改变同一用户的系统选项，不是单次导入的隔离设置；修改期间可能落盘，正常清理后须验证恢复。
进程崩溃或同用户并发修改时不能承诺自动恢复或完全隔离，原异常与未恢复事实必须保留。
依据为2026-11-04核查的SolidWorks2022 SP5本机`api/redist/SolidWorks.Interop.swconst.dll`（30.5.0.49）
及`api/sldworksapi.chm`／`swconst.chm`的默认模板主题；在线[默认模板选项](https://help.solidworks.com/2022/english/api/swconst/SO_DefaultTemplates.htm)
可能仅返回新版外壳，不将其当作已读取的2022正文。

本机2022 `ISldWorks::LoadFile4`正文规定：3D Interconnect启用时`ArgString`使用空串；
小写`r`位于未启用3D Interconnect的非DXF／DWG、非Pro/E导入分支，表示导入到新文档，
不是只读标志，也不能据此保证消除全部提示。当前查看profile临时启用691并保留空串，不混用两分支。
同页指出空串可能出现翻译对话框；因此官方接口选择正确不等于已证明无人值守或模板初始化正确。
回执记录实际ArgString、111／691读回、8／9配置与读回、受控模板文件record及mtime、
原PID与导入前PID一致性。模板record证明所读字节身份，不证明模板内部无附加几何；外层owner的
原件／副本保护和原进程句柄仍是生命周期权威，不由mtime或COM PID读回替代。
这次仅补可核查诊断；真实NewDocument／LoadFile对照及无协助冷打开仍需另行原生验收，
不把官方`r`分支或软件替身测试称为已修复本机启动提示。

Toolbox数据库缺失是独立环境问题。官方`swHoleWizardToolBoxFolder=52`是目录设置，不是通用警告抑制开关；
不得自动改指安装目录中的factory数据库、修建用户库或关闭所有警告。启动时早于COM连接的提示也不能由
导入后设置模板来保证消除；保留原始提示及是否需要手动协助，不将一次成功打开表述成无人值守启动已完成。

## 安装发现与验证

PowerShell 入口通过[`resolve_solidworks_2022.ps1`](resolve_solidworks_2022.ps1)、Python 入口通过[`installation.py`](installation.py)解析同一
SolidWorks 2022 安装。默认读取系统注册表；非标准或便携安装可以设置`SOLIDWORKS_2022_ROOT`，其值
必须直接指向包含`SLDWORKS.exe`和2022 PIA程序集的安装目录。调用者不得复制安装盘符或PIA路径。

实际CAD变更仍须先运行根`common/verify_toolchain.ps1`，并完成项目适用的SolidWorks保存与引用门禁；
路径解析成功不代表CAD资产已经通过正式验收。
