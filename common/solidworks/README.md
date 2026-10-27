# SolidWorks公共实现与验证

本目录只保存跨项目的 STEP 导入、原生零件/装配生成和引用验证入口；项目几何、参数与资产资格仍写入
对应项目文档。工具链版本与正式执行入口统一见[操作指南](../../docs/OPERATIONS.md)。

## 按任务查阅

| 任务 | 入口与职责 |
|---|---|
| 解析受支持的安装 | [PowerShell 解析器](resolve_solidworks_2022.ps1)、[Python 解析器](installation.py) |
| 从 MATLAB 导入 STEP 并保存零件／装配 | [MATLAB 桥接](import_step_to_solidworks.m)，通过临时 JSON manifest 调用同目录 Python 模块 |
| 从 Python 导入 STEP，或复用保存、变换操作 | [Python 桥接](import_step_to_solidworks.py)：`import_steps`、`save_native_document`、`create_transform`、`document_title` |
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

## 安装发现与验证

PowerShell 入口通过[`resolve_solidworks_2022.ps1`](resolve_solidworks_2022.ps1)、Python 入口通过[`installation.py`](installation.py)解析同一
SolidWorks 2022 安装。默认读取系统注册表；非标准或便携安装可以设置`SOLIDWORKS_2022_ROOT`，其值
必须直接指向包含`SLDWORKS.exe`和2022 PIA程序集的安装目录。调用者不得复制安装盘符或PIA路径。

实际CAD变更仍须先运行根`common/verify_toolchain.ps1`，并完成项目适用的SolidWorks保存与引用门禁；
路径解析成功不代表CAD资产已经通过正式验收。
