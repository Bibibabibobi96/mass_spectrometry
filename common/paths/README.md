# 工作区与组件输出路径

`workspace_paths.m`默认解析源码和同级 artifacts 根；`common_artifact_paths.m`要求调用者提供已经存在的
项目 `runs/<run_id>` 或 `scratch/<task_id>`，并只创建该上下文下的 `comsol/`、`results/`。
已经发布终态 manifest 的上下文不能复用。目录职责以[生命周期](../../docs/LIFECYCLE.md)为准。

## 公共运行根与原生执行表示

MATLAB `resolve_path_identity` 仅供身份与写入授权比较：沿 Java `Path.toRealPath` 解析最近存在祖先的真实链接，
再接回未来文件名；权限错误或无法解析的现有链接不作缺失文件放行。原生 argv/cwd/输出继续保留调用者执行表示，
不能将鉴权结果替换为原生路径。`common_artifact_paths` 的 `artifactRoot` 是持久身份，`modelsDir/resultsDir` 保留执行路径。
本机 R2025b／Java 8 已用真实 Windows junction 验证；API 边界见 [Java 8 Path.toRealPath](https://docs.oracle.com/javase/8/docs/api/java/nio/file/Path.html#toRealPath-java.nio.file.LinkOption...-) 与 [MATLAB JavaException](https://www.mathworks.com/help/matlab/ref/matlab.exception.javaexception-class.html)。

Python `resolve_workspace_paths`与PowerShell `Resolve-WorkspacePaths`在启动时接收显式源码根，
解析源码、可写产物、执行和主机调度器四个规范位置；显式参数优先于环境。
`MASS_SPECTROMETRY_ARTIFACT_ROOT`可一次配置短产物根，执行根默认跟随其`common/execution_aliases`，
也可用既有`MASS_SPECTROMETRY_EXECUTION_ROOT`指定。主机库沿既有
`MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH`保持原身份，不随产物根或源码快照位置新建调度器。
四字段上下文交现有run配置冻结；后续消费完整冻结上下文，不重新解释当前环境默认。
`Remove-RunPackageExecutionAlias`成功移除junction后，将Package恢复为持久run位置并清除旧执行表示；
`Get-RunNativeExecutionContext`也处理从冻结记录恢复、但登记alias已不存在的Package，依据本次明确的
持久路径和冻结执行根重新准备。它不迁移载荷、不搜索其他根，也不修改旧manifest。

`project_run_path`／`Project-RunPath`只把显式本run路径投影到执行表示，不resolve执行junction，
外部输入原样保留；身份、锁、容量和长期引用仍用`artifact_run_dir`。
原生物化可显式调用`project_native_run_path`读取公共owner传入的成对进程环境，缺项拒绝；
它不用于身份或持久receipt。`native_run_path.lua`执行同一run内的显式投影，供冻结Lua及生成Program使用；
IP、prepared_joint、local/cooled、单反射与paired实际入口已接线。当前软件行为测试不替代
全部受影响工具的原生保存／移除alias后重开验收。既有SIMION小型探针已使用正式单反射
IOB builder/core完成保存、删除原alias、由公共入口新建不同alias并冷重开，四个原生操作成功；
随后公共收尾从持久进程与释放事实恢复，零新增原生调用并移除新alias。该探针无Refine／Fly，
不替代N=100功能实例或科学资格；其他受影响工具边界仍须各自相称证据。

冻结源码在快照中执行时，`workspace_paths(projectName,ArtifactRoot=...)`可显式接收绝对的全局产物根；
源码路径仍从实际函数位置解析。调用者从受管run配置传递该上下文，不从模型输出路径反推许可根；
提供者入口仍负责run／scratch边界及Formal写保护。
`common_artifact_paths(runDir,ArtifactRoot=...)`将同一显式根传给解析器；未显式指定时，
两者使用`MASS_SPECTROMETRY_ARTIFACT_ROOT`，最后才使用默认根。运行owner须向子进程传递
本次冻结根，不能依赖后来改变的部署环境重新选择位置。

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
paired pulse为前段MATLAB／COMSOL保留其必要early alias；IP、prepared_joint及公共Python prepared owner
也已按实际计划消费公共执行上下文。Python owner投影本run的argv、日志和cwd，冻结import_root仍使用
持久路径，实际模块身份校验不从cwd回退；来源原生输入只沿显式SourceReferences保护与声明路径投影。
相关参数与恢复边界见[公共生命周期owner](../contracts/README.md#python工作流的公共生命周期owner)。
外部深PA／cache仍需原owner的明确短路径／私有副本边界，不得把跨owner路径改到当前run。
深根、普通子进程与LuaIOB测试证明软件接线；移除旧alias后由新执行表示冷重开的实际范围见
[集成状态](../../integrations/docs/INTEGRATION.md)及相应项目状态。冷重开会启动实际原生进程，
零Refine／Fly／Compute不等于零原生调用；只恢复已持久完成事实的收尾则不启动计算。
这些证据不承诺任意历史MPH／IOB的内部路径都可迁移，也不把重开当作科学资格。
