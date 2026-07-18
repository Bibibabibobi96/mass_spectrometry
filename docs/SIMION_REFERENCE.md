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
