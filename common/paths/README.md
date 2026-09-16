# 工作区与组件输出路径

`workspace_paths.m`解析源码和同级 artifacts 根；`common_artifact_paths.m`要求调用者提供已经存在的
项目 `runs/<run_id>` 或 `scratch/<task_id>`，并只创建该上下文下的 `comsol/`、`results/`。
已经发布终态 manifest 的上下文不能复用。目录职责以[生命周期](../../docs/LIFECYCLE.md)为准。

轻量静态回归：从仓库根运行
`python -m unittest common.paths.test_common_artifact_paths_contract`，检查组件调用没有省略上下文；
不限制消费者数量、参数变量名或路径实现的源码写法。

MATLAB 纯路径行为回归位于 `tests/commonArtifactPathsTest.m`，从仓库根执行
`assertSuccess(runtests('common/paths/tests/commonArtifactPathsTest.m'))`；启动方式遵循
[操作指南](../../docs/OPERATIONS.md#工具链与执行入口)。测试复制两份实际路径函数到 `TemporaryFolderFixture` 隔离工作区，覆盖
合法 run/scratch、非法/缺失目录和发布状态；不调用 COMSOL，不写真实项目产物，fixture 自动清理。
