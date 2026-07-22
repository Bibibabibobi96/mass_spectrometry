# SolidWorks 2022 共享桥接

本目录只保存跨项目的 STEP 导入、原生零件/装配生成和引用验证入口；项目几何、参数与资产资格仍写入
对应项目文档。

PowerShell 入口通过`resolve_solidworks_2022.ps1`、Python入口通过`installation.py`解析同一
SolidWorks 2022 安装。默认读取系统注册表；非标准或便携安装可以设置`SOLIDWORKS_2022_ROOT`，其值
必须直接指向包含`SLDWORKS.exe`和2022 PIA程序集的安装目录。调用者不得复制安装盘符或PIA路径。

实际CAD变更仍须先运行根`common/verify_toolchain.ps1`，并完成项目适用的SolidWorks保存与引用门禁；
路径解析成功不代表CAD资产已经通过正式验收。
