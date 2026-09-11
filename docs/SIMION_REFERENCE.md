# SIMION 跨项目参考

本文件只保存已经能跨项目复用的 SIMION 操作经验。具体项目的 PA 尺寸、粒子参数、运行结果和
IOB 路径写入该项目 `docs/SIMION.md` 或 `docs/PROJECT.md`。

## PA、GEM 与 IOB

- GEM 是可审阅几何源；PA/PA# 是数值场资产；IOB 保存实例、变换和 Program 关联。三者职责不同。
- 二维圆柱对称 PA 可在 IOB 中旋转为三维轴对称场，适合真正轴对称的器件；真实非轴对称结构仍需
  三维 PA，不能为了省内存强行二维化。
- 各向异性网格可以在敏感方向加密而控制 PA 大小，但必须同时检查电极最小厚度、间隙和边缘场
  是否被足够网格点解析。
- IOB 可能保存相对或绝对 PA 路径。迁移前先检查，迁移后必须在 GUI 中确认所有实例并实际飞行；
  仅看到 IOB 文件存在不能证明可复现。

### 重叠电场 PA 的实例优先级

- 同一点若落入多个电场 PA 实例，粒子只使用**优先级最高**的那个实例；电场不会自动叠加。
  SIMION View PAs页显示的priority number越大，优先级越高，可用`L-` / `L+`调整。
- 不得把GUI priority number、PAs列表槽位、Lua的`wb.instances[n]`和Data Recording的
  `PA instance`混为同一编号。构建契约应分别记录Workbench槽位和GUI优先级，并用一个重叠点
  实际飞行确认哪个PA生效；仅凭数组下标推断优先级不可靠。
- 该遮蔽不只影响场值：低优先级实例的电极碰撞/终止面也可能不可见。因此局部功能器件、检测器
  或 stopper 必须高于与其重叠的包络、屏蔽罩或粗网格背景 PA。
- 默认把全局包络/屏蔽设为最低优先级，局部功能器件必须高于与其实际重叠的背景PA；检测器/
  stopper也必须高于覆盖其终止面的背景PA，但没有重叠依据时不要求它成为全局最高优先级。无场管
  或屏蔽罩应作为回退场，不得覆盖加速器、反射器等功能区。
- `segment.instance_adjust()`可在运行时抑制当前高优先级实例并回落到下一个实例，但只适合明确的
  空间分区例外，不能用来掩盖静态 IOB 排序错误，否则 GUI 场查看、Program Off 和其他调用路径
  会得到不同物理。
- 正式门禁必须同时检查实例文件名、Workbench槽位和GUI优先级，并在每个重叠区验证实际选中的
  PA；只检查实例数量不足。

依据：[SIMION Particle Trajectory Calculations](https://simion.com/info/particle_trajectory_calculation.html)、
[Multiple PAs](https://simion.com/info/multiple_pas.html)、
[Trajectory Programming Techniques](https://simion.com/info/trajectory_programming.html)。

### 长PA输入路径

**已关闭范围：SIMION 只读 standalone PA 的长路径输入。** 初版实现与回归提交于 `fe09cc9c`，
Agent 强制路由提交于 `d6a51112`；本节是该能力适用边界和关闭结论的唯一规范位置。

| 消费方式 | 必须使用的输入表示 | 完整性检查 |
|---|---|---|
| 真正 standalone 的只读 PA（不含从 family 抽出的响应成员） | 公共入口生成可写、可丢弃的短名普通 `.pa` 副本 | 复制前后源及目标大小／SHA-256一致；进程退出后核对源 |
| 新 family 的构建、Refine 与响应生成 | 仅在一次性、可写的 build staging 中创建原生 family；发布前把每个响应复制到全新 PA 对象并保存为 standalone `.pa` | 新对象逐节点保留势、电极标志及网格元数据；独立进程重开和延迟哈希稳定 |
| 已发布 cache 的 `.paN` 成员 | **禁止供应商进程再次打开**；运行时只消费同 generation 内已发布的 standalone 响应 | manifest 同时覆盖原生 family 和 standalone 响应；运行后完整 cache probe |

统一复用 [short_pa_path_support.ps1](../common/simion/short_pa_path_support.ps1)。禁止用
junction、symlink 或 hard link 把不可变缓存暴露给 SIMION，禁止项目私有短路径实现。文件只读属性
不能代替写隔离；所有路径都不能只核对 `.pa#` 哨兵。短名副本在供应商退出后清理，不改变规范 artifact
目录、科学输入身份或 manifest 路径。完整 family 的内容缺失或损坏不能误判为 `MAX_PATH` 问题。
把 `.paN` 单个复制、改名，甚至把已发布 family 完整复制到私有目录，都不能证明其 family 关联已解除：
`r59` 与 `r66` 分别捕获了单成员路径和完整复制路径之后的延迟源哈希漂移。因此公共短副本入口拒绝
`.paN`，生产运行器只接受在 family 初次构建时由**全新 PA 对象**生成并受同一 cache manifest 约束的
standalone 响应。完整 family 物化仅是通用字节复制原语，不再是已发布 SIMION family 的运行时隔离边界。

已验证能力包括完整分析器 PA、局域 PA0、IOB 装配及真实飞行；独立响应导出的最终真实飞行复验为
`20260916_193000__sim__simion__mrtof-r55-standalone-flight-r76`，其上游 build/cache 证据由
[MR-TOF 项目状态](../projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md)绑定。自然检测命中属于对应项目 run 的功能证据，不由本公共能力授予统计、数值收敛、
Candidate 或 Formal 资格。本结论不扩展为所有求解器的通用短路径发布层。

[公共实现说明](../common/simion/README.md#长路径输入-api与证据)维护 API、回归命令、官方依据及完整
失败／复验链。后续直接复用并按改动范围验证，不重新建立替代机制。

## GUI 对等

正式基线应让用户在 GUI 中检查 PA 实例、位置、旋转、缩放、Fast Adjust 电压、Fly2 粒子和
Program。Lua 可以参数化和联动实例，但关键几何/终止条件不能只有不可见虚拟逻辑。数值检测面
不是机械检测器时，应明确标注其角色、有效面与口径。

## Program 与 Data Recording

Program 可以实现实例联动、粒子追踪控制和审计信息。关闭 Program 编辑窗口不等于禁用 Program；
若真正禁用程序，依赖它的终止、记录或联动逻辑会消失。Data Recording 复核应至少记录 Ion
Number、TOF、坐标和 Event/实例信息，避免把其他 splat 或重复事件混入谱图。

## 可复现交付

打包时至少包含 IOB、同名 Lua/Fly2、所有被引用的 PA 文件及必要 PA0/PA#、可审阅 GEM、固定粒子
表或生成脚本、参数契约、运行说明和预期校验值。优先使用相对路径，并在另一目录或另一台机器
进行一次解包复现测试。
