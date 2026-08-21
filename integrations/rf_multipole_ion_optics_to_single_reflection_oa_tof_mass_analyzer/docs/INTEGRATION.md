# RF 多极杆—单反射 oaTOF 集成

本目录定义从 RF 多极杆交接状态到单反射 oaTOF 单飞运行的活动集成边界。它是当前架构入口，不记录
历史性能叙事、已退役 campaign 或逐次调试结论；这些材料位于 [`HISTORY.md`](HISTORY.md)。

## 所有权与入口

- 多极杆项目拥有杆内几何、RF 驱动、源粒子与 `handoff` 状态；oaTOF 项目拥有下游几何、脉冲和分析。
- 本集成只拥有跨组件状态绑定、活动 campaign 的生命周期、单飞适配与运行证据链。
- [`workflows/family_source_closure/prepare.py`](../workflows/family_source_closure/prepare.py) 只准备并验证已授权输入；
  [`execute.ps1`](../workflows/family_source_closure/execute.ps1) 只执行生命周期注册表明确允许的 campaign。
  未注册、退役或历史 campaign 必须失败关闭。
- [`runtime/run_single_flight.ps1`](../runtime/run_single_flight.ps1) 是单飞 SIMION 的唯一运行入口；项目或分析脚本
  不得复制其 PA cache、FLY2、粒子重编号或资源预算实现。

## 运行边界

商业求解器默认按 campaign 串行调度。粒子相互独立、无碰撞、无空间电荷且 campaign 显式授权时，单个
SIMION 运行可调用共享批处理；批内结果必须恢复全局粒子 ID 并合并为一个来源 run。不得在外层 campaign
并发之上再启动嵌套并发。

仓库级 [`common/simion/resource_scheduler.py`](../../../common/simion/resource_scheduler.py) 仅为已授权请求
规划 RF/静电批次：它综合粒子数、每批 CPU、可用内存、预留内存、已观测的同资源身份峰值及并发上限。
没有匹配历史时，首次运行只能采用单批 bootstrap；观测到峰值后才可为同一资源身份提高并发。

每个 run 必须冻结 `run_config.json`、`summary.json` 和 `run_manifest.json`。缓存只用于完全相同的冻结身份，
且不可替代来源 run。功能成功不自动证明数值收敛、跨求解器等价、参数最优或 Formal 资格。

## 配置、验证与历史

活动配置位于 [`config/`](../config/)；公共 schema 和文件身份工具位于
[`common/contracts/`](../../../common/contracts/README.md)。修改活动运行器、合同、资源策略或 campaign 后，应运行
项目门禁及仓库级集成门禁。历史文档中的数字、状态和链接均不构成活动授权。

实验 campaign 可继续使用完整行，也可用扁平 authoring：`experiments.shared` 声明共同控制，
`variation_axes` 列出允许变化的字段，`rows` 只列行身份和 `overrides`。准备阶段先展开为完整冻结行，
再执行既有 schema 与授权校验；任何未声明的字段变化都失败关闭。这样同一合同可顺序执行多个 gap 或
其他已授权参数点，而不会复制共享输入。
