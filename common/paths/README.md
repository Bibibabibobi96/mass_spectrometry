# 工作区与组件输出路径

`workspace_paths.m`解析源码和同级 artifacts 根；`common_artifact_paths.m`要求调用者提供已经存在的
项目 `runs/<run_id>` 或 `scratch/<task_id>`，并只创建该上下文下的 `comsol/`、`results/`。
已经发布终态 manifest 的上下文不能复用。目录职责以[生命周期](../../docs/LIFECYCLE.md)为准。

冻结源码在快照中执行时，`workspace_paths(projectName,ArtifactRoot=...)`可显式接收绝对的全局产物根；
源码路径仍从实际函数位置解析。调用者从受管run配置传递该上下文，不从模型输出路径反推许可根；
提供者入口仍负责run／scratch边界及Formal写保护。


## 公共运行根与原生执行表示

MATLAB `resolve_path_identity` 仅供身份与写入授权比较：沿 Java `Path.toRealPath` 解析最近存在祖先的真实链接，
再接回未来文件名；权限错误或无法解析的现有链接不作缺失文件放行。原生 argv/cwd/输出继续保留调用者执行表示，
不能将鉴权结果替换为原生路径。`common_artifact_paths` 的 `artifactRoot` 是持久身份，`modelsDir/resultsDir` 保留执行路径。
本机 R2025b／Java 8 已用真实 Windows junction 验证；API 边界见 [Java 8 Path.toRealPath](https://docs.oracle.com/javase/8/docs/api/java/nio/file/Path.html#toRealPath-java.nio.file.LinkOption...-) 与 [MATLAB JavaException](https://www.mathworks.com/help/matlab/ref/matlab.exception.javaexception-class.html)。

Python `resolve_workspace_paths`与PowerShell `Resolve-WorkspacePaths`解析源码根、可写产物根、
执行根和主机调度器路径；显式参数优先于环境，四字段上下文冻结在新run配置`paths`中。
`MASS_SPECTROMETRY_ARTIFACT_ROOT`可配置产物根，执行根默认跟随其`common/execution_aliases`；
`MASS_SPECTROMETRY_EXECUTION_ROOT`可显式选择执行根。主机库继续沿已有
`MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH`保持身份，不因产物移动另建调度器。
公共生命周期owner将本次冻结根传给prepared子进程；恢复消费原配置，环境变化不重新选根。

`Get-RunNativeExecutionContext -Package ... -Paths ...`按本次明确原生路径自动准备必要的既有短junction，
返回cwd/参数投影和成对进程环境；`Project-RunPath`只投影本run路径，不resolve执行junction，外部输入原样保留。
真实现有cooled原生helper已消费该公共入口；其原场构建和停止边界保持不变。
身份、容量和长期引用仍用`artifact_run_dir`。`Remove-RunPackageExecutionAlias`清理后重置Package执行表示；
已记录但不存在的alias也可由公共上下文按本次计划重建。公共PowerShell owner持久记录必要alias清理事实，
确认writer结束后收尾，原CLI收尾恢复不重启计算。
这不提供外部不可变PA隔离、任意旧模型重开或所有消费者迁移；外部PA沿原公共防写／普通副本入口处理。

MATLAB路径函数接受同一显式ArtifactRoot，未指定时消费`MASS_SPECTROMETRY_ARTIFACT_ROOT`，最后才用默认同级根。
工程/科学输入身份不使用运输路径。本主题软件回归不能冒充求场、Fly或科学资格。

轻量静态回归：从仓库根运行
`python -m unittest common.paths.test_common_artifact_paths_contract`，检查组件调用没有省略上下文；
不限制消费者数量、参数变量名或路径实现的源码写法。

MATLAB 纯路径行为回归位于 `tests/commonArtifactPathsTest.m`，从仓库根执行
`assertSuccess(runtests('common/paths/tests/commonArtifactPathsTest.m'))`；启动方式遵循
[操作指南](../../docs/OPERATIONS.md#工具链与执行入口)。测试复制两份实际路径函数到 `TemporaryFolderFixture` 隔离工作区，覆盖
合法 run/scratch、非法/缺失目录和发布状态；不调用 COMSOL，不写真实项目产物，fixture 自动清理。

## 前端原生计划的实际消费者

公共frontend flight／IOB／显式回放消费同一Package并在实际原生边界取得最新context，
paired pulse、local、cooled与single_reflection调用同步迁移；field/helper与拓扑验证把cwd、argv和
显式PA/report环境定位一并投影。Program中的standalone查找使用同一冻结Lua运输实现，
IOB wrapper只投影声明路径，原物理core保留；路径文本不独立定义科学复用身份。
local与cooled、single_reflection不再强制每run建alias；后两者必要已声明路径仍可提前触发条件准备。
paired pulse目前为前段MATLAB／COMSOL保留原early alias，IP／prepared_joint和公共Python／COMSOL运输另有迁移边界，
本条不声明它们已经完成。外部深PA／cache仍需原owner的明确短路径／私有副本边界，
不得把跨owner路径改到当前run。相关深根／实际普通子进程与LuaIOB测试是软件接线；原生冷开另看已取得的小SIMION证据。

纯准备的冻结Python cwd本身若超过Windows进程目录边界，仍需后续Python owner运输；本主题不以SIMION argv投影声称关闭此限制。
