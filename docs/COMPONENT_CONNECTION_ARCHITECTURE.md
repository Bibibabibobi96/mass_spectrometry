# 器件端口、连接器与跨项目联合模拟架构

本文定义跨项目器件连接的稳定职责。具体连接参数、当前结果和资格由对应integration维护。

## 决策

连接采用“项目端口 + 公共解析 + integration profile”的结构：

- 上游项目拥有provided port和canonical输出；
- 下游项目拥有required port和输入接受条件；
- `common/integration/`拥有端口、连接、坐标、时钟、粒子状态、谱系和composition plan的schema与解析；
- `integrations/<connection-family>/`拥有具体连接profile、运行编排、联合分析、测试和当前证据；
- 联合run以`integration_id`为主身份，并冻结两端项目、port和profile身份。

公共层不能只根据两个项目ID猜测连接。composition plan最少显式冻结：

```text
UpstreamProjectId
UpstreamPortId
DownstreamProjectId
DownstreamPortId
ConnectionProfileId
```

自动选择只可作为用户界面便利；最终选择、来源、版本和SHA仍须进入计划。

## 目录与所有权

```text
projects/<upstream>/config/interfaces/provided/
projects/<downstream>/config/interfaces/required/
common/contracts/                         # schema
common/integration/                       # solver-neutral解析
integrations/<connection-family>/
  config/                                 # connection/campaign/runtime合同
  runtime/                                # 解析与执行机制
  stages/                                 # 内部阶段
  workflows/                              # 公开入口
  analysis/                               # 联合分析
  tests/
  docs/INTEGRATION.md                     # 当前状态
```

integration不是第三份器件模型。它只保存连接本身、组合规则和联合证据，不复制两端baseline或Formal资产。

## 连接器归属

| 类型 | 归属 |
|---|---|
| 零长度canonical状态交接 | 公共端口与composition合同 |
| 通用无源圆筒、矩形管、接地孔primitive | `common/integration/`或已验证公共几何层；实例值在connection profile |
| 某一连接族专用实体或场重叠区 | 对应integration |
| 具有独立电极、脉冲、透镜或可独立验收功能 | 建立独立项目并发布端口 |

连接profile至少声明mating ports、孔径、壁厚、材料、电位、位姿、场耦合、网格职责和观察面。
解析器必须对坐标/时钟不一致、实体相交、未定义真空、电位冲突、场域重叠或缺失、物理面语义混同和
求解器投影不一致失败关闭。

## 联合模拟模式

profile显式选择一种物理模式：

1. `state_handoff`：上游输出canonical状态，下游重新释放；
2. `field_overlap`：integration拥有连接区联合场；
3. `monolithic_joint_solve`：器件与连接器在同一模型中求解。

执行策略是运行实现，不得与物理模式混淆。例如一个`monolithic_joint_solve`连接可在SIMION采用
同一次Fly连续飞行，并用checkpoint记录中间状态；checkpoint不是state handoff。

## SIMION粗全局PA与局部细PA耦合

当一个连续SIMION装配中只有局部器件需要更细网格，而整体细化会改变其他器件的离散场、超过内存
预算或显著增加构建时间时，可使用“粗全局PA + 局部细PA overlay”。这是一种
`monolithic_joint_solve`的数值实现，不把粒子导出、重新释放或时间清零。

采用该模式必须同时满足以下合同：

1. 粗PA覆盖完整物理装配和全部连续飞行路径；局部PA只重建其负责的实体，坐标、尺寸和电极ID来自同一
   resolved geometry，不维护第二套物理参数。
2. 对粗PA的每个可调电极建立独立单位基函数，把六个局部外表面的粗场电势逐点复制为细PA的Dirichlet
   电极边界；运行时按同一电极电压线性组合。只复制当前合成电势不能支持RF、脉冲或fast-adjust变化。
3. 人工Dirichlet面是SIMION数值电极，不是透明接口。完全位于不可通行实体导体内的面可以贴合该导体；
   存在孔、透明栅网或粒子通道的面必须越过物理结构并保留重叠保护区。局部实例须在粒子到达人工面前
   失活，使粗PA接管；不得让出口人工面与透明栅网重合。
4. Workbench中局部PA置于粗PA之后并具有更高覆盖优先级；`instance_adjust`只在声明的内部有效域启用
   局部实例，在保护区外回退到粗PA。两套PA仍在同一次Fly中使用同一粒子、绝对时钟和电压调度。
5. 首次启用必须先跑同网格身份对照，再改变局部网格。同网格对照至少检查逐阶段census、共同粒子的
   checkpoint状态、探测TOF和落点；只验证六面电势相等不足以证明实例切换没有改变轨迹。
6. PA族按几何、网格、粗PA、电极映射、基函数构建器、Refine机制和SIMION身份建立内容寻址缓存。
   基函数默认串行构建；SIMION并发只有在独立资源测试证明内存、写盘、许可证和稳定性均有余量后才能
   开启。缓存是可删除性能层，run仍冻结输入、验证报告和所用PA身份。

该机制当前只在RF多极杆→oaTOF integration中实现；尚未满足两个平级消费者的公共代码迁移条件。
其他integration采用时应复用本节的合同和门禁，但先在自身边界实现并验证；第二个消费者闭合后再评估
把无器件假设的基函数传递与实例切换机制迁入`common/simion/`。

## 当前RF多极杆→oaTOF实例

四、六、八极杆共享多极杆家族出口端口，一个integration family
`rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer`覆盖三者。当前实现支持：

- `staged_three_stage`分阶段COMSOL/COMSOL/SIMION链；
- `simion_single_flight`连续SIMION单次飞行；
- 模式中性的direct-mating profile；
- 接地圆套筒、带孔法兰和整体屏蔽；
- 由参数合同驱动的单流程布局和受影响PA重建。

准确流程、四PA结构、电极18/19映射、当前诊断和开放任务见
[integration入口](../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/README.md)。

## 扩展门禁

新增连接profile或第二个integration前必须：

1. 两端发布版本化端口；
2. 冻结连接profile和唯一变量；
3. 生成并验证resolved connection与composition plan；
4. 两端求解器从同一resolved连接投影；
5. 以同一源完成静态、功能和相称的数值验证；
6. 形成integration文档、changed-scope路由和artifact身份；
7. 将被取代过程冻结为history，再按授权退出旧活动入口。

仅创建schema、空目录或静态PASS不构成联合物理资格。
