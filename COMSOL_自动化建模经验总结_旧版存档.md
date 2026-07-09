# COMSOL 6.4 自动化建模经验总结（MATLAB LiveLink + Java API）

> 本文档基于一整套质谱仪部件的三维建模（几何→静电场/磁场→带电粒子追踪→碰撞/多体效应）
> 实战过程整理，用于喂给 AI 作为后续 COMSOL 自动化仿真任务的先验知识，减少重复踩坑。

---

## 📖 快速导航：先看这里，再决定读哪一节

**本文档分两层**：§1-§6、§8 是"发现过程"的叙事记录（为什么、怎么排查出来的）；
**§7 是"怎么写"的速查表（按调用/属性组织），是日常写新脚本时应该优先查的那一层**，
叙事节只在"查完§7还是不确定根因"时才需要回头看。**新建任何脚本前，先做下面两步**：

**第一步——确认这个部件是否已经有验证过的实现**，查 **[§7.0 已验证部件库速查表](#70-已验证质谱仪部件库速查表)**：
如果需求和表里已有的部件同类（哪怕参数不同），直接复用/改造对应脚本，不要从零重写。

**第二步——按下面的任务类型定位该查§7的哪个分类**（各分类内部条目本身不需要重新编号，见 [§7内容分类索引](#7内容分类索引)）：

| 你要做什么 | 先查 |
|---|---|
| 连接/管理 COMSOL 服务端、模型标签 | §7.1, §7.13, §3.2, §3.4 |
| 建几何（图元、布尔运算、倒角、选择集） | §7.2, §7.3, §1.2, §1.4 |
| 静电场（材料/电位边界/网格/稳态求解） | §7.4, §7.5, §7.6, §1.5 |
| 磁场（`InductionCurrents`/`Coil`线圈） | §7.14（详细过程见 §8） |
| 带电粒子追踪 CPT 基础（发射/受力/时间相关study） | §7.7, §7.8, §2.1-2.4 |
| 从粒子数据里取坐标/速度/末态能量/碰撞计数 | §7.10（**先看这条，`mpheval`/`mphinterp`/`mphparticle` 该用哪个全是坑**），§2.5-2.7 |
| 结果绘图（切面图、粒子轨迹图、图片导出） | §7.9, §3.1（**批处理导出粒子轨迹图有已知稳定性风险**） |
| CPT 里的磁场力/点释放/壁面条件/粒子间相互作用(库仑排斥) | §7.15, §7.24, §8.5 |
| 背景气体碰撞（碰撞池/CID，弹性碰撞/电荷交换） | §7.22, §7.25（**`Collisions`必须配Attribute子特征才生效，是本项目最隐蔽的坑**） |
| GPU (cuDSS) 求解器要不要开 | §7.11, §5（结论：本项目规模下**不要开**，比CPU慢） |
| 具体某个质谱仪部件（透镜/阱/TOF/ESA/磁扇形场/多极杆/Wien滤波器/ICR池） | §7.0 表格里对应行 → 对应 §7.16-7.26 详细条目 |
| 不确定某个调用有没有试过、会不会报错 | §7.12 黑名单（**已确认无效的调用，别再重试**） |
| 写新脚本前的通用调试方法论 | §4 |

---

## 0. 技术路线选择：优先绕过 MCP 工具，直接走 Java API

如果项目要求"优先使用 MCP COMSOL 工具"，**先做一次最小连通性测试**（建模型+建组件+建最简几何），
不要假设 MCP 工具箱是可靠的。本次实测发现 MCP 的 `model_create_component` 工具存在代码级 bug
（内部按 3 参数重载调用 `ModelNodeListClient.create()`，但 COMSOL Java API 该方法只有 1/2 参数重载），
换 COMSOL 版本（6.3→6.4）、换启动参数都无法修复，是工具本身的实现问题。

**可靠的备选方案**：MATLAB LiveLink for COMSOL，直接调用底层 Java API：

```matlab
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
mphstart(2036);           % 连接到已启动的 COMSOL 服务端
import com.comsol.model.*
import com.comsol.model.util.*
model = ModelUtil.create('Model');
```

- 服务端需要先单独、持久化地启动（不要每次都重新拉起，代价是几十秒）：
  ```powershell
  & "D:\COMSOL 6.4\COMSOL64\Multiphysics\bin\win64\comsolmphserver.exe" -port 2036 -multi on -silent
  ```
  用后台进程方式启动一次，整个建模会话（多阶段脚本）共用同一个服务端，只在真正需要时重启。
- 每个"阶段"脚本用 `matlab.exe -batch "cd(...); 脚本函数名"` 非交互调用，脚本内部自己 `mphstart` 连接。
- 这条路径不依赖 MATLAB 图形界面/许可证之外的东西，比"COMSOL Java 源码 + comsolcompile + comsolbatch"
  更适合迭代调试（可以快速改一行代码重跑，不需要每次重新编译）。

---

## 1. Java API 建模层的具体坑

### 1.1 组件与几何创建（正确写法）
```matlab
comp1 = model.component.create('comp1', true);      % 注意：2参数 (tag, boolean)，没有维度参数
geom1 = comp1.geom.create('geom1', 3);               % 维度在这里指定
geom1.lengthUnit('mm');                               % 建议设置，但要记住这会影响后续插值坐标单位（见 3.1）
```

### 1.2 Fillet / Chamfer 可能受许可证限制
`geom1.feature.create('fil1','Fillet')` / `'Chamfer'` 报错
`"The requested geometry operation is unknown or cannot be created in this context"`
——即使在最简单的单个圆柱体上也失败，说明是许可证/模块限制（很可能需要 Design Module），
不是参数写法问题。**排查方法**：先在一个空白模型里对最简单的图元单独测试 Fillet/Chamfer，
如果连这个都失败，就不要在正式模型里纠结参数了，直接切换方案。

**替代方案：用 Cone（圆锥台）− Cylinder 布尔差手工构造 45° 倒角**，不依赖 Fillet/Chamfer 功能：
- 外圈顶部边缘：`Cylinder(r=R, h=d, pos=z_top-d)` 减去 `Cone(r=R, rtop=R-d, h=d, pos=z_top-d)`
- 外圈底部边缘：`Cylinder(r=R, h=d, pos=z_bot)` 减去 `Cone(r=R-d, rtop=R, h=d, pos=z_bot)`
- 内孔（aperture）顶部边缘：`Cone(r=r_hole, rtop=r_hole+d, h=d, pos=z_top-d)` 减去 `Cylinder(r=r_hole, h=d, pos=z_top-d)`
- 内孔底部边缘：`Cone(r=r_hole+d, rtop=r_hole, h=d, pos=z_bot)` 减去 `Cylinder(r=r_hole, h=d, pos=z_bot)`
- 最后用一次 `Difference` 把所有倒角工具体从母体里减掉。

**Cone 图元的正确属性名**（容易搞错）：
```matlab
geom1.feature(coneTag).set('r', baseRadius);          % 底面半径
geom1.feature(coneTag).set('specifytop', 'radius');   % 注意：字符串 'radius'，不是 boolean true/false！
geom1.feature(coneTag).set('rtop', topRadius);         % 顶面绝对半径，不是 'r2'，也不是 'ratio'
geom1.feature(coneTag).set('h', height);
```

### 1.3 几何信息查询
`geom1.getNEdge(tag)` 这类方法在这套 API 封装里不存在。用 MATLAB 工具函数：
```matlab
gi = mphgeominfo(model, 'geom1');   % 字段是大写开头：Ndomains, Nboundaries, Nedges, Nvertices
```

### 1.4 命名选择集（Selection）的建立方式
- 给几何图元开启自动域选择：`geom1.feature(tag).set('selresult','on')`，之后可以用固定命名规则
  `geom1_<featureTag>_dom` 引用该图元对应的域选择，不用去猜域编号。
- 要拿"某个域的边界面"（比如某个电极的表面），建组件级 `Adjacent` 选择：
  ```matlab
  comp1.selection.create('selb_x', 'Adjacent');
  comp1.selection('selb_x').set('input', {'geom1_xxx_dom'});
  ```
- 在材料/物理场里引用命名选择：`feature.selection.named('selection_tag')`。

### 1.5 材料、静电场物理场、网格、稳态求解 —— 标准套路
```matlab
mat = model.material.create('mat1','Common');
mat.selection.named(sel_tag);
mat.propertyGroup('def').set('relpermittivity', {'1'});

es = comp1.physics.create('es','Electrostatics','geom1');
es.selection.named(sel_vac_tag);
pot = es.create('pot1','ElectricPotential', 2);   % 2 = 边界(面)级别
pot.selection.named(selb_tag);
pot.set('V0','V_value_or_param');

mesh1 = comp1.mesh.create('mesh1');
mesh1.feature('size').set('hauto', 3);  % 1=最细...9=最粗，Finer≈3
mesh1.run;

std1 = model.study.create('std1');
std1.create('stat1','Stationary');
model.sol.create('sol1');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').runAll;
```

### 1.6 结果绘图常见属性名坑
- `Slice` 图层的切面方向属性是 `quickplane`，合法取值是 `"xy"|"yz"|"zx"`（**不是** `"xz"`，顺序反了会报错）。
- 默认一个方向会自动铺开好几个切面（默认 `quickznumber=5` 类似的属性），只要单张切面需要显式设：
  ```matlab
  sl1.set('quickznumber','1'); sl1.set('quickxnumber','1'); sl1.set('quickynumber','1');
  ```
- 图片导出：`model.result.export.create(tag,'Image')`，设置 `plotgroup`、`pngfilename`、`width`、`height`，然后 `.run`。

---

## 2. 带电粒子追踪（CPT）专项坑

### 2.1 物理场与默认特征
```matlab
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
```
自动带有：
- `wall1`（Wall，默认 `WallCondition=Freeze` 且 `Otherwise=Freeze`，即默认对所有边界"冻结/吸收"粒子，
  同时天然充当"末端探测面"，不用额外配置）
- `pp1`（ParticleProperties，**默认已经是电子**：`mp=me_const`, `Z=-1`，不用改）
- `dpcon1`（PairContinuity，装配体配对用，普通模型忽略即可）

### 2.2 从边界发射粒子：特征类型叫 `Inlet`，不是 `Release`/`ReleaseFromBoundary`
```matlab
inl1 = cpt.create('inl1', 'Inlet', 2);   % 2 = 边界级别
inl1.selection.named(sel_emit_surface);
% 默认 v0=0，方向默认沿边界法向 —— 刚好对应"初始能量≈0eV、垂直表面发射"的常见需求，不用改
```

### 2.3 电场耦合到粒子受力：`ElectricForce` 是 cpt 物理场下的**特征**，不是顶层 multiphysics 节点
```matlab
% 错误：model.multiphysics.create('epf1','ElectricForce', ...)  -> "Unknown multiphysics coupling"
% 正确：
ef1 = cpt.create('ef1', 'ElectricForce', 3);   % 3 = 域级别
ef1.selection.named(sel_vac_tag);
ef1.set('E_src', 'root.comp1.es.Ex');          % 必须是这个完整限定字符串，不能只写 'es'
```
**技巧**：不确定合法值时，先随便 set 一个错误值（比如 `'es'`），COMSOL 报错信息里通常会
直接列出所有合法取值（这次就是靠报错里的 `"root.comp1.es.Ex", "userdef", "fromCommonDef"` 才定位到写法）。

### 2.4 时间相关粒子追踪 Study：复用已求解的静电场
```matlab
std2 = model.study.create('std2');
tstep = std2.create('time1', 'Transient');            % 时间相关步的特征类型叫 Transient
tstep.set('tlist', 'range(0,0.1[ns],40[ns])');
tstep.setEntry('activate','es', false);               % 关掉 es，不重新求解
tstep.setEntry('activate','cpt', true);                % 只求解 cpt

% !!! 高优先级坑：仅仅 setEntry('activate','es',false) 并不会让 cpt 自动
% 复用已求解的 es 场！createAutoSequence 生成的 Variables 节点(v1)默认
% notsolmethod='init'，即"未求解变量的取值"落回初始值（对 es 场约等于
% 全 0），而不是 Study 1 的已存解。实测后果：ElectricForce 算出的力处处
% 为 0，电子以 v0=0 释放后，整个 tlist 时间范围内位置/速度完全不变
% ——即"粒子看起来完全不运动"，且不报任何错误，非常隐蔽（比 §3.1 的
% 图形问题更容易被误判成"画图程序的问题"，实际是求解配置问题）。
% 必须显式把"未求解变量取值"指向 Study 1 的解：
model.sol.create('sol2'); model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');  % 'sol'=用存储解，不是默认的'init'
model.sol('sol2').feature('v1').set('notsol', 'sol1');       % 属性名是 notsol，不是 notsolnum！
% ('notsolnum' 是另一个属性，只接受 "auto"/"all"/"first"/"last"/
%  "from_list"/"interp"/"manual" 或整数，塞解的 tag 字符串会直接报
%  "'Selection' can be: ... - Property: notsolnum"；'notsol' 才是那个
%  接受解 tag（如 'sol1'）的属性，容易搞混。)
model.sol('sol2').runAll;
```
**排查方法（比看轨迹图/末态统计更快定位问题）**：怀疑粒子没有真正受力/运动时，
直接对比同一坐标下 `es.normE`（或其他 es 场变量）在 `dset2`（CPT study 的解）
和 `dset1`（纯静电场解）里的取值：
```matlab
mphinterp(model, 'es.normE', 'coord', coords, 'dataset', 'dset2')  % 应与 dset1 同量级
```
如果 `dset2` 上处处为 0 而 `dset1` 不为 0，就是这个"未求解变量"配置的问题，
不用去怀疑几何/边界条件/网格。

时间步长/总时长的估算：非相对论电子末速度 `v=sqrt(2*E_eV*1.602e-19/9.11e-31)`，
再除以渡越距离得到量级，留 30-50% 余量。

### 2.5 求粒子末态动能：不要迷信 `cpt.Ep`，可能根本不存在
本次实测 `cpt.Ep`/`cpt.Ek`/`cpt.KE`/`cpt.kin_en`/`cpt.Ekin`/`cpt.speed`/`cpt.U`、
以及 `comp1.qx`/`cpt.qx`/`cpt.vx` 等"看起来应该对"的变量名在 `mpheval` 里全部报 "Undefined variable"。

**稳健替代方案：用能量守恒代替去猜变量名**——如果粒子从阴极（V=0）附近以≈0eV初速释放，
那么它在任意后续位置的动能[eV] = 该位置的静电势 V（来自阶段2已求解的 ES 数据集）：
```matlab
pd = mphparticle(model, 'dataset', 'pdset1');   % 见下方 2.5b，这是唯一可靠的取值方式
qx = pd.p(end,:,1).'; qy = pd.p(end,:,2).'; qz = pd.p(end,:,3).';   % 末态坐标
coords = [qx'; qy'; qz'];
KE_eV = mphinterp(model, 'V', 'coord', coords, 'dataset','dset1');   % dset1 = 静电场解
```
这个方法完全绕开了"到底哪个变量名是动能"的问题，只要模型是纯静电场加速（无磁场/无碰撞损耗）就总是对的。

### 2.5b 【重要坑，曾直接导致误判"电子不运动"】取粒子坐标绝对不要用
`mpheval(...,'dataset','dset2','edim',0)`，要用专用的 `mphparticle`
本次debug最容易踩、后果最严重的坑：`mpheval(model, {'x','y','z'}, 'dataset','dset2', 't', t, 'edim',0)`
（`dset2` = CPT study 的原始 Solution 数据集，不是 §2.7 的 `Particle` 类型数据集）**不会报错，
但取到的根本不是粒子位置**——它安静地退化成了对底层 FEM 网格的 0 维几何顶点求值，
坐标范围正好等于整个真空域圆柱体的上下边界（如 z∈[z_dom_bot, z_dom_top]），
且**不随 `t` 变化**（因为网格顶点当然不会动）。这次debug里，这个坑一度让人误以为
"粒子完全没有运动"（因为拿到的伪坐标随时间常量），而真正原因（见 §2.4 的
notsolmethod/notsol 坑）反而是在怀疑这个数据提取方式本身之后才定位到的——
两个坑叠加在一起，排查时容易互相掩盖，要分别验证。

**正确写法**：用专门的 `mphparticle` 函数，而不是 `mpheval`/`Particle` 数据集本身：
```matlab
pd = mphparticle(model, 'dataset', 'pdset1');   % pdset1 = Particle 类型数据集(见2.7)
% pd.p, pd.v 都是 [nTimes x nParticles x 3] 的 double 数组（不是 cell！）
% pd.t 是 1 x nTimes 的时间向量，与 study 的 tlist 一致
z_all_particles_at_tk = pd.p(k, :, 3);        % 第 k 个时间步，所有粒子的 z
z_of_particle_j_over_time = pd.p(:, j, 3);    % 第 j 个粒子，随时间变化的 z
```
另外，`mpheval(...,'dataset','pdset1','edim',0)`（用对了数据集，但还留着 `edim` 参数）
在本次实测中直接**卡死**（等待 8 分钟无响应，强制杀掉客户端后连服务端本身都被拖坏，
参见 §3.2 的恢复流程）——`Particle` 数据集不需要也不接受 `edim` 这个概念，
不要对它用 `mpheval`，只用 `mphparticle`。

**排查建议**：如果"粒子看起来不动"，先用 §2.4 的方法确认 `es` 场在 `dset2` 里是否真的非零，
再用这里的 `mphparticle` 确认取到的坐标本身是否可信——不要想当然认为数值提取脚本没问题，
两处都可能是坑。这也解释了为什么"轨迹图看起来是空的"未必是画图代码的问题
（参见 §3.1 末尾的澄清）：粒子数据本身没有真实运动时，`ParticleTrajectories`
图层渲染出来自然只有一个点/空线，看起来像"画图坏了"，实际是上游数据的问题。

### 2.6 `mpheval`/`mphinterp` 的两个隐蔽单位/维度坑（非常容易悄悄给错结果，且不报错！）

**坑 A：坐标单位跟随模型的 `geom.lengthUnit`，不一定是国际单位制的米。**
如果 `geom1.lengthUnit('mm')`，那么 `mphinterp(...,'coord',coords,...)` 的 `coords` 也必须用 **mm**，
不能想当然换算成米——用米传入不会报错，只会**安静地返回全 0**（因为坐标落在网格范围之外，
插值默认给0，没有任何异常提示）。**每次用 mphinterp/mpheval 前先确认坐标单位和 geom.lengthUnit 一致。**

**坑 B：`'outersolnum','end'` 对"时间相关/粒子追踪"数据集不代表"最后一个时间步"。**
本次实测对 96 个粒子、301 个时间输出点的 CPT 解用 `'outersolnum','end'` 取回了 **28896 个点**
（= 96×301，即所有粒子在所有时间步的数据混在一起），不是想要的"末态"快照，
统计出来的能量分布因此被严重稀释、误导。
**正确做法：显式指定具体时间值** `'t', tend`（单位：秒，需与 study 里 `tlist` 的最后一个值对应），
才能拿到真正的"最终时刻"切片。

### 2.7 粒子轨迹图需要专门的 `Particle` 数据集，不能直接指向原始 Solution
```matlab
% 错误：pg.set('data','dset2') -> "Operation cannot be performed on dataset dset2 (Solution)"
% 正确：
pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.set('solution', 'sol2');     % 属性名是 solution，不是 data！
pg3 = model.result.create('pg_traj','PlotGroup3D');
pg3.set('data', 'pdset1');
tr1 = pg3.create('traj1', 'ParticleTrajectories');
```

---

## 3. 运维/稳定性坑（这些浪费的时间最多，务必提前规避）

### 3.1 无 GUI 的批处理模式下，粒子轨迹图的图片导出会卡死——用软件渲染可以修好卡死，但轨迹线本身仍可能画不出来
`ParticleTrajectories` 图层的 `imgT.run()`（图片导出）在 `matlab -batch`（无 GUI/OpenGL 上下文）里
最初两次遇到进程挂起（CPU 占用不再增长，但"Responding"状态显示正常，永远不返回），
换 `linetype='tube'` 和 `linetype='line'` 都一样卡死。普通的场分布切面图（Slice/Surface）导出没有这个问题。

**曾经以为找到的"修复"，实测是个更糟的陷阱，不要用**：一开始怀疑是后台会话拿不到正常
OpenGL/GPU 上下文导致卡死，于是重启 `comsolmphserver.exe` 时加上 `-3drend sw -graphics`
（强制软件渲染）：
```powershell
comsolmphserver.exe -port 2036 -multi on -silent -3drend sw -graphics
```
加上这个之后，图片导出确实稳定在 1-5 秒内"完成"（不再卡死），一度以为问题解决了。
**但几分钟后（不是当次调用里，是后续某次操作触发的异步崩溃）整个 `comsolmphserver.exe`
进程会直接崩溃退出**（Windows 事件日志确认：`csgraphics_sw.dll` 里发生访问违例 0xc0000005，
即软件渲染库本身不稳定）。这比"单次操作卡死"更糟——卡死只影响当次调用（杀掉那个客户端进程还能保住
服务端和其他已建好的模型），而这种崩溃会直接拖垮共享的服务端进程本身，殃及所有正在或将要用这个
服务端的其他工作。**结论：`-3drend sw` 不是可靠方案，不要在长期运行的 `comsolmphserver` 上使用**，
默认的 `-3drend ogl`（不加此参数）虽然粒子轨迹图片导出会卡死，但至少稳定、可预测、影响范围可控
（卡死了杀掉那一个客户端进程就行，服务端不受影响）。

**另外，即使排除了卡死/崩溃问题，轨迹线条本身也可能仍然渲染不出来**（这是另一个独立问题，
在软件渲染崩溃之前的短暂窗口期测试到的，没有解决）：即使 `resultinfo` 报告
`Number_of_points`/`Number_of_segments` 都是非零的真实值（说明轨迹几何确实被计算出来了），
逐像素扫描导出的PNG图片仍然可能找不到任何轨迹颜色——只有几何轮廓的黑白线条被正确画出。
尝试过 `dataset.run()`/`plotgroup.run()` 显式求值、调整线型/颜色/粗细都无效。

**结论：批处理脚本里做粒子轨迹图片导出，目前找不到稳定可靠的路径**（默认OpenGL会卡死单次调用，
软件渲染会拖垮整个服务端，即使侥幸不崩溃线条也可能是空的）。确实需要看轨迹图，
最可靠的办法是用 COMSOL 桌面客户端手动打开保存好的 .mph 文件查看（数值结果本身完整可靠，
不受这个渲染限制影响，可以用 mpheval/mphinterp 正常提取)。如果批处理流程里必须做粒子轨迹相关的
图形操作，考虑用一次性、可随时丢弃重启的服务端实例单独跑这一步，不要和其他重要工作共用同一个
长期运行的服务端连接。

**后续一次实测的补充数据点（不确定是否推翻上面的"不可靠"结论，谨慎参考）**：
另一次调试会话里，用同样的 `-3drend sw -graphics` 启动参数，`imgT.run()` 图片导出
在 1-2 秒内正常完成，服务端在导出后继续正常响应（ping 测试、后续多次模型加载/查询都正常），
且导出的 PNG **确实包含可见的红色轨迹线**（不是只有黑白几何轮廓）。**但这次轨迹之所以能看见，
很可能只是因为这次粒子真的在运动**（在此之前，粒子因为 §2.4 的 notsolmethod/notsol 坑完全没有
移动，"轨迹图是空的"当时被误判为渲染问题，实际是数据问题）——不能排除"粒子数据没问题、
轨迹线依然渲染不出来"或"服务端过一会儿崩溃"这两种上面记录过的失败模式，只是这次没有再复现。
**结论调整**：怀疑"轨迹图看起来是空的/没有线"时，第一步应该是按 §2.4/§2.5b 的方法确认
粒子数据本身有没有真实运动，而不是直接归咎于画图/导出代码；如果确认粒子数据没问题、
轨迹线依然导出不出来或服务端不稳定，再参考上面 §3.1 的已知陷阱去排查渲染层面的问题。

### 3.2 强杀一个卡死的 MATLAB 客户端后，共享的 comsolmphserver 服务端本身也可能被拖坏
杀掉卡死进程后，**后续所有新连接（哪怕是最简单的 ping 测试）也会一起卡死**，
说明服务端进程本身进入了不健康状态（大概率是残留的锁/会话没有正常释放）。
**每次强制杀掉一个 COMSOL 批处理客户端之后，不要想当然认为服务端还健康——
先用一个几秒钟就该返回的最小连接测试验证一下，不行就直接重启 comsolmphserver.exe 本身。**

### 3.3 脚本可重复运行性（幂等性）：不要把中间产物存回自己读取的源文件
如果脚本一开始 `ModelUtil.load('Model', A.mph)`，跑完在末尾 `model.save(A.mph)`，
那么下次再跑这个脚本，会往一个已经"被污染"（带有上次新增的材料/物理场/网格节点）的文件里
重新创建同名节点，报 "An object with the given name already exists"。
**约定：每个阶段脚本只从上一阶段产出的、不会被本阶段覆盖的文件里读（比如纯几何的 `xxx.mph`），
本阶段新增的内容另存为一个新文件名（`xxx_ES.mph`、`xxx_CPT.mph`），保证阶段脚本可以反复重跑。**

### 3.4 `ModelUtil` 模型标签在服务端里会跨客户端进程残留
comsolmphserver 是持久进程，不同的 `matlab -batch` 调用只是不同的客户端连接，
之前调用里 `ModelUtil.create('Model')` 创建的模型标签在服务端内存里会一直存在，
直到显式 `ModelUtil.remove(...)`。**每次载入模型前先检查并清理同名标签**：
```matlab
if any(strcmp(cell(ModelUtil.tags()), 'Model'))
    ModelUtil.remove('Model');
end
model = ModelUtil.load('Model', modelPath);
```
调试阶段容易积累一堆用完即弃的临时标签（`ModelTest1`,`ModelTest2`...），建议定期批量清理：
```matlab
tags = cell(ModelUtil.tags());
for i=1:numel(tags), try, ModelUtil.remove(tags{i}); catch, end, end
```

---

## 4. 高效调试技巧

1. **不确定属性/特征名时，故意传一个错误值，让 COMSOL 的报错信息告诉你合法取值**——
   多次靠这个方法直接从异常堆栈里拿到精确的合法字符串（`quickplane` 的 `"xy"/"yz"/"zx"`，
   `E_src` 的 `"root.comp1.es.Ex"` 等），比盲猜或查文档快得多。
2. **不确定某个 Feature Type 名字是否合法时，先在一个空白 scratch 模型里单独试**，
   用 try/catch 循环批量测试几个候选名字，比在正式模型的复杂上下文里反复报错调试快。
3. **`feature.properties()` + 逐个 `getString()` 打印全部属性和当前默认值**——
   往往看一眼默认值就能确认某个设置"已经是想要的"（比如看到 `pp1` 默认 `mp=me_const,Z=-1`
   就知道不用手动配置"电子"这个粒子种类）。
4. 大块新功能先写一个只测试这一个功能点的最小独立脚本（几行代码），确认可行后再拼进主脚本，
   避免在几百行的正式流程里因为一个新 API 调用失败而反复重跑整个前面已经验证过的流程。
5. **对着 Java API 反复试参数猜不出根因时，先查本机 COMSOL 安装自带的 Application Library 文档**
   （路径形如 `D:\COMSOL 6.4\COMSOL64\Multiphysics\doc\help\wtpwebapps\ROOT\doc\com.comsol.help.models.<module>.<example_name>\models.<module>.<example_name>.pdf`，
   可以用 `find`/`Glob` 按关键词搜文件名，比如 `*collision*`/`*ion_drift*` 之类），
   官方示例的 Modeling Instructions 里会把"这个物理场到底该配哪些特征、变量到底叫什么名字"讲得
   一清二楚——本次调试碰撞池`Collisions`特征卡了很久（Nd从1e20试到1e28全部零效果），
   靠读 `ion_drift_velocity_benchmark.pdf` 才发现"`Collisions`必须配`Elastic`等Attribute
   子特征才有非零碰撞截面"这个根本没在任何属性名/枚举值里体现出来的结构性要求，
   靠试参数是试不出来的，**遇到"这个特征所有参数都设对了但就是没反应"这种情况，果断去翻本地文档，
   不要继续盲试**。
6. **"完美条件"排除法：不确定问题出在哪个环节时，把其中一个环节人为设成"完美"、已知不会出问题的
   理想状态，看异常是否消失**——**如果消失了，问题所在就清楚了（就是刚刚改成完美条件的那个环节）**；
   **如果没有消失，说明问题可能在别的环节，也可能是系统性的问题（多个环节共同作用，或者核心逻辑
   本身有误）**——这时候可以把其他环节也逐一设成完美条件，继续排查，直到问题消失或者所有环节都
   排除完为止。**关键是每次只改一个变量**，跑完记录结果再决定下一步，不要同时调好几个参数（否则
   出问题时无法判断该归咎于谁）。本次实测(oa-TOF反射镜后离子发散排查)：怀疑反射镜设计→去掉中间
   栅网(gridless)→发散无变化(问题没消失)→说明问题不在反射镜，或者是系统性的，继续排查下一个环节；
   怀疑推斥极方形不对称→改圆形→依然无变化(问题还没消失)→继续排查下一个环节；**决定性一步**：怀疑
   检测器实体本身扰动场（哪怕没有直接挡住离子）→把检测器挪到束流绝对到达不了的地方(x=350mm)，
   制造"检测器完全不干扰任何东西"的完美条件→**离子轨迹立刻变得干净、可复现**(`z_max≈222.6mm`，
   返回`z≈0`，`x≈14-21mm`，y发散仅~7mm)→**问题消失了，说明问题就出在检测器这个环节**（它的物理
   存在扰动了周围的场，不管是否直接挡住离子路径），不是加速器或反射镜的问题。之后每次改动检测器
   （位置/半径），都直接对照这组"完美条件"基准数值——偏离太多就说明是这次改动本身的问题，不用
   重新怀疑加速器或反射镜。**推广用法**：怀疑碰撞物理场→暂时`Nd`设0(完美真空)看异常是否消失；
   怀疑某电极接地有误→暂时换成`userdef`理想场或直接去掉；怀疑释放体积位置影响统计→改单点释放；
   怀疑求解器设置导致不稳定→换回默认/已验证设置——都是同一个方法论的应用：**一次只把一个环节变
   成完美，异常消失=问题就在这个环节；异常不消失=问题在别处或是系统性的，继续排查下一个环节**。
7. **发现某个部件的电场"泄露"到本该无场/受屏蔽的区域时，加一个接地屏蔽结构**——不限于本项目遇到
   的具体情况，是通用原则。本次实测：反射镜入口栅极(接地，250mm大孔)本该挡住反射镜自身60mm环堆
   叠的强场，但直接测量发现`es.Ez`从z=50mm的-6866 V/m一路增长到z=250mm的-17618 V/m(理论上应该
   全程接近0)——说明一块"开大孔的接地平板"不是有效屏蔽，孔径越大，泄露越严重。**加屏蔽结构时要
   注意尺寸匹配**：曾在入口栅极前加一段30mm长、250mm半径的接地套筒，结果几乎没有改善——套筒长度
   远小于其半径，静电屏蔽的衰减长度和套筒半径同量级，30mm长完全不够、需要几百mm量级才有效，这个
   方向不现实。**真正有效的两个方向**：(a) 从根源上缩小孔径本身(如果孔径是为了容纳某个已经不存在
   的旧问题而设的过大尺寸，比如这里的250mm孔径是为了兼容"早期强发散设计"的离子轨迹，实际束流已经
   收得很紧后孔径应该同步缩小)；(b) 用多级接地/中间电极分担电压梯度，让每一级只需要屏蔽"这一级自
   己的电压差"而不是"电源到地的全部电压差"——参见下一条(#8)对加速器的具体应用。**注意缩小孔径本身
   可能引入新问题**：孔径缩小会增大离子偏移量与孔径的比值，可能重新触发孔径透镜效应导致的横向失稳
   (参见#6附近记录的反射镜偏移/孔径比问题)，缩小孔径后必须重新校准电极中心位置或分stage处理。
8. **设计新部件前，先用理想化的解析场验证轨迹可行，再据此建造实体部件，最后对比两者差异来调整/
   增补部件**——这个思路能把"设计是否可行"和"实体几何有没有引入意外的场畸变"这两件事分开验证，
   不会在排查复杂的多电极系统时把两种错误混在一起。具体做法：①先用`E_src='userdef'`加纯解析表达式
   构造一个理想场(比如完全均匀的加速场、按线性梯度变化的反射场)，不涉及任何真实几何电极，跑CPT验证
   轨迹符合预期（这一步只验证"这个场设计本身能不能达到目标"，排除了电极形状/网格/边界条件的干扰）；
   ②确认理想场可行后，再建造对应的真实电极几何(栅网/环堆叠/屏蔽罩)去逼近这个理想场；③用`mphinterp`
   在关键点直接对比"理想场的解析值"和"COMSOL实际求解出的场值"，哪里差得多，就说明哪里的电极几何
   （孔径大小、屏蔽是否到位、电极间距）需要调整或增补——这比直接建好复杂几何再"看轨迹对不对、猜哪里
   错了"要精确得多，因为可以直接定量对比场本身，而不是等轨迹已经因为多个环节的误差叠加而面目全非。

---

## 5. GPU 求解器（cuDSS）实测结论

COMSOL 6.4 的 Direct 求解器特征（`sol1.feature('s1').feature('dDef')`）暴露了 NVIDIA cuDSS
GPU 直接求解器支持，属性名带 `cudss` 前缀（`cudssreorder`、`cudssmatching`、`cudssprecision` 等）。
启用方法：
```matlab
dDef.set('linsolver','cudss');
s1.feature('fc1').set('linsolver','dDef');   % 默认 fc1.linsolver 通常是 'i1'（CPU迭代法），要显式切过来
```
**实测（几万自由度规模的静电场模型，RTX 2060）：GPU（cuDSS直接法）14.16s，
反而比默认 CPU 迭代法（8.98s）慢 58%。** 小规模问题下 GPU 的上下文初始化/数据搬运开销
超过了并行计算收益，直接法本身开销也比迭代法大。**GPU cuDSS 只在自由度规模远大于本例
（经验上百万级以上）时才可能体现优势，小模型不要默认开 GPU。**

**同样的切换方法在时间相关(Transient)求解器上也适用，结构完全类比**：时间相关 study
的求解器序列（如 `model.sol('sol2').feature('t1')`，类型`Time`）内部同样嵌套着
`dDef`(Direct)/`fc1`(FullyCoupled)/`i1`(Iterative) 子特征，和 Stationary 求解器（`s1`
下同名结构）完全一致，切换方法不变：
```matlab
t1 = model.sol('sol2').feature('t1');
t1.feature('dDef').set('linsolver','cudss');
t1.feature('fc1').set('linsolver','dDef');
```
**实测（碰撞池模型，32粒子×201个时间步的CPT时间相关求解）：CPU（默认迭代法）0.982s，
GPU（cuDSS）1.672s，GPU反而慢70%（比值0.59x）**——和上面静电场稳态求解的结论
（GPU在小规模问题下更慢）完全一致，说明这个"小规模不要用GPU"的结论**不是稳态求解特有
的，时间相关/粒子追踪类求解同样适用**，本质原因相同（GPU初始化开销在小规模问题里占主导）。
**验证了切换求解器后端不影响物理结果**：CPU和GPU两次求解的粒子轨迹逐点比较，最大差异
仅 `3.75e-12mm`（纯浮点噪声），确认这纯粹是性能层面的切换，不会引入任何数值差异。

---

## 6. 工程/物理层面的经验：提前做"能不能走通"的检查

建好静电场之后、正式做粒子追踪之前，**先花一分钟沿电子实际飞行路径（轴线）算一遍电位分布**
（`mphinterp` 在几个关键 z 位置取 V 值），检查有没有电位"先降后升"形成的势垒——
如果控制电极（Wehnelt/栅极）负偏压相对目标能量偏大，会在发射点附近形成电子（尤其是初始能量
接近0的电子）翻不过去的势垒，届时粒子追踪会出现"大部分粒子在发射点附近就被吸收"的结果。
这个检查几乎不花时间，但能在正式跑粒子追踪（通常耗时更长、调试成本更高）之前
提前发现"参数设置在物理上是否自洽"的问题，值得作为标准流程的一步。

### 6.1 螺旋线圈灯丝的"匝间自吸收"是真实物理效应，不是建模错误
把阴极从实心圆柱换成更真实的螺旋线圈钨丝之后，如果相邻匝间距（`axialpitch - 2*rmin`）
和钢丝直径（`2*rmin`）同量级（本次约各 0.1mm），冷发射（v0=0，纯法向）情况下会有
**绝大多数电子（本次实测92%）在极短时间内就被相邻的线匝自身吸收**，只有朝"外侧/远离
线圈"方向发射的那一小部分电子才有机会真正进入加速区。这是螺旋线圈相对实心圆柱阴极
真实存在的效率损失（现实中的灯丝设计也要考虑这个），**换用更真实的热发射初速分布
（各方向都有一定概率，不再局限于纯法向）会显著缓解这个效应**（本次从92%自吸收降到0.03%），
提醒：评估"收集效率"类指标时，冷发射(v0=0)基线可能因为这个效应严重低估螺旋线圈阴极
的真实表现，应该用带热初速的结果作为基准，冷发射结果只适合用来验证"粒子确实在运动"
这类正确性检查，不适合用来评估效率。

### 6.2 螺旋线圈灯丝的安装朝向：线圈轴是否该垂直于枪轴，取决于应用是否关心"对称性"
§6.1 提到的线圈自吸收问题，本质原因是**线圈轴与枪轴同向（螺线管式，套在束轴上）时，
线圈表面绝大部分点的法线指向径向/切向（垂直于枪轴），只有很小分量朝向阳极**。如果把
线圈换成**轴与枪轴垂直**的朝向（像一根弹簧横躺在 Wehnelt 腔体里，COMSOL 里用
`hel1.set('axistype','x')` 实现），每一匝朝上（朝向阳极孔）的一侧表面法线就基本沿枪轴
方向，天然对着有效发射方向。**实测对比**（同样 2700K 热发射、同样 Wehnelt 孔径1.0mm/
偏压-0.5V 基线）：轴向线圈收集效率 27.71%，横置线圈收集效率 **34.18%**——确实有实质提升。
但横置线圈让整个电子枪不再严格轴对称（现实中直热式线圈灯丝多数也是横置在两个支撑柱
之间的），**如果应用只关心"发射利用率"（比如质谱仪电子轰击电离源：电子只需要穿过电离
腔被收集，不需要成像级的对称聚焦光斑），横置是更合理的选择；如果应用需要严格轴对称的
聚焦光斑（比如电镜/CRT 成像），传统做法反而是用"发夹形"弯折钨丝、把弯折尖端卡在轴线上，
牺牲发射面积换取对称性**。选哪种朝向应该先问"这个电子枪的下游需求是效率还是对称性"，
而不是默认套用同轴设计。

### 6.3 Wehnelt 偏压存在"最优点"，不是越负越好也不是不加最好
对 Wehnelt 孔径和偏压做网格扫描时（本次 3×3），观察到收集效率关于偏压**非单调**：
偏压比基线更负（抑制过强）和偏压为0（没有聚焦）时收集效率都比一个适中的负偏压更低，
每种孔径下都是同一个中间值最优。这和电子光学教科书里 Wehnelt 极"负偏压既截止电流、
又同时充当聚焦透镜"的经典结论一致——不是简单的"越负越安全/电流越小"，负偏压太小会
缺乏聚焦、太大会过度截止，中间有一个最大电流点。**做这类参数扫描时不要只测两三个极端值
就下结论，扫描出的非单调关系本身可能就是需要报告的核心结果**。

## 7. API / 函数 / 属性调用速查表（持续更新）

> **维护约定**：这一节是"已验证过的调用方式"的索引，目的是以后遇到同类需求时直接查表使用，
> 不用重新试错。**每次新发现一个可靠用法或一个无效/错误用法，都直接追加到下面对应的小节里**
> （新增一行/一条即可，不用大改结构；确实找不到合适分类再新开一个 7.x 小节，追加到末尾、
> 编号只递增，不要在已有编号中间插入新小节——`见§x.x`交叉引用依赖编号稳定）。每条尽量只留
> "怎么写是对的"+ 一句话背景，详细踩坑过程留在第 1-6 节（或 §8），用 `见 §x.x` 互相引用，
> 避免重复。**新增一个完整的质谱仪部件（几何+物理场组合、有自己的验证脚本）时，除了在
> 新开的 §7.x 小节里写细节，还要在 §7.0 的部件库表格里加一行**（部件名/核心机制/关键结果/
> 脚本/详见），以及在 §7内容分类索引 的"已验证的质谱仪部件"一类里补上这个新编号——
> 这两处是本文档最高频被查阅的入口，保持同步比小节内容本身更重要。

### 7.0 已验证质谱仪部件库速查表

> **用途**：新任务第一步先扫一眼这张表——如果要建的部件（或近似同类部件）已经在这里，
> 直接复用/改造对应脚本和参数，不要从零重新摸索建模方式；表格只列结论和入口，
> 具体调用写法、踩过的坑都在"详见"指向的 §7.x 小节里。

| 部件 | 核心物理机制 | 关键验证结果 | 参考脚本 | 详见 |
|---|---|---|---|---|
| 电子枪（螺旋灯丝+Wehnelt） | 热发射(`Thermal`)+Wehnelt偏压聚焦 | 横置线圈收集效率34.18% > 轴向线圈27.71%；Wehnelt偏压存在非单调最优点(不是越负越好) | 电子枪 phase1-5 系列脚本 | §6.1-6.3 |
| 螺线管线圈 | `InductionCurrents`+`Coil`(Numeric) | 中心磁场/无限长理论值比值0.85(有限长度螺线管符合物理直觉) | `test_magnetic_coil.m` | §7.14, §8 |
| 均匀磁场回旋运动(裸测试) | 均匀Bz+`MagneticForce` | 回旋半径0.58mm vs理论0.57mm(2%误差)，轨迹为正圆 | `test_cpt_magnetic_force.m` | §7.15, §8.5 |
| 四极/六极/八极杆 | RF交替电位；仅四极有严格马蒂厄稳定性 | on-axis电位幂律`r^(N/2)`吻合4位有效数字；四极q=0.5稳定/q=1.2发散；六极/八极是"离子导管"而非质量滤波器 | `test_multipole_geometry.m` / `test_multipole_es.m` / `test_quadrupole_stability.m` | §7.16 |
| 爱因茨尔透镜(Einzel Lens) | 静电透镜聚焦 | 聚焦强度只取决于`KE_beam/|V_lens|`比值(标度律)，不取决于绝对值 | `test_einzel_lens.m` / `test_einzel_cpt.m` | §7.17 |
| 线性离子阱(LIT) | RF四极径向约束+DC端盖轴向约束 | 轴向束缚呈现平滑抛物线往返运动，全程未接近电极 | `test_lit_geometry_es.m` / `test_lit_cpt.m` | §7.18 |
| TOF飞行时间分析器+反射器 | 加速→漂移→反射镜减速反弹 | `t∝sqrt(m)`吻合(100 vs 200amu，误差0.5%)；漂移管必须接地侧壁 | `test_tof_reflectron_es.m` / `test_tof_cpt.m` | §7.19 |
| ESA静电扇形场能量分析器 | 同轴柱形电容器径向场`E=V0/(r·ln(R2/R1))` | FEM与解析解吻合4位有效数字；能量选择性验证(设计能量稳定/偏差30%撞外壁) | `test_esa.m` | §7.20 |
| 磁扇形场质谱仪 | 均匀B场回旋运动，固定KE下按质量分离 | `r∝sqrt(mass)`吻合5位有效数字(50/150amu) | `test_magnetic_sector.m` | §7.21 |
| 碰撞池/CID(背景气体碰撞) | `Collisions`+`Elastic`子特征(必须加子特征才生效) | 损失率/碰撞数随`Nd`单调变化(1e18→1e20/m³对应3.1%→100%损失) | `test_collision_cell.m` / `test_collision_cell_gpu_comparison.m` | §7.22 |
| 共振电荷交换碰撞 | `Collisions`+`ResonantChargeExchange`子特征，速度瞬间近乎归零(区别于Elastic的渐进散射) | 25%粒子出现单步>90%速度骤降，轨迹图呈现尖锐"V形"速度低谷 | `test_resonant_charge_exchange.m` | §7.25 |
| Wien滤波器(交叉E×B) | 正交均匀E场+B场，`v=E/B`只筛速度、与质量电荷无关 | 共振速度偏转≈0；快/慢20%偏转符号相反且吻合手算理论；200amu同速度下同样偏转≈0(质量无关性) | `test_wien_filter.m` | §7.23 |
| 空间电荷/库仑排斥 | `ParticleParticleInteraction`(`InteractionForce='Coulomb'`) | 有vs无相互作用，径向扩散标准差相差33倍、最大半径相差28倍 | `test_space_charge.m` | §7.24 |
| FTICR/ICR离子回旋共振池 | 均匀B场回旋(径向)+DC端盖(轴向)组合捕集 | 两种约束分别独立验证有效；组合后出现真实的磁控漂移(magnetron drift)现象，非bug | `test_icr_cell.m` | §7.26 |
| 简单质谱仪整机(EI源→引出→多极杆→TOF→反射器→检测器) | 电子撞击电离(`Ionization`碰撞) + 引出加速 + RF多极杆导管 + TOF漂移+单次反射 | 电离产率与理论(Nd·σ·L)吻合 | `ms_stage1_ei_source.m`(其余早期TOF/反射器脚本已被§7.28的环栈反射镜设计取代并删除) | §7.27 |
| 正交加速TOF(oa-TOF)：三栅精确时间聚焦加速器(方形屏蔽罩+方形环电极，D=0)+双级Mamyrin环栈反射镜(闭式解E1/E2，L_total几何对齐修正)+理想细网格栅网(内部边界)+单一静态场(无脉冲) | 三栅加速器(repeller/grid1/grid2，用"三栅加速器总长度符号推导"闭式解设计，KE0=2000eV/ΔKE=±80eV/Δx0=1mm/d1=3mm，实测到达无场区边界时刻方差=0，上游传输时间问题彻底解决；加速器本体用**方形屏蔽罩**(半宽35mm)+5个方形渐变环电极约束场，而非铺满全域的理想平面，圆柱形方案曾因边缘效应失败，方形独立测试后整合成功) + 双级环栈反射镜(用`reflectron_dual_stage_solver.py`同时解一阶+二阶聚焦条件得到E1/E2/V_mid/V_mirror；`L_total`修正为`2*(L_flight-L_accel)=960.34mm`而非早期误用的`L_flight×2=1000mm`，探测器移到无场区边界`L_accel+0.3mm`使L1/L2与理论假设对齐) + 5环/级(环数不是瓶颈，且用"理论完美场"诊断法+重新扫描发现`bore_r`应该**扩大**而非收窄，250mm/350mm是性价比最优点) + CPT非线性求解器由GMRES(`i1`)换成直接求解器(`dDef`)修复N≥20必现的崩溃 + 反射镜环电极几何中心与理论电压对齐修复(`Cylinder`底面圆心≠环几何中心的0.5mm偏移) + 飞行管圆柱化统一entgrid/midgrid/grid2/backplate尺寸关系(`flight_tube_r`/`ring_outer_r`) + CPT输出tlist分段加速(耗时降约33%，精度不变) + 修正加速器/飞行管/反射镜不同轴的bug(`x_refl_center`统一重置为0) + 修正几何使L1=L2=500mm严格成立(`L_flight=L_accel+500mm`，探测器移到x=420mm/z=L_accel精确避开grid2圆盘)，反射镜理论按`L_total=1000mm`重新求解(`V_mid=1866.67V`/`V_mirror=4551.15V`) + 飞行管改为实体封闭管(延长加速器屏蔽罩包裹repeller，飞行管背端用不开孔的实心大圆盘封闭，grid2恢复为加速器自身的小出口栅网，repeller背面加封板消除环形缝隙场泄露) + 全面加厚屏蔽罩与环电极(加速器屏蔽罩2→4mm，飞行管新增10mm显式实体壁，反射镜环电极1→5mm) + 屏蔽罩统一延长包住反射区(两端全盘封闭，backplate同步加厚到5mm) + repeller背板与两端端盖厚度统一(分别匹配加速器/飞行管侧壁厚度) + 飞行管屏蔽罩改为"一次做差"单体壳设计(消除端盖与圆柱壁的真实几何重叠) + repeller尺寸对齐环电极外轮廓、背板焊死进屏蔽罩本身(一次做差)、删除冗余的reflvac + "完全封闭包围"理论验证(grid1/midgrid安全收缩间隙，grid2/entgrid保持全尺寸密封)、探测器移到L2=500mm真实落点(x=94.93mm)+探测判定逻辑修复(处理物理碰撞冻结轨迹) + 探测器上表面位置修正、显式Wall/Freeze边界、无场区扩到600mm(L1=L2=600mm)、d1参数化+扫描寻优(d1=120mm最佳，R=14220.7) + d2自适应化(按d1动态算`d2_min*1.3`)、端盖间隙加大到20mm、加速器与探测器关于飞行管真轴对称放置(`x_accel_center=-48.80mm`/探测器`+48.80mm`，含grid1/grid2选择框漏更新的bug修复)、确认场与粒子追踪均为COMSOL内置物理接口(非自定义方程) | N=100(1ns步长)：100%命中，当前(d1=120mm+对称放置+自适应d2)到达时间`31.41289±0.00175us`，**质谱分辨率R≈8966.2**(历史范围R≈5756-18848视d1/d2/对称化等具体几何参数波动，无场漂移区始终保持-0.0000V/m的完美精度，加速器场始终准确匹配160000/104570V/m目标)；用"选择性理想化"隔离实验确认**反射镜环栈场精度是绝对主导瓶颈**(只让反射镜理想化即可让R恢复到12852.7≈理论上限，只让加速器理想化则几乎无变化)；CPT求解耗时85-165s | `ms_modelA_collisional_cooling.m` / `ms_modelB_ringstack_reflectron.m`(唯一保留的reflectron模型) + `reflectron_dual_stage_solver.py`(双级反射镜闭式解) + `test_square_shield_accel.m`(方形屏蔽罩独立验证模型) + `scan_d1.m`(d1扫描脚本) | §7.28-§7.50(§7.35为分辨率排查方法论速查，§7.41为L1/L2分配无关性的理论+实测双重验证，§7.42为飞行管封闭端盖设计，§7.43-§7.50为屏蔽罩加厚/统一/消除重叠/间隙修正/探测器落点/d1扫描/d2自适应/对称放置) |

### 7内容分类索引

> 下面的 §7.x 编号本身**不做调整**（避免破坏全文已有的大量 `见§7.x` 交叉引用），
> 这里只是把现有条目按主题重新分组，方便按需求跳转，而不用从7.1顺序翻到7.26。

- **环境/会话管理**：§7.1（会话/模型管理）、§7.13（服务端启动命令）
- **几何/材料/网格/静态求解通用套路**：§7.2（几何建模）、§7.3（选择集）、§7.4（材料）、§7.5（静电场）、§7.6（网格/稳态求解）
- **CPT粒子追踪核心机制**：§7.7（CPT物理场基础）、§7.8（时间相关study，含"复用已存ES场"关键设置）、§7.9（结果绘图/导出）、§7.10（数值提取函数选型：mpheval/mphinterp/mphparticle）
- **磁场物理场**：§7.14（`InductionCurrents`/`Coil`特征，完整调试叙事见 §8）
- **CPT里的力/碰撞/多体效应**：§7.15（磁场力/点释放/发射方向分布/壁面条件/粒子间相互作用入口）、§7.22（背景气体碰撞-Elastic）、§7.24（空间电荷/库仑排斥实测）、§7.25（共振电荷交换碰撞）
- **GPU求解器**：§7.11（cuDSS，结论：本项目规模下比CPU慢，不要默认开）
- **已验证的质谱仪部件（几何+物理组合实例，对应 §7.0 表格）**：§7.16（多极杆）、§7.17（爱因茨尔透镜）、§7.18（LIT）、§7.19（TOF+反射器）、§7.20（ESA）、§7.21（磁扇形场）、§7.23（Wien滤波器）、§7.26（ICR池）、§7.27（简单质谱仪整机集成：EI源→引出→多极杆→TOF→反射器→分辨率）、§7.28（oa-TOF：碰撞冷却+真实环栈反射镜+尺寸匹配检测器，唯一保留的reflectron设计）
- **理想细网格栅网(内部边界技术) + Release特征分布/随机化API**：§7.29（`Union`+`intbnd`嵌入零厚度栅网、`Box`+`'allvertices'`选择避坑、`InitialPosition='Density'`显式指定粒子数、`v0`里用`random()`手动Box-Muller构造高斯能量分布、GPU/CPT关系再确认）
- **黑名单**：§7.12（已确认无效/错误的调用，不要重试）

### 7.1 会话 / 模型管理
| 调用 | 说明 |
|---|---|
| `mphstart(2036)` | 连接本机已启动的 comsolmphserver（端口 2036）。每个 `matlab -batch` 脚本开头都要单独调用一次。 |
| `ModelUtil.create('Model')` | 新建一个空模型，tag='Model'。 |
| `ModelUtil.load('Model', path)` | 从 .mph 文件加载模型到 tag='Model'。 |
| `ModelUtil.remove('Model')` | 删除服务端内存里的模型 tag。**载入前必须先检查并清理同名 tag**（见 §3.4）。 |
| `cell(ModelUtil.tags())` | 列出服务端当前所有模型 tag（跨客户端连接持久存在）。 |
| `model.save(path)` | 保存为 .mph。**注意幂等性**：存到新文件名，不要覆盖自己读取的源文件（见 §3.3）。 |
| `model.label('xxx')` | 给模型设标签（仅显示用，不影响 tag）。 |

### 7.2 几何建模
| 调用 | 说明 |
|---|---|
| `comp1 = model.component.create('comp1', true)` | 2 参数 (tag, boolean)，无维度参数（见 §1.1）。 |
| `geom1 = comp1.geom.create('geom1', 3)` | 维度(3=三维)在这里指定。 |
| `geom1.lengthUnit('mm')` | 设长度单位；会影响后续 `mphinterp`/`mpheval` 坐标单位（见 §2.6 坑A）。 |
| `geom1.feature.create(tag,'Cylinder')` + `.set('r',...)/.set('h',...)/.set('pos',{'x','y','z'})/.set('axis',[0 0 1])` | 圆柱体图元。 |
| `geom1.feature.create(tag,'Cone')` + `.set('r',...)/.set('specifytop','radius')/.set('rtop',...)/.set('h',...)/.set('pos',...)` | 圆锥台图元；`specifytop` 是字符串 `'radius'`（不是 boolean），顶面半径属性是 `rtop`（不是 `r2`/`ratio`）（见 §1.2）。 |
| `geom1.feature.create(tag,'Difference')` + `.selection('input').set({...})` + `.selection('input2').set({...})` | 布尔差；`input`=被减，`input2`=减去的。 |
| **Fillet / Chamfer 特征** | 本环境许可证不支持（见 §1.2），改用 Cone−Cylinder 手工倒角，不要再试 Fillet/Chamfer。 |
| `geom1.feature(tag).set('selresult','on')` | 开启该图元的自动域选择输出，之后可用 `geom1_<tag>_dom` 引用（见 §1.4）。**但要注意**：如果该图元与其他图元有大范围空间重叠（比如一个包住所有电极的外层"真空域"圆柱体），`selresult` 生成的命名选择可能不是"纯净"的那个域，而是包含了所有和它重叠过的最终子域（实测两次：`geom1_cyl6_dom` 不管是简单直圆柱阴极还是线圈阴极几何，都解析出全部域，不是只有真空域一个）——**正确修复：不要用外层大圆柱的 selresult 当真空域，改用 `comp1.selection.create('sel_vac','Complement')` + `.set('input',{电极域1,电极域2,...})`，对"真正独立不重叠"的电极域（如线圈/倒角后的Wehnelt/阳极）取补集，实测能正确解析成唯一 1 个真空域**。任何选择用之前都先 `comp1.selection('xxx').entities()` 打印检查实际解析到的域编号，不要直接假设名字对应的就是预期的那一个域。 |
| `geom1.run` | 构建几何（布尔运算、自动切分域）。 |
| `mphgeominfo(model,'geom1')` | 返回 `Ndomains/Nboundaries/Nedges/Nvertices`（大写开头字段）；`geom1.getNEdge()` 这类方法不存在（见 §1.3）。 |
| `geom1.feature.create(tag,'Helix')` + `.set('rmaj',...)/.set('rmin',...)/.set('axialpitch',...)/.set('turns',...)/.set('pos',{'0' '0' 'z0'})` | **原生螺旋线圈实体图元**，不需要额外的 Sweep-along-curve！`type` 默认 `'solid'`（另有 `'surface'`），`rmaj`=线圈半径，`rmin`=线材（钢丝）截面半径，`axialpitch`=每匝轴向间距，`turns`=匝数，`chirality`默认`'right'`，`endcaps`默认`'paraaxis'`（平端面）。属性名容易搞错的排查方法同 §4.1：故意传错值让报错列出合法属性/取值。 |
| `hel1.set('axistype','x')`（或`'y'`/`'z'`/`'cartesian'`/`'spherical'`） | 螺旋轴朝向；默认`'z'`。改成`'x'`后，`pos`就是螺旋沿x轴的**起点**（螺旋从这个点开始沿+x方向延伸`turns*axialpitch`的长度），`pos`的y/z分量则是螺旋横截面圆心的位置——想让线圈"横躺"、某一侧正对着轴向的某个方向（比如正对阳极孔），把线圈中心摆到目标y/z、再用`pos`的x分量把线圈沿x居中，很直接。（应用场景见 §6.3：灯丝线圈轴垂直于枪轴时更利于电子朝阳极方向发射。） |
| `mphgeom(model,'geom1', 'facealpha',0.5)` + MATLAB `print(fig,'file.png','-dpng')` | **验证复杂几何（比如线圈）最可靠的可视化方式**：用 MATLAB 自己的图形引擎渲染（`figure('Visible','off')`），完全不经过 `comsolmphserver` 的图形导出管线，不受 §3.1 记录的卡死/崩溃风险影响，`matlab -batch` 无 GUI 环境下同样能正常出图。 |

### 7.3 选择集 (Selection)
| 调用 | 说明 |
|---|---|
| `comp1.selection.create(tag,'Adjacent')` + `.set('input',{'geom1_xxx_dom'})` | 组件级"相邻边界"选择，从域选择拿到该域的边界面（见 §1.4）。 |
| `feature.selection.named('tag')` | 材料/物理场特征引用命名选择的标准写法。 |
| `sel.entities()` | 返回该选择实际解析到的实体编号数组（域/边界的整数索引），**排查选择是否解析对了的关键手段**，不要只看名字。 |

### 7.4 材料
| 调用 | 说明 |
|---|---|
| `model.material.create(tag,'Common')` + `.selection.named(...)` + `.propertyGroup('def').set('relpermittivity',{'1'})` | 标准写法（见 §1.5）。 |

### 7.5 静电场 (Electrostatics)
| 调用 | 说明 |
|---|---|
| `es = comp1.physics.create('es','Electrostatics','geom1')` + `.selection.named(sel_vac)` | 限定物理场作用域。 |
| `es.create('pot1','ElectricPotential', 2)` + `.selection.named(...)` + `.set('V0', 'V_expr_or_param')` | 电位边界条件，2=边界级别（见 §1.5）。 |

### 7.6 网格 / 稳态求解
| 调用 | 说明 |
|---|---|
| `mesh1 = comp1.mesh.create('mesh1')` + `.feature('size').set('hauto', N)` + `.run` | N: 1=最细...9=最粗，"Finer"≈3。**警告**：这个"只设全局size就run"的写法不保证真的生成域网格！见下面 FreeTet 那一行。 |
| `mesh1.feature.create('sz1','Size')` + `.selection.geom('geom1',2)` + `.selection.named(边界选择)` + `.set('custom','on')` + `.set('hmaxactive',true)` + `.set('hmax',...)` + `.set('hminactive',true)` + `.set('hmin',...)` + `.set('hgradactive',true)` + `.set('hgrad',1.3)` | 对特定边界（比如细线圈钢丝表面）显式指定局部网格尺寸（不是用 `hauto` 预设，那是全局粗细档位，局部用具体数值更可控）。 |
| **`mesh1.feature.create('ftet1','FreeTet')`（域填充网格特征）** | **【高优先级坑】必须显式加，不要假设 `mesh.create()+size+run()` 会自动补一个域填充网格！** 实测：即使是和之前验证过的直圆柱阴极模型完全相同的写法（`mesh1.feature('size').set('hauto',3); mesh1.run;`，不加任何自定义局部 Size），换到线圈阴极几何上就**静默生成了空网格**——`mesh1.run()` 不报任何错误/警告，后续 `model.sol('sol1').runAll` 也"成功"跑完，但求解出的其实是一个空网格上的无意义结果：域级 `mpheval` 查询返回 0 个点，`mphinterp`/`mphmax` 对**任意坐标**（不只是复杂几何附近的坐标）都报 "Cannot evaluate expression. - Feature: Interpolation"。**这是判断"网格其实是空的"的关键信号**：如果连远离任何精细几何的普通坐标点插值都失败，先怀疑网格没建好，不要怀疑坐标本身。加一行 `mesh1.feature.create('ftet1','FreeTet')` 后网格能正常生成。 |
| `meshinfo = mphmeshstats(model,'mesh1')` + 检查 `meshinfo.isempty`/`.hasproblems`/`.iscomplete` | **网格建完后必须显式检查这三个字段再往下走**，不要只看 `mesh1.run` 有没有抛异常——上面那个坑就是"不抛异常但网格是空的"。 |
| `model.study.create('std1')` + `.create('stat1','Stationary')` | 稳态 study。 |
| `model.sol.create('sol1')` + `.study('std1')` + `.createAutoSequence('std1')` + `.runAll` | 标准求解四步（见 §1.5）。 |

### 7.7 带电粒子追踪 (CPT) 物理场
| 调用 | 说明 |
|---|---|
| `cpt = comp1.physics.create('cpt','ChargedParticleTracing','geom1')` | 自动带 `wall1`(默认Freeze，兼作吸收/探测面)、`pp1`(默认电子: `mp=me_const`,`Z=-1`)、`dpcon1`（装配体用，可忽略）（见 §2.1）。 |
| `cpt.create('inl1','Inlet', 2)` + `.selection.named(...)` + `.set('N',1)` | 从边界发射粒子；默认 `v0=0`、方向=边界法向（见 §2.2）。**不是** `Release`/`ReleaseFromBoundary`。 |
| `inl1.set('VelocitySpecification','Thermal')` + `.set('T_src','userdef')` + `.set('T','2700[K]')` | **内置的热发射（Maxwell-Boltzmann 通量加权分布）release 模式**，不用手动算单一等效速度再塞给 `v0`。合法取值（故意传错值从报错里拿到）：`VelocitySpecification` ∈ `"SpecifyVelocity"`(默认)/`"SpecifyMomentum"`/`"SpecifyKineticEnergy"`/`"Thermal"`；`InitialVelocity`(另一个相关但不同的属性，"Expression"模式下的取值方式) ∈ `"Expression"`/`"ConstantSpeedHemisphere"`/`"ConstantSpeedCone"`/`"ConstantSpeedLambertian"`，容易和 `VelocitySpecification` 搞混，注意区分。`T` 默认 `293.15[K]`(室温)。钨丝典型热发射工作温度取 **2700K**。实测效果：均匀法向零初速(v0=0)时，紧密线圈相邻匝之间的自吸收比例高达92%，改用 Thermal 之后骤降到0.03%（发射方向不再局限于纯法向，绝大多数电子有机会避开正对面的相邻匝），是个物理上很直觉但数值上很显著的差异。 |
| `cpt.create('ef1','ElectricForce', 3)` + `.selection.named(sel_vac)` + `.set('E_src','root.comp1.es.Ex')` | 把 es 物理场的电场耦合进粒子受力；`E_src` 必须是这个完整限定字符串（见 §2.3）。**不是** `model.multiphysics.create(...)`。 |

### 7.8 时间相关粒子追踪 Study（含"复用已存 ES 场"的关键设置）
| 调用 | 说明 |
|---|---|
| `std2.create('time1','Transient')` + `.set('tlist','range(0,dt,tmax)')` + `.setEntry('activate','es',false)` + `.setEntry('activate','cpt',true)` | 只重新求解 cpt，跳过重解 es。 |
| `model.sol('sol2').feature('v1').set('notsolmethod','sol')` + `.set('notsol','sol1')` | **必须显式加这两行**，否则"未求解变量"（如 es 场）默认取初始值(≈0)而非 Study1 的解，导致粒子受力为0、完全不动（见 §2.4，本次实测的头号大坑）。属性名是 `notsol`，**不是** `notsolnum`（那个是选 "auto/all/first/last/from_list/interp/manual" 或整数，语义完全不同）。 |
| 排查手段 | `mphinterp(model,'es.normE','coord',coords,'dataset','dset2')` 对比 `dataset','dset1'`，处处为0说明踩了上面这个坑（见 §2.4）。 |

### 7.9 结果绘图 / 导出
| 调用 | 说明 |
|---|---|
| `pg = model.result.create(tag,'PlotGroup3D')` | 三维绘图组。 |
| `pg.create('slice1','Slice')` + `.set('quickplane','xy'/'yz'/'zx')` + `.set('quickznumber','1')`(同理x/y) + `.set('expr','V'/'es.normE')` | 切面图；**不是** `'xz'`（顺序反了会报错）；不显式设 quick*number 会默认铺开多张切面（见 §1.6）。 |
| `pdset1 = model.result.dataset.create('pdset1','Particle')` + `.set('solution','sol2')` | 粒子轨迹图必须用专门的 Particle 数据集，属性名是 `solution` 不是 `data`；直接把 `PlotGroup3D.set('data','dset2')` 指向原始 Solution 会报错 "Operation cannot be performed on..."（见 §2.7）。 |
| `pg3.create('traj1','ParticleTrajectories')` | 轨迹图层，`data` 指向 `pdset1`。 |
| `model.result.export.create(tag,'Image')` + `.set('plotgroup',...)` + `.set('pngfilename',...)` + `.set('width'/'height',...)` + `.run` | 图片导出。**批处理模式下 `ParticleTrajectories` 的导出有已知稳定性风险，见 §3.1**；普通 Slice/Surface 图导出没有这个问题。 |

### 7.10 数值提取函数：mpheval / mphinterp / mphparticle 该怎么选
| 需求 | 用哪个 | 关键点 |
|---|---|---|
| 任意坐标处插值某个场量（V、es.normE...） | `mphinterp(model, 'expr', 'coord', coords, 'dataset', tag)` | 坐标单位=`geom.lengthUnit`（见 §2.6坑A）；粒子study的 `dataset` 要配合 `'t', t值` 才能拿到某一时刻切片，`'outersolnum','end'` 对时间/粒子数据集**不代表最后一步**（见 §2.6坑B）。 |
| 取粒子（CPT）在某时刻的坐标/其他量 | ~~`mpheval(...,'dataset','dset2','edim',0)`~~ **不要用**，会静默返回错误的 FEM 网格顶点数据（见 §2.5b） | 正确：`mphparticle(model,'dataset','pdset1')`，返回 `.p/.v` 为 `[nTimes x nParticles x 3]` 的 **double 数组**（不是 cell！），`.t` 为 `1 x nTimes` 时间向量，与 study 的 tlist 完全对应。取法：`pd.p(k,:,3)` = 第k个时间步所有粒子的z；`pd.p(:,j,3)` = 第j个粒子随时间的z。 |
| 取粒子末态动能（无变量名可用时） | 能量守恒法：末态坐标 + `mphinterp(model,'V','coord',...,'dataset','dset1')`（见 §2.5） | 前提：粒子从 V≈0 处以≈0eV 初速释放、纯静电场加速、无磁场/碰撞损耗。 |
| ~~`cpt.Ep`/`Ek`/`KE`/`kin_en`/`Ekin`/`speed`/`U`/`qx`/`vx`~~ | **不存在，不要试**（"Undefined variable"，见 §2.5） | 用上面的能量守恒法代替。 |
| 对 `Particle` 类型数据集（如 `pdset1`）用 `mpheval` 并传 `'edim'` 参数 | **不要用，会卡死**（实测8分钟无响应，见 §2.5b/§3.1类比） | 用 `mphparticle`，不要给它传 `edim`。 |
| 粒子中途被吸收（不管是撞墙、还是紧密线圈里撞到相邻匝）后，它在 `pd.p`/`pd.v` 里后续时刻的值 | 实测表现不完全一致：有的场景冻结在最后有效坐标（旧的直圆柱阴极模型），有的场景（线圈阴极，大量粒子在第一个 0.1ns 输出步之前就已被吸收）直接是 **NaN**，且同一批 NaN 粒子在所有后续时间点都保持 NaN（不是"某个时刻突然变成NaN"，而是从第一个记录点起就已经是 NaN）——这提示 NaN 出现的粒子很可能是在小于最小输出时间分辨率内就已完成吸收。**不要假设"被吸收=冻结在小z值"，两种表现都要处理**：用 `isnan(...)` 单独统计"丢失"的粒子数，不要只看 `z<阈值` 判断早期吸收。 |
| 对含 NaN 的数组算 `min`/`max` vs `mean`/`median` | **MATLAB 陷阱**：`min`/`max` 默认自动忽略 NaN，但 `mean`/`median` **不会**，只要数组里有一个 NaN，`mean`/`median` 就返回 NaN，很容易造成"min/max 正常但 mean/median 是NaN"的困惑现象。统计粒子能量/位置前，先用 `isnan` 过滤掉真正失效的粒子（不代表数值错误，代表该粒子已被吸收/丢失），或用 `mean(x,'omitnan')`。 |

### 7.11 GPU 求解器 (cuDSS)
| 调用 | 说明 |
|---|---|
| `sol1.feature('s1').feature('dDef').set('linsolver','cudss')` + `sol1.feature('s1').feature('fc1').set('linsolver','dDef')` | 切换到 GPU 直接求解器（见 §5）。**结论：几万自由度规模下比默认 CPU 迭代法慢 58%，小模型不要默认开**，只有百万自由度以上量级才可能有优势。 |

### 7.12 已确认无效/错误的调用（黑名单，不要重试）
- `model.multiphysics.create('epf1','ElectricForce', ...)` → "Unknown multiphysics coupling"（正确见 §7.7 / §2.3）。
- `geom1.getNEdge(tag)` → 方法不存在（正确见 §7.2 `mphgeominfo`）。
- `geom1.feature.create('fil1','Fillet')` / `'Chamfer'` → 许可证限制报错（正确见 §7.2 Cone−Cylinder 手工倒角）。
- `cpt.Ep`/`Ek`/`KE`/`kin_en`/`Ekin`/`speed`/`U`、`comp1.qx`/`cpt.qx`/`cpt.vx` → "Undefined variable"（正确见 §7.10 能量守恒法）。
- `mpheval(...,'dataset','dset2','edim',0)` 取粒子坐标 → 不报错但语义错误，返回 FEM 网格顶点数据，非粒子数据（正确见 §7.10 `mphparticle`）。
- `mpheval(...,'dataset','pdset1','edim',0)` → 卡死（正确见 §7.10 `mphparticle`，不要传 `edim`）。
- `model.sol('sol2').feature('v1').set('notsolnum', 'sol1')` → 报错 "'Selection' can be: auto/all/first/last/from_list/interp/manual"（正确属性名见 §7.8 `notsol`）。
- `v1.set('notstudy'/'notsollist'/'notsolstudy'/'notsolstudystep', ...)` → "Unknown property"（这几个名字都不存在，正确见 §7.8 `notsol`+`notsolmethod`）。
- `'outersolnum','end'` 用于取时间相关/粒子数据集的"最后一步" → 实际取回所有时间步×所有粒子混在一起（正确见 §7.10 显式传 `'t',tend`）。
- `comsolmphserver.exe ... -3drend sw -graphics`（长期运行的共享服务端上使用） → 有实测记录会在后续某次操作异步崩溃（`csgraphics_sw.dll` 访问违例），虽然也有一次实测未复现崩溃且轨迹线正常导出（见 §3.1 两处记录，结论仍偏谨慎不推荐）。
- `mesh1 = comp1.mesh.create('mesh1'); mesh1.feature('size').set('hauto',N); mesh1.run;`（不显式加 `FreeTet`/其他域填充特征） → 在简单几何（直圆柱阴极）上能用，但换到更复杂的几何（螺旋线圈）上**不抛任何错误、却静默生成空网格**，求解器照样"成功"跑完但结果毫无意义（正确做法见 §7.6 `FreeTet` + `mphmeshstats` 检查）。**不要认为这个模式在新几何上一定还能用，每次换几何后都应验证网格非空。**
- `comp1.physics.create('mf','MagneticFields',...)` → "Unknown physics interface"（正确 tag 见 §7.14 `InductionCurrents`）。
- `std1.create('cga1','CoilGeometryAnalysis')` → "Operation cannot be created in this context"（正确 study-step 类型见 §7.14 `CoilCurrentCalculation`，跟 Coil 子特征 `ccc1` 同名）。
- `mphinterp(model,'es_rf.Ex',...)` / `'es_dc.normE'`（自定义物理场tag直接当变量名用，且同一component里有多个同类型物理场时） → "Undefined variable"（正确见 §7.18，变量命名空间按类型+创建顺序自动分配 `es`/`es2`，不跟自定义tag）。
- `comp1.selection.create(tag,'Union')` / `'Difference'` + `.set('input2',{...})`（组件级别选择组合运算） → 前者报"Selection on wrong geometric entity level"（缺 `.geom('geom1',2)`），修复后又报"Unknown property: input"（属性名不确定，未验证）——正确做法见 §7.19，改用 `Adjacent`取全部实体ID + MATLAB `setdiff` 算差集 + `Explicit`选择类型。
- `p.set('h','10[mm]')`（用`h`作为自定义模型参数名） → 求解时报 "Duplicate parameter/variable name. Variable: h. Global scope"（`h`是COMSOL保留的全局变量名，正确做法见 §7.20，换成`h_cyl`等不冲突的名字）。
- `inl1.set('v0','5[m/s]')`（`Inlet`的`v0`给标量表达式） → "A vector of length 3 expected"（即使概念上只想要一个标量速度+固定方向，`Expression`模式下`v0`语义仍是完整三分量向量，正确见 §7.19 `{'0','0','v'}`）。
- 磁扇形场/回旋运动类CPT测试，`MeshBased`域内撒点后随手挑一个粒子分析、且圆轨道直径接近或超过域尺寸 → 测得半径可能精确是理论值的整数分之一（如0.5倍）而不是随机噪声，是轨道被边界截断，不是物理误差，正确排查/修复见 §7.21。
- `std1.create('sss1','StationarySourceSweep')` 用于单线圈 → 能创建，求解时报 "No sources found."（这个 study 类型是给多线圈互感扫描用的，见 §7.14）。
- `cpt.create('lf1','LorentzForce',...)` → 不存在，正确名字是 `'MagneticForce'`（见 §7.15）。
- `rel1.set('InitialPosition', 'Manual')` 或 `cpt.create('rel1','Release',0)`（点级别） → 前者报 "Invalid parameter value"（合法值只有 MeshBased/Density/RandomPosition），后者报 "Cannot create feature in the specified element dimension"（`Release` 只能在 edim=3 创建，见 §7.15）。
- `rel1.set('rc', {...})` 试图当"释放坐标"用 → `rc` 其实是"Release current magnitude"（释放电流大小，标量），不是坐标，名字容易望文生义猜错。
- `ppi1.set('InteractionType'/'ForceType'/'Interaction', ...)` → 都是 "Unknown parameter"，正确属性名是 `InteractionForce`（见 §7.15）。
- **`MagneticForce`/`ElectricForce` 等力特征忘记调用 `.selection`** → 不像 `Release`/`Inlet` 那样在编译期报错，而是静默地让力处处为零，粒子沿直线运动、能量仍然守恒，很容易被误判成"物理是对的"而不是"没生效"（见 §7.15，本次为此专门排查了一次）。
- **同一 component 里创建第二个同类型物理场（比如两个 `Electrostatics`）时，用 `mphinterp`/`mpheval` 表达式里引用自己起的自定义 tag（如 `'es_rf.Ex'`/`'es_dc.normE'`）** → 报 "Undefined variable"。COMSOL 的变量命名空间**不跟着你传给 `physics.create(tag,...)` 的自定义 tag 走**，而是按物理场"类型"自动从默认前缀开始编号（第一个 `Electrostatics` 永远叫 `es`/依赖变量 `V`，第二个自动变成 `es2`/`V2`，不管你给它们起的 Java API tag 是什么）。`tag` 只在 Java API 层面（`comp1.physics('mytag')`、`setEntry('activate','mytag',...)`）有效，**表达式/变量引用必须用 COMSOL 默认分配的 `es`/`es2`/`V`/`V2` 这套编号，不是你自己起的名字**（见 §7.17，本次在线性离子阱RF+DC双物理场耦合时踩到，靠依次探测 `V`/`V2`/`es.Ex`/`es2.Ex` 才定位到正确变量名）。

### 7.13 服务端启动命令
```powershell
& "D:\COMSOL 6.4\COMSOL64\Multiphysics\bin\win64\comsolmphserver.exe" -port 2036 -multi on -silent
```
默认 `-3drend ogl`（不加软件渲染参数）是目前证据下更稳的选择（见 §3.1、§7.12）。

### 7.14 磁场物理场 (Magnetic Fields) 与 Coil 特征
| 调用 | 说明 |
|---|---|
| `comp1.physics.create('mf','InductionCurrents','geom1')` | **"Magnetic Fields" 物理场接口的内部 tag 是 `InductionCurrents`，不是 `MagneticFields`**（后者直接报 "Unknown physics interface"，靠故意试错才定位到正确 tag，见 §8）。属于 AC/DC Module，`model_inspect` 报的 `modules` 列表里没显式列出 "AC/DC" 但实测这个物理场是有许可证的，**不要仅凭 modules 列表就断定某个物理场不可用，直接试一次更可靠**。默认自带特征 `fsp1`(自由空间/Ampere定律)、`mi1`、`init1`。 |
| `mf.create('coil1','Coil', 3)` + `.selection.named(域选择)` | 在任意三维实体域（哪怕是不规则形状，比如我们的螺旋线圈）上直接定义"这是一个载流导体"。`CoilType` 默认 `'Numeric'`（合法值：`"Numeric"/"Circular"/"Linear"/"UserDefined"`），对任意真实3D形状用 Numeric 就对，不用改。`CoilExcitation` 合法值 `"Voltage"/"Current"/"CircuitVoltage"/"CircuitCurrent"`，设 `'Current'` 后配 `ICoil`（电流值）。`N`（匝数倍率）**如果线圈的真实绕线形状已经在几何里画出来了（像我们的Helix），设成 `'1'`，不要用默认的 `'10'`**（默认10是给"匀质化"简化线圈准备的，不适用于真实几何）。 |
| `coil1.feature('ccc1').feature('ct1').selection.set(边界编号)` | Numeric 类型的 Coil 会自动带 3 个子特征：`cg1`(UserDefinedCoilGeometry，本场景不用)、`ccc1`(CoilCurrentCalculation，标签"Geometry Analysis 1")内含 `ct1`(CoilTerminal，标签"Input 1")、`cre1`(CoilReferenceEdge)。**`ct1` 必须显式指定一个边界选择**（线圈实体的两个平头端面之一），否则编译报错 "No selection specified for the Input subfeature..."。边界编号在不同几何构建之间不稳定，每次都要用 `Adjacent` 选择重新取该域的邻接边界列表，再挑一个（实测直接挑第一个就能工作）。 |
| Coil 所在域必须有材料的 `electricconductivity`（sigma） | 否则报 "Undefined material property 'sigma' required by Domain Coil 1"。给线圈材料一个真实的电导率（如钨 `1.8e7[S/m]`），周围"空气"域给 `electricconductivity=0`。 |
| **`std1.create('ccc_step1','CoilCurrentCalculation')` 必须在 `std1.create('stat1','Stationary')` 之前加进同一个 Study** | **这是让 Numeric Coil 真正求解出来的关键一步，极易漏掉**：只有 `Stationary` 会报错 "Numeric coil Domain Coil 1 (coil1) not solved for. Solve it in a Coil Geometry Analysis step."。study-step 类型名字**不是**猜测中的 `'CoilGeometryAnalysis'`（报 "Operation cannot be created in this context"），而是和 `ccc1` 子特征同名的 `'CoilCurrentCalculation'`。也**不是** `'StationarySourceSweep'`（那个类型确实能创建成功，但求解时报 "No sources found." ——它是给**多线圈互感扫描**用的，单线圈场景用不上）。`createAutoSequence('std1')` 会看到这两个 study step，自动生成两段 solver 序列（先算线圈电流分布，`su1: StoreSolution` 存下来，再算主磁场）。 |
| `mphinterp(model,'mf.Bz','coord',...,'dataset','dset1')` | 磁场解出来后取磁通密度分量，和 es 物理场取 `V`/`es.normE` 的写法完全一致。 |
| 完整可跑通的参考脚本 | `comsol_scripts/test_magnetic_coil.m`（螺旋线圈通1A电流，求出的中心轴向 B 场和无限长螺线管估算 mu0\*N\*I/L 的比值≈0.85，符合"有限长度线圈磁场应略小于无限长理想值"的物理直觉）。 |

### 7.15 CPT 中的磁场力 / 点释放 / 发射方向分布 / 壁面条件 / 粒子间相互作用
| 调用 | 说明 |
|---|---|
| `cpt.create('mf1','MagneticForce', 3)` + `.selection.???` | 洛伦兹力的磁场部分，**不是** `'LorentzForce'`（这个名字不存在）。`B_src` 合法值：`"EarthsMagneticField"`(真实地磁场，按经纬度/日期算)/`"userdef"`/`"fromCommonDef"`（如果模型里还有一个已求解的 `mf`(`InductionCurrents`) 物理场，还会额外出现 `"root.comp1.mf.Bx"` 这种选项，和 ElectricForce 的 `E_src` 完全同一套路）。`userdef` 模式下用 `.set('B', {'0','0','0.01[T]'})` 给一个显式三分量表达式。**⚠️极易踩的坑：`MagneticForce` 特征创建后必须显式 `.selection.all`（或 `.selection.named(...)`）指定作用域，和 `ElectricForce` 一样——但和 `Release`/`Inlet` 不同的是，选择为空时它不会在编译期报错，只会静默地让磁场力处处为零，粒子于是走一条看起来"毫无问题"的直线（因为速度大小仍然守恒，容易被误判成"物理是对的，只是没转起来"）。排查方法：先画轨迹图看是不是直线，而不是只看有没有报错。** |
| `cpt.create('rel1','Release', 3)` | 和 `Inlet`（边界2维）平行的**域(3维)级别**粒子释放特征，用于"体内释放"而不是"从表面发射"。`InitialPosition` 合法值只有 `"MeshBased"/"Density"/"RandomPosition"`——**没有"手动指定单点坐标"这个选项**（试过 `'Manual'` 报错，也试过 `cpt.create('rel1','Release',0)` 点级别创建，报 "Cannot create feature in the specified element dimension" ——`Release` 只能在 edim=3 创建）。想要"单点、精确坐标、精确速度矢量"的测试场景，只能接受粒子会在整个域选择内按网格节点/密度/随机撒开，测试均匀场里的物理规律（比如回旋半径/周期）这类不依赖具体起点的场景完全够用；`v0` 属性支持直接设三分量向量 `{'vx','vy','vz'}`（不只是标量速度+法向），配合 `VelocitySpecification='SpecifyVelocity'`（默认）。 |
| `inl1.set('InitialVelocity','ConstantSpeedHemisphere'/'ConstantSpeedCone'/'ConstantSpeedLambertian')` | `Inlet`/`Release` 除了 `'Expression'`(默认，固定方向+`v0`)和 `VelocitySpecification='Thermal'`(完整通量加权麦克斯韦分布，见 §6.1/§7.7) 之外，还有**"固定速度大小、但方向按某种分布随机撒开"**的模式：`ConstantSpeedHemisphere`=半球均匀、`ConstantSpeedCone`=限定圆锥角内均匀、`ConstantSpeedLambertian`=圆锥角内按余弦定律加权（更接近真实蒸发/溅射角分布）。配套属性 `alphac`=圆锥半角（默认 `pi/3`=60°）。这几个和 `Thermal` 是互斥的不同建模简化层级：`Thermal` 速度和方向都物理自洽，这几个只固定速度、方向近似。 |
| `cpt.feature('wall1').set('WallCondition', ...)` | 合法值出乎意料地丰富：`"Bounce"/"Freeze"/"Stick"/"Disappear"/"Pass"/"DiffuseScattering"/"IsotropicScattering"/"MixedDiffuseSpecular"/"GeneralReflection"`（`Otherwise` 属性合法值是其子集，不含最后两个散射模型）。默认 `Freeze`（我们的电子枪模型一直用这个）；`Disappear` 更适合"确认被吸收即可、不关心冻结位置"的统计场景；`Bounce`/`*Scattering`/`GeneralReflection` 适合做真实表面碰撞/二次电子/中性气体散射建模。 |
| `cpt.create('ppi1','ParticleParticleInteraction', 3)` | **CPT 原生支持粒子间相互作用（含库仑排斥/空间电荷效应）**，属性名是 `InteractionForce`（不是直觉猜测的 `InteractionType`/`ForceType`），合法值 `"Coulomb"`(默认!)/`"LinearElastic"`/`"LennardJones"`/`"UserDefined"`——**默认就是 Coulomb**，做大电流电子枪的空间电荷自洽效应时这是入口特征，配套属性 `ks`/`r0`/`rcoff`/`sigma`/`eps`/`Fu`（后三个明显是 Lennard-Jones 分子动力学参数，说明这个特征底层是通用的"成对相互作用"框架，不是专为 Coulomb 写死的）。**完整的空间电荷收敛性/效应验证已在 §7.24 完成**（有vs无`ppi1`径向扩散标准差相差33倍）。 |
| 完整可跑通的参考脚本 | `comsol_scripts/test_cpt_magnetic_force.m`（均匀 Bz 场中电子回旋运动，实测回旋半径 0.58mm vs 理论 `m*v/(qB)`=0.57mm，误差2%；轨迹图是一个漂亮的正圆）。 |

### 7.16 多极杆 (Quadrupole/Hexapole/Octupole) 几何、交替电位与 RF 时变场
| 调用 | 说明 |
|---|---|
| N 根圆柱杆沿方位角均匀排布 | 不用找"阵列/圆形复制"几何特征，直接在 MATLAAB 循环里用三角函数算每根杆的 `pos`：`x=R_center*cos(theta_k)`, `y=R_center*sin(theta_k)`，`theta_k=(k-1)*360/N`（角度用 `[deg]` 单位）——和电子枪倒角工具一样的"显式循环建几何"套路，比找 Array/Copy+Rotate 特征更可控。经典四极杆理想双曲面近似半径比 `r_rod=1.1468*r0`；六极/八极本次只用了近似占位比值（0.55），不是精确工程设计值。 |
| 相邻杆交替 `+V_rf`/`-V_rf` | 偶数 N 才能严格交替；`for k=1:N`，`mod(k,2)==1` 用 `+V_rf`，否则 `-V_rf`，配合 §7.2 的 `Complement` 选择拿真空域（外层大圆柱同样有"重叠域 selresult 污染"问题，见 §7.2/§7.12，不要用它，用杆域取补集）。 |
| **物理验证**：中心电位/场应为0，偏轴电位应按 `r^(N/2)` 幂律增长 | 实测四极(N=4) `V∝r^2`（比值4.00/4.00/9.00，和理论(r2/r1)^2 完全吻合到4位有效数字）、六极(N=6) `V∝r^3`（比值8.28/7.53/3.38，接近理论8/8/3.375，偏差来自用圆杆近似而非精确双曲面电极+粗略半径比）、八极(N=8) `V∝r^4`（比值16.9/5.10，接近理论16/5.06）——**这是检验多极杆几何+交替电位设置对不对的最快方法：算几个不同半径下的 on-axis 电位比值，不吻合幂律就是杆间距/半径比/交替符号设错了，不用等做完粒子追踪才发现。** |
| RF 时变场加到 CPT：方案A（手写表达式，本次实际用的） | 静电场只解一次（用某个单位幅值 `V_rf_solve` 交替加在杆上），CPT 的 `ElectricForce` 用 `E_src='userdef'` + `.set('E', {...})`，表达式直接写 `(V_target/V_rf_solve)*es.Ex*cos(2*pi*f_rf*t)`（`t` 是时间相关 study 里的内置时间变量，可以直接在表达式字符串里引用）——**同一个静电解，换 `V_target` 幅值/`f_rf` 频率完全不用重新解静电场**，适合做扫描。 |
| RF 时变场加到 CPT：方案B（`ElectricForce` 原生振荡模式，本次只探测属性未做完整验证） | `ef1.set('TimeDependenceOfField','TimeHarmonic')`（合法值：`"StationaryOrTimeDependent"`(默认)/`"TimeHarmonic"`/`"Periodic"`）+ `ef1.set('FrequencySpecification','SpecifyFrequency')`（合法值：`"FromSolution"`(默认，需要频域解)/`"SpecifyFrequency"`/`"SpecifyPeriod"`）+ `ef1.set('omega', f_rf)`（默认 `1[MHz]`，恰好是常见RF四极杆频率量级）+ `phi0`（相位，默认0）。**`MagneticForce` 也有一模一样的这组属性**，说明这是 COMSOL CPT 里"给一个已解出的静态场自动乘上正弦时变系数"的通用机制，理论上比手写 `cos(2*pi*f*t)` 表达式更"正规"，但本次没有跑通完整算例，只确认了属性存在和合法取值，留给未来验证。 |
| `ElectricForce` 还有 `SpecifyForceUsing`（合法值 `"ElectricField"`(默认)/`"ElectricPotential"`）+ 对应的 `V_src`/`V` 属性 | 除了给"电场"表达式，也可以直接给"电位"表达式让特征内部做 `-∇V`，用哪个看哪个表达起来更方便（比如想直接引用解出来的标量势 `V` 而不是三个分量 `es.Ex/Ey/Ez` 时更省事）。 |
| 离子（区别于电子）粒子属性设置 | `cpt.feature('pp1').set('mp', '100*1.66054e-27[kg]')`（质量数100的离子，用原子质量单位换算成kg；也可以直接试 `'100[u]'`看是否COMSOL支持原子质量单位token，本次用的是显式kg换算，更保险）+ `.set('Z','1')`（+1价正离子，默认是电子的 `Z=-1`，别忘了改）。 |
| **马蒂厄方程稳定性判据实测验证** | 四极杆(N=4)，r0=4mm，RF频率1MHz，离子100amu/+1价：算出马蒂厄 `q=4*e*V/(m*Omega^2*r0^2)`，q=0.5(理论稳定区)时近轴离子最大偏移中位数仅 0.26*r0（90%分位0.41*r0，全部不超过r0，轨迹图是收敛的利萨如图案）；q=1.2(超过稳定边界q_boundary≈0.908)时最大偏移中位数达到1.02*r0（90%分位1.13*r0，100%超过r0，轨迹图明显发散撞向杆方向）——**四极杆几何+RF场+CPT粒子追踪全链路定量符合教科书马蒂厄稳定性理论，是本次验证里信噪比最干净的一次对比**。 |
| `Release` 用 `MeshBased` 在整个真空域释放时的采样偏差 | 实测四极杆模型里30810个释放点中，只有343个（约1%）落在"距轴0.3*r0以内"的近轴关心区域，其余绝大多数是靠近杆表面/外边界的网格节点（弯曲表面附近网格天然更密）——**做"离子在多极杆中心区域"这类关心近轴动力学的测试，必须在后处理时按初始半径过滤释放点，不能直接对全体释放粒子统计，否则统计量会被大量"本来就在杆表面附近、本来就该发散"的点严重污染**（本次第一次没过滤时误判"92%都超出r0"，过滤后才看出q=0.5确实是干净的稳定解）。 |
| 完整可跑通的参考脚本 | `comsol_scripts/test_multipole_geometry.m`(几何，传入N=4/6/8) + `test_multipole_es.m`(静电场+幂律验证) + `test_quadrupole_stability.m`(RF+CPT稳定性对比，传入Vamp和label)。 |

### 7.17 爱因茨尔透镜 (Einzel Lens)
| 调用/发现 | 说明 |
|---|---|
| 几何 | 3片同轴圆盘（接地-透镜-接地），每片都用"实心圆柱-同轴小圆柱"布尔差集挖出中心通孔（和电子枪阴极/Wehnelt同一套手法），中间片`V_lens`可正可负。参数：`R_disk=10mm, r_hole=3mm, t_disk=1mm, gap=8mm`。 |
| **聚焦强弱只取决于 `KE_beam/|V_lens|` 这个无量纲比值，不取决于绝对值** | 实测 `KE=1000eV,V_lens=-800V`(比值1.25) 和 `KE=5000eV,V_lens=-4000V`(比值同样1.25) 给出**完全相同**的聚焦效果——第一次看到这个结果时容易误判成"没调对参数/仿真有bug"，其实这是静电透镜的基本标度律（拉普拉斯方程线性、轨迹方程只依赖比值）。要看到不同的聚焦效果必须让这个**比值本身**变化（比如固定`V_lens=-4000V`，`KE`从1000→3500→5000eV，比值0.25→0.875→1.25，才会看到明显不同的聚焦強度）。 |
| 反射风险 | 中间片电压幅值必须小于离子/电子的动能（`|V_lens|<KE_beam/e`），否则粒子会在还没到达透镜中心前就被反射回去，根本"透"不过去——设计任何静电透镜前先检查这个不等式。 |
| 完整可跑通的参考脚本 | `test_einzel_lens.m`(几何+静电场) + `test_einzel_cpt.m`(束流聚焦CPT测试，传入KE_eV)。 |

### 7.18 线性离子阱 (Linear Ion Trap, LIT)
| 调用/发现 | 说明 |
|---|---|
| 几何 | 四极RF杆（径向约束，同§7.16手法）+ 两片端盖孔径电极（轴向约束，同爱因茨尔透镜的挖孔圆盘手法），杆和端盖共享同一个真空域（`Complement`选择）。 |
| **同一 component 里两个同类型物理场（两个 `Electrostatics`）的坑：自定义 tag 不是变量命名空间** | 用 `comp1.physics.create('es_rf','Electrostatics',...)` 和 `comp1.physics.create('es_dc','Electrostatics',...)` 建了两个物理场后，在 `mphinterp`/CPT 表达式里写 `'es_rf.Ex'`/`'es_dc.normE'` 全部报 "Undefined variable"。**COMSOL 的变量命名空间不跟着你传的自定义 tag 走，而是按物理场类型+创建顺序自动分配默认前缀**：第一个 `Electrostatics` 永远是 `es`（依赖变量`V`），第二个自动变成 `es2`（依赖变量`V2`），不管 Java API 里的 tag 叫什么。自定义 tag 只在 Java API 层（`comp1.physics('es_rf')`、`study.setEntry('activate','es_rf',false)`）有效。**排查方法：依次探测 `V`/`V2`/`es.Ex`/`es2.Ex` 等候选名，不要直接假设自定义tag可用。** |
| RF+DC 合成力表达式 | `ef1.set('E', {'(Vrf/100)*cos(2*pi*f*t)*es.Ex+(Vdc/100)*es2.Ex', ...})`——RF部分乘时变余弦，DC部分常数，两个独立求解的单位静电场按各自的物理标度系数叠加，同一套"先解单位场、CPT里手写标度表达式"的机制（同§7.16 RF方案A）。 |
| **验证结果：轴向束缚运动是干净的谐振子式往返** | 100amu/+1价离子，轴向初始动能0.5eV（速度982m/s），近中心释放的离子在40us内（对应4个RF周期共40个RF小周期）轨迹图呈现平滑的"下凹抛物线→上凸抛物线"往返运动，转折点在z≈3.5mm和z≈16.7mm之间（端盖分别在z=-3mm和z=22mm，远未触及），**这是本次所有验证里信噪比最干净的一次结果**：束缚离子的运动被完整、平滑地限制在阱内，从未接近电极。 |
| 完整可跑通的参考脚本 | `test_lit_geometry_es.m`(几何+RF/DC双静电场) + `test_lit_cpt.m`(轴向束缚CPT验证)，模型存于 `comsol_models/LinearIonTrap.mph`。 |

### 7.19 飞行时间分析器 (TOF) + 反射器 (Reflectron)
| 调用/发现 | 说明 |
|---|---|
| 几何 | 源极盘(`V_accel`) → 挖孔引出栅极(接地) → 漂移管(真空) → 实心反射镜电极(`V_mirror`，无通孔，离子理论上应在到达前被减速反弹)。和电子枪/爱因茨尔透镜/LIT 同一套挖孔圆盘手法。 |
| **⚠️漂移管必须有接地导体壁，否则远端电极的场会"漏"穿整个漂移区** | 第一次建模时漂移管外侧圆柱侧壁留空（默认零电荷/开放边界），结果on-axis电位从引出栅极附近的~0V一路爬升到接近反射镜电极的~1200V（反射镜电压），**"漂移区"完全不是场自由的**——因为侧壁没有接地导体屏蔽，拉普拉斯方程会让远处反射镜的电位在整个空间平滑内插，没有"局部"这回事。修复：把漂移管真空域"除了3个电极盘以外的所有边界"（`sel_vac`的Adjacent边界集合减去3个电极盘各自的Adjacent边界集合，在MATLAB里用`setdiff`做集合差，再建`Explicit`边界选择）显式接地(`V=0`)，之后漂移区中点电位降到0.002V（几乎精确为零），只在两端电极附近有合理的场穿透。**这是一条通用规律：任何"应该场自由"的区域，光是不设边界条件不够，必须有接地导体真正屏蔽远处电极。** |
| **组件级别的 Union/Difference 选择类型不可靠，改用 MATLAB 端 `setdiff`** | 试过 `comp1.selection.create(tag,'Union')`+`.set('input',{...})` 和 `'Difference'`+`.set('input2',{...})`，前者报"Selection on wrong geometric entity level"（需要先显式 `.geom('geom1',2)` 指定实体维度，同§2.3网格Size特征的坑）、修复后又报"Unknown property: input"（`Difference`类型的第二输入属性名不是`input2`，具体正确名字未确认）。**最终改用已验证可靠的组合**：`Adjacent`选择拿到全部边界的实体ID数组，用 MATLAB `setdiff(allIDs, knownIDs)` 在客户端算出差集，再用 `Explicit` 选择类型（`.geom('geom1',2)` + `.set(idArray)`）建立最终选择——绕开所有未验证的组合选择类型，只依赖`Adjacent`/`Explicit`这两个已反复验证过的类型。 |
| **平板电极的离轴离子径向散焦是真实物理，不是bug** | 沿+z方向释放、初始位置略微偏离轴心（r0≈0.9mm）的离子，在飞行~108mm接近反射镜时径向坐标从r≈0.9mm加速增长到恰好r=10mm（撞上漂移管侧壁），且径向增长在接近反射镜镜面时明显加速——这是**有限半径平板电极边缘场散焦**的真实效应（真实反射式TOF仪器也有同样问题，这正是实际仪器常用弯曲反射镜面或多层网格梯度而不是单一平板镜的原因）。诊断方法：检查粒子"冻结"瞬间的速度是否仍在增长（若仍在加速说明是撞墙冻结，不是物理转折点减速到零）+ 检查径向坐标r是否恰好等于边界半径（`r=9.999996mm`几乎精确等于`R_tube=10mm`，实锤撞墙）。 |
| **质量分离定量验证** | 100amu vs 200amu离子，同样`V_accel=1000V`加速，测量到达z=60mm（漂移区安全中点，场穿透可忽略）的时间：1.57us vs 2.21us，比值1.408，理论`sqrt(200/100)=sqrt(2)=1.414`，误差0.5%——干净验证了TOF核心原理`t∝sqrt(m)`。 |
| `Inlet`的`v0`哪怕想表示"标量速度"也必须给三分量向量 | `inl1.set('v0','0[m/s]')` 报错"A vector of length 3 expected"，必须写成 `inl1.set('v0',{'0','0','v_extra'})`——即使方向已经由边界法向决定，`Expression`模式下`v0`的语义仍然是完整速度矢量而非标量速度。 |
| `Inlet`选择整个电极盘边界（无通孔）时的坑 | 电极盘的"Adjacent边界"包含前面+后面+侧面**全部**表面，若不精确限定到"朝向漂移管的那一面"，`Inlet`可能从背面/侧面发射粒子（背离漂移管方向），离子几乎立刻冻结在极靠近释放点的位置（观测到`z_max≈0.4mm`）。**更省事的替代方案：改用`Release`(域级别)配合显式速度矢量，彻底绕开"到底是哪个面"的歧义**（本次采用的修复方式）。 |
| 参考脚本(已删除，仅保留本节的经验记录) | 原`test_tof_reflectron_es.m`/`test_tof_cpt.m`及对应的`TOFReflectron*.mph`是最早期的单一平板反射镜验证测试——按用户要求"只保留最新最合理的reflectron模型"已删除，本节记录的物理教训(接地漂移管壁、平板边缘径向散焦、原生轨迹绘制)仍然有效，被后续§7.28的环栈反射镜设计所继承和取代。 |

### 7.20 静电扇形场能量分析器 (ESA)
| 调用/发现 | 说明 |
|---|---|
| 几何 | 同轴圆柱电容器：内层实心导体(r<R1=40mm)接地，外层薄壳导体(R2=50mm~R2o=52mm)加正电压，中间环形真空隙(R1~R2)供离子飞行。**关键坑：内外电极务必被一个更大的"整体真空圆柱"完全包住**（本次第一次漏加，导致`Ndomains=2`且`Complement`选择解出0个域——环形间隙压根没被划分成一个域，因为没有任何几何体覆盖那块空间）。 |
| **设计电压公式（同轴柱形电容器精确解，非平行板近似）** | `E(r)=V0/(r*ln(R2/R1))`（不是`E=V0/d`平行板近似——间隙10mm相对半径45mm不算特别薄，用精确公式更准）。给定设计离子（100amu/+1价/1000eV）在`R0=45mm`做圆周运动需要的向心场，反解出`V0≈446.3V`。 |
| **FEM场与解析式验证：4位有效数字吻合** | 在`r=41/43/45/47/49mm`处比较`es.normE`(FEM)与解析式`V0/(r*ln(R2/R1))`，比值全部落在0.9998~1.0002之间——干净确认了COMSOL在同轴柱形几何里求出的确实是精确的`1/r`径向场，不是近似。 |
| **能量选择性（ESA的定义性特征）定量验证** | 设计能量(1000eV)离子稳定运行在r=45.6~45.76mm之间（紧贴R0=45mm，未碰任何电极）；能量偏高30%(1300eV)的离子径向漂移，最终恰好在`r=50.0000mm`（精确等于外电极半径R2）处撞墙——**ESA按能量筛选离子、与质量无关**，这是它和磁扇形场（按`sqrt(m/z)`筛选）的本质区别。 |
| `'h'` 是保留的COMSOL全局变量名 | 用 `p.set('h','10[mm]')` 定义自己的圆柱高度参数，求解时报"Duplicate parameter/variable name. Variable: h. Global scope"——`h`是COMSOL内部保留符号（推测和网格尺寸/普朗克常数等全局量有关），自定义参数必须避开这个名字（改成`h_cyl`即可）。 |
| 完整可跑通的参考脚本 | `test_esa.m`(几何+静电场+CPT一体化，传入KE_eV和label测试不同能量下的径向行为，自动存轨迹图 `comsol_results/esa_trajectory_<label>.png`，含R1/R2虚线圆参考)，模型存于 `comsol_models/ESA.mph`（若未显式save则仅内存中）。 |

### 7.21 磁扇形场质谱仪 (Magnetic Sector)
| 调用/发现 | 说明 |
|---|---|
| 复用已验证的CPT `MagneticForce`回旋运动机制（§7.15/§8），改用质谱仪惯例：固定加速动能KE、不同质量算不同速度 | `v=sqrt(2*KE/m)`，回旋半径`r=m*v/(qB)=sqrt(2*m*KE)/(qB)`，对固定KE和B，`r∝sqrt(mass)`——这是磁扇形场质量分离的核心原理（和ESA按能量筛选、与质量无关正好互补）。 |
| **⚠️`Release`(MeshBased,整个域撒点)测回旋运动时，必须保证"整个圆轨道直径"远小于域尺寸，且与释放点在域内哪里无关** | 第一次用`domain半径100mm`测`r_theory=32mm`（直径64mm）的轨道，随手挑了"粒子1"来分析，测出的"直径"恰好是理论值的**精确一半**——不是随机误差，是因为MeshBased撒点撒满整个域，挑到的那个粒子起始点离边界太近，它自己的圆轨道还没转完就撞墙冻结（径向"清空"不够）。**排查关键信号：比值恰好是0.5这种"干净的分数"而不是随机噈声，几乎总意味着轨迹被边界截断，不是物理量本身有误差**。修复：过滤只挑选择"离域中心足够近"（如 `|x0|,|y0| < 15mm`）的释放点。但当换成更大质量（`r_theory=55.76mm`，直径111.5mm）时，**即使离中心15mm以内的释放点仍然撞墙**——因为轨道自身直径(111.5mm)已经超过或接近域半径(100mm)，无论从哪里释放，轨道最远点离域中心的距离最多可达`2*r_gyro`，必须保证`2*r_gyro`明显小于域半径本身，和释放点过滤是两个独立的必要条件，都要满足。 |
| **定量验证：`r∝sqrt(mass)`** | `50amu`理论/实测半径均为`32.19mm`（比值1.0001），`150amu`理论/实测均为`55.76mm`（比值1.0001）；两者比值`55.76/32.19=1.7321`，理论`sqrt(150/50)=sqrt(3)=1.7321`——精确吻合5位有效数字。 |
| 完整可跑通的参考脚本 | `test_magnetic_sector.m`(传入mass_amu, KE_eV, label；域半径200mm、B=1T为本次选定的量级，实测按需放大以容纳更大质量/更弱场对应的更大轨道，自动存轨迹图 `comsol_results/magsector_orbit_<label>.png`)。 |
| **本节所有CPT类测试脚本约定：都必须存轨迹图** | 检查发现早期几个组件测试脚本（ESA/磁扇形场/TOF）漏加了轨迹可视化（只打印数值结果），后来统一补上——`comsol_results/`目录下每个CPT测试都应该有一张对应的轨迹图（`figure('Visible','off')`+`print(...,'-dpng','-r150')`），不要只满足于数值验证，图像能立刻看出轨迹是否符合预期形状（圆/直线/散焦/往返），比单纯看数字更容易发现问题。 |
| **⚠️外部MATLAB画的PNG轨迹图 ≠ .mph文件里能看到轨迹** | 本次做完全部组件测试后，用户直接打开 `LinearIonTrap.mph`/`Multipole4.mph` 发现 Results 树里根本没有粒子轨迹——因为所有脚本的CPT部分全程只调用了 `mphparticle`+MATLAB `plot`/`print` 在客户端画图存PNG，**从未调用 `model.result.create(...,'PlotGroup3D')` 建立COMSOL原生结果节点，也从未调用 `model.save(...)` 把CPT物理场/study/solution存回磁盘**——用户在COMSOL Desktop里打开的.mph文件只有最初(纯静电场阶段)的状态。正确做法（已给全部CPT脚本补上）：`pg1=model.result.create('pg_traj','PlotGroup3D'); pg1.set('data','pdset1'); pg1.create('trj1','ParticleTrajectories'); pg1.run;` 之后再 `model.save(path)`——这样COMSOL Desktop打开时Results树里就有原生"3D绘图组>粒子轨迹"可以直接看、转、导出动画。**同一个源模型被多个测试用例(不同质量/能量/label)复用时，存盘路径要按label区分文件名（如`TOFReflectron_CPT_M100.mph`），否则后一次运行会静默覆盖前一次的CPT结果。**⚠️注意生成的.mph文件可能非常大（本次几万粒子×几十/百个时间步的多极杆/爱因茨尔透镜CPT模型存盘后单个文件可达约600MB），属于正常现象（存的是完整粒子轨迹时序数据），不是bug。 |
| **⚠️原生轨迹图太多太杂看不清（LIT/多极杆尤其明显）：正确修复是限制"释放范围"，不是事后过滤** | 全域`MeshBased`释放（如`sel_vac`整个真空域）会产生数千到数万个粒子，其中绝大多数远离感兴趣区域（撞墙/发散），原生 `ParticleTrajectories` 图会显得极其杂乱。**尝试过的、不work的方案**：①`trj1.create('filt1','Filter')` / `pg1.create('filt2','Filter')`（想在Plot Group/Trajectory特征下建过滤子特征）→ 报"Operation cannot be created in this context"，这两类结果节点根本不支持子特征叫`Filter`；②`model.result.dataset.create('filt_ds','Filter')`（数据集层面确实存在这个类型，属性含`data`/`expr`/`lowerexpr`/`upperexpr`/`level`，`expr`默认值恰好是`qr0`——证实`qr0`就是COMSOL内置的"粒子释放时刻的径向位置"变量，命名规律是`q<坐标>0`）→ 建立成功，但把它接到 `ParticleTrajectories` 的`data`属性上时报"Operation cannot be performed on dataset filt ds (Filter)"，说明`ParticleTrajectories`直接拒绝`Filter`类型数据集做数据源；③`comp1.selection.create(tag,'Ball')`（尝试用坐标定义的球形选择限制释放范围）→ 能建立且能求出实体数，但`Ball`（以及一般的域级别选择）只能整颗整颗地"挑选域"，不能从一个大域里切出一个空间子区域，所以对`MeshBased`释放的采样范围毫无实际限制作用。**真正有效的做法**：直接在几何里加一个小圆柱体`relvol`（专门作为释放子区域，比如LIT里`r<1mm, z∈[8,12]mm`，多极杆里`r<0.2*r0`、只取杆长中段4mm），设`selresult='on'`让COMSOL自动生成`geom1_relvol_dom`具名选择，让几何自动union/imprint把真空域拆成"`relvol`+其余真空"两个域（`Complement`真空选择因此从1个域变成2个域，需要更新校验逻辑）；CPT物理场(`cpt`/`ElectricForce`)仍然选整个`sel_vac`（让粒子释放后能自由运动/发散），**只有`Release`特征的`.selection`改成`geom1_relvol_dom`**——这样从根本上限制了"哪些粒子会被求解/追踪"，而不是求解完所有粒子后再筛选着色/隐藏，图像天然干净，粒子数也从数万降到几百到两千量级。配合在`relvol`域上加一个局部粗化的`mesh1.feature.create('sz_relvol','Size')`(`.selection.named('geom1_relvol_dom')`+`hauto=9`)可以进一步把粒子数砍下来（本次四极杆从6508→1326）。**注意：改几何后原本`if vac_n~=1 error(...)`之类的域数校验要同步改成2，且如果同一个.mph文件之前跑过旧版本脚本（比如`sel_vac`已存在），必须重新从`ModelUtil.create`整个重建，不能在旧模型上直接追加，否则会报"An object with the given name already exists"（tag冲突）。** |
| **`relvol`释放子域推广到全部CPT组件后的两个新坑** | ①**`relvol`如果恰好落在两个不同电位电极之间的间隙里（比如TOF加速间隙、ESA环形电容间隙），它自己的边界是纯内部边界（两侧都是`sel_vac`），如果后续代码用"`sel_vac`的`Adjacent`边界减去电极边界"这种方式去找"应该接地的杂散边界"，会把`relvol`自己的内部边界也误算进去，导致在加速场正中间强行钉一个`V=0`，直接破坏原本平滑变化的加速场——必须显式再算一次`Adjacent(geom1_relvol_dom)`并把这部分也从"待接地边界"里减掉（本次在TOF模型上踩到并修复）**；②对均匀场类模型（如磁扇形场，只有一个空场域、没有任何电极），加`relvol`前物理场的`.selection`往往靠"域只有一个所以隐式全选"生效，一旦引入第二个域(`relvol`)必须把`cpt.selection`/力特征的`.selection`都显式改成`.all`，不能再依赖隐式默认。 |
| **多极杆RF约束推广到六极/八极：物理结论和四极不同，这是真实物理不是bug** | 四极杆有严格的马蒂厄稳定性（线性回复力，q<0.908尖锐边界），六极/八极的回复力是非线性的（分别∝r^2/r^3），**没有同样干净的稳定性边界**，实际用途更接近"离子导管"（宽松透过，牺牲质量选择性换取更低损耗）而非精密质量滤波器。本次用相同RF电压(82V低/196V高，1MHz)测试三者：四极在196V下100%超出r0(严格失稳)；六极在196V下呈现"中心core仍收敛但28%的近轴粒子发散"的混合状态(比四极软得多的过渡)；八极在196V下0%超出r0(近轴回复力比六极更弱，反而更抗失稳，符合"高阶极杆离轴势阱更宽更平"的真实物理)——**这组对比本身就是六极/八极作为离子导管而非质量滤波器的定量证据，不需要也不应该套用马蒂厄q参数去"验证"六极/八极，那是概念误用**。 |
| **画图规范：标题必须包含组件名+粒子性质+关键场参数，坐标轴必须标单位** | 早期版本的标题过于简略（如"Cyclotron trajectory in uniform Bz"、"ESA trajectory: %s"），只有拿到脚本源码才知道具体是什么粒子、什么参数——后来统一改为多行标题，第一行组件名+测试用例名，第二行具体物理参数（质量/电荷/动能、RF电压频率、磁场强度等），例如`{'Linear Ion Trap: axial position vs time, confined near-center ions', 'particle: 100amu +1 ion, KE_{axial}=0.5 eV, RF: 82V @ 1MHz, DC end-cap: 5V'}`（MATLAB `title`支持cell数组=多行）。**原生COMSOL结果图默认标题是"Particle trajectories"这种通用文本，需要显式`pg1.set('titletype','manual'); pg1.set('title', '<自定义字符串>')`才能覆盖成同样有信息量的标题**（`titletype`合法值含`auto`/`manual`，默认`auto`）。 |
| **⚠️模型树节点命名规范：每个 feature 都要显式 `.label(...)`，不能只满足于默认名/tag** | 默认情况下，COMSOL 用类型+序号自动生成显示名（如"Cylinder 1"/"Electrostatics"/"3D Plot Group 1"/"Particle Trajectories 1"），在 COMSOL Desktop 的 Model Builder 树里完全看不出这是"哪个电极"/"哪个测试用例"——必须靠打开脚本源码才知道。**`.label('自定义字符串')` 是几乎所有 Java API 对象（geometry feature、selection、material、physics 接口及其子特征、mesh 及其子特征、study 及其子步骤、solver sequence、result dataset、plot group 及其子特征）都支持的方法**，且是同一个方法名同时充当 getter（无参数调用返回 `String`）和 setter（传入字符串即设置），**跟 tag 完全独立**（tag 仍然是几何/API访问用的短标识符不受影响）。实测验证：设置后无论是当前会话内读取还是 `model.save()` 存盘后重新 `ModelUtil.load()` 都能正确取回，说明标签会持久化进 .mph 文件。**本次做法**：对质谱仪全部6类组件脚本（LIT/四六八极杆/Einzel透镜/TOF/ESA/磁扇形场/回旋运动）逐一加上有意义的 `.label(...)`——geometry feature 标注"是什么电极+关键参数"（如"RF rod 1 (theta=0 deg, alternating +/-V_rf)"）、selection 标注"这是哪个边界/哪个域的选择"、physics/study/solution 标注"哪个组件+哪个测试用例"、result plot group/trajectory 标注"哪个组件+哪个粒子群"，每加完一批立即重新求解验证物理结果和之前完全一致（label 是纯显示层修改，不应该也没有影响任何物理量）。**这是一个应该在所有后续脚本里从一开始就养成的习惯，而不是事后补丁**——写 `geom1.feature.create(tag, type)` 之后顺手加一行 `.label(...)`，成本几乎为零。 |

### 7.22 CPT 背景气体碰撞 (`Collisions` 特征，适用于碰撞池/CID建模)
| 调用/发现 | 说明 |
|---|---|
| `cpt.create('coll1','Collisions',3)` | **CPT 原生支持背景气体碰撞建模**，猜测的其它名字（`GasCollisions`/`BackgroundGas`/`ElasticCollision`/`ChargeExchange`/`MonteCarloCollisions`/`GasDrag`等）全部不存在，正确名字就是朴素的 `'Collisions'`。 |
| 关键属性与默认值 | `Nd`(背景气体数密度，默认`1E20[1/m^3]`，对应低压碰撞室量级) / `mg`(背景气体分子摩尔质量，默认`0.04[kg/mol]`——**恰好是氩气Ar的摩尔质量**，和真实CID碰撞气体选择一致，说明COMSOL默认值是照着真实碰撞池场景设计的) / `T`(背景气体温度，默认`293.15[K]`室温) / `T_src`/`u_src`(温度/漂移速度来源，默认`'userdef'`)。 |
| `CollisionDetection` 合法值 | `"AtTimeStepsTakenBySolver"`(默认) / `"NullCollisionMethodColdGasApproximation"`——后者是等离子体/粒子物理里经典的"零碰撞法"(Null Collision Method)蒙特卡洛技巧，用于高效模拟和背景气体的随机碰撞而不需要极小时间步长，"ColdGasApproximation"暗示假设背景气体分子相对离子几乎静止（简化的弹性/非弹性截面处理）。 |
| **⚠️关键坑：`Collisions` 特征本身只是个容器，不加子特征(Attribute)碰撞完全不生效** | 第一次搭碰撞池模型时，只创建了 `coll1 = cpt.create('coll1','Collisions',3)` 并设置 `Nd`/`T`/`CollisionDetection`，结果**从 `Nd=1e20` 一路测到 `Nd=1e28`（整整8个数量级，接近固体密度），轨迹逐点比较全部完全一致（差异仅 `1e-12mm` 浮点噪声）**——碰撞对轨迹literally零影响。排查过程中依次验证过`isActive()`(全部=1，特征未被禁用)、`StudyStep`绑定(见下一条)、`CollisionDetection`两种模式切换、`tstepsbdf`严格步长、`CountAllCollisions`开关，**全部无效**。最终在COMSOL自带的Application Library示例`Particle_Tracing_Module/Charged_Particle_Tracing/ion_drift_velocity_benchmark`（本机路径`D:\COMSOL 6.4\COMSOL64\Multiphysics\doc\help\wtpwebapps\ROOT\doc\com.comsol.help.models.particle.ion_drift_velocity_benchmark\`下有PDF）里找到根因：**`Collisions` 域特征只负责`Nd`/`T`/碰撞检测算法这些"容器级"设置，真正定义"发生哪种碰撞、碰撞截面σ多大"的是挂在它下面的 Attribute 子特征（`Elastic`弹性碰撞、`Resonant Charge Exchange`共振电荷交换等），不加任何Attribute子特征等于截面σ隐式为零，碰撞频率`ν=Nd·σ·v`自然恒为零，不管`Nd`多大都没用。** |
| **正确的最小可用配方** | `elastic1 = coll1.create('elastic1','Elastic'); elastic1.set('CountCollisions', true);`——`Elastic`特征默认自带一个物理上合理的**常数截面`xsec=3E-19[m^2]`**（真实离子-中性原子弹性碰撞截面量级），`NumberDensitySpecification`/`MolarMassSpecification` 默认`'FromParent'`（自动继承父`Collisions`节点的`Nd`/`mg`，不用重复设置）。**只要建了这个子特征，哪怕什么参数都不改，碰撞立刻就会生效**（本次实测：加上`elastic1`后，同样`Nd=1e20`，100%粒子被径向扩散撞墙损失，vs加之前0%——纯粹这一个子特征的有无就是"碰撞完全不生效"和"碰撞100%生效"的开关）。 |
| **`StudyStep` 属性同样需要显式绑定到实际求解的时间相关study**（和LIT里`es_rf`/`es_dc`那次踩坑同一类问题） | `pp1`(Particle Properties)、`coll1`、`elastic1` 创建时默认都带一个 `StudyStep` 属性（本次发现值默认是`'std1/stat1'`，即模型里先建的静态study），如果后建的时间相关study（`std2/time1`）不显式绑定，这几个特征可能仍然被当作"只对`std1`生效"——本次修复时对三者都显式加了 `.set('StudyStep','std2/time1')`（必须在`std2.create('time1',...)`**之后**才能设置，否则报"Invalid parameter value"）。**实测上这条本身没有单独解出问题（真正的根因是缺 Attribute 子特征），但这是一个真实存在、容易被忽略的属性，建议凡是先建了多个 study 的模型都显式设置一遍，避免叠加坑。** |
| **⚠️碰撞计数变量的正确取值方式：只有 `mphparticle` 的 `'expr'` 选项能用** | 碰撞计数变量命名规律和COMSOL官方示例一致：`<physics_tag>.<collisions_tag>.<attribute_tag>.Nc`（本例`cpt.coll1.elastic1.Nc`）——但**`mphinterp` 直接报错"mphinterp does not support particle data sets"（完全不支持粒子数据集）；`mpheval(model,'cpt.coll1.elastic1.Nc','dataset','pdset1',...)` 报"Undefined variable"，即使表达式本身完全正确也一样失败**（怀疑`mpheval`对粒子数据集的非空间标量导出量支持有缺陷或需要额外语法，未查明）。**唯一验证有效的方法**：`mphparticle(model,'dataset','pdset1','expr',{'cpt.coll1.elastic1.Nc'})`，返回结构体里会多出一个 `d1` 字段（`[nTimes x nParticles]`，和`p`/`v`同样的时间×粒子排列），取最后一行即每个粒子在`t_end`时刻的累计碰撞数。**`Nc` 在粒子被吸收(撞墙/`Freeze`)后会保持不变（冻结在吸收时刻的值），不是持续累加到`t_end`**，所以"平均碰撞数"衡量的是"粒子存活/被吸收前经历的碰撞数"，不是"如果活满全程会经历的碰撞数"。 |
| **验证结果：碰撞率和离子损失率都随气体密度单调、物理自洽地变化** | 碰撞池：直管`r=5mm, L=100mm`，两端弱推场electrode(10V→0V，仅提供微弱轴向牵引，无径向约束)，100amu+1价离子，KE=10eV(v=4393m/s)，`Elastic`默认截面`3e-19m^2`。扫描`Nd`：`1e18/m^3`→透过率96.9%/损失3.1%/平均碰撞数0.031；`1e19/m^3`→透过率81.2%/损失18.8%/平均碰撞数0.219；`1e20/m^3`→透过率0%/损失100%/平均碰撞数1.406——**透过率随密度单调下降、损失率单调上升、平均碰撞数随密度近似线性增长（3个密度点跨2个数量级，碰撞数跨约45倍，基本符合`ν∝Nd`的动理论预期）**，且实测碰撞数系统性低于"整个200us都在气体里"的粗略理论估计（`ν_theory=Nd·σ·v_beam`），原因是**多数粒子在完整200us跑完之前就已经被径向扩散撞墙吸收，`Nc`提前冻结**，不是碰撞机制本身有误——这组结果本身就是"无径向约束的碰撞池会因碰撞导致的径向扩散而损失大量离子"的定量证明，也解释了为什么真实碰撞池(如三重四极杆质谱的Q2)几乎都会叠加RF径向约束而不是用裸漂移管。 |
| 完整可跑通的参考脚本 | `test_collision_cell.m`(碰撞池几何+ES+CPT一体化，传入`Nd_val`/`KE_eV`/`label`，自动算并对比动理论碰撞频率，存原生轨迹图)；`test_collision_cell_gpu_comparison.m`(同一场景的CPU/GPU求解器对比，见§5)。模型存于 `comsol_models/CollisionCell_<label>.mph`。 |

### 7.23 Wien 滤波器 (交叉 E×B 速度选择器)
| 调用/发现 | 说明 |
|---|---|
| 物理原理 | 均匀 E 场和均匀 B 场正交（都垂直于束流方向z），受力平衡条件 `qE=qvB` 给出 `v=E/B`——**只和速度有关，和质量、电荷完全无关**，这是Wien滤波器区别于ESA(只筛能量,和质量无关)和磁扇形场(固定能量下按质量筛选)的本质特征。本次是本会话首次**同时**用`ElectricForce`+`MagneticForce`且方向正交（此前电场磁场都是分开测的）。 |
| 建模方式 | 沿用回旋运动/磁扇形场测试的简化手法——不解真实静电场，`ef1.set('E_src','userdef')` + `ef1.set('E',{E0,'0','0'})`（用户定义uniform E），`mf1.set('B_src','userdef')` + `mf1.set('B',{'0',B0,'0'})`，二者叠加在同一个`cpt`物理场下即可，不需要额外的multiphysics耦合。 |
| **⚠️坑：偏转量必须相对释放起始位置算，不能直接看终点绝对坐标** | 用`MeshBased`在小`relvol`里撒点释放，粒子在x/y方向会有随机的初始小偏移（本次约`-0.16mm`），而均匀交叉场对x/y方向没有任何回复力——这个初始偏移会原封不动地叠加在真正的物理偏转量上。第一次直接看`x_end`，"共振速度"下的结果是`-0.1648mm`（看起来没打到0，容易误判成物理没调对），改成算`x_end-x_start`之后才发现真正的物理偏转量精确到`-2.8e-8mm`（纯浮点噪声，即完美直线通过）。 |
| **验证结果：定量符合Wien滤波器全部预期** | 设计点：100amu+1价离子，KE=1000eV(v_resonant=4.393e4 m/s)，B0=0.01T，E0=439.28V/m。①**共振速度**(v/v_resonant=1.000)：偏转≈0(-2.8e-8mm)；②**快20%**(v/v_resonant=1.200, KE=1440eV)：偏转`-0.0361mm`，和手算理论值`-0.038mm`吻合(~5%误差)；③**慢20%**(v/v_resonant=0.800, KE=640eV)：偏转`+0.0816mm`，**符号和"快"的情形相反**(电场占优 vs 磁场占优，符合物理预期)；④**质量无关性验证**：200amu离子在SAME速度v_resonant下(KE=2000eV，因为固定v时KE∝m)，偏转同样≈0(-1.4e-8mm)，**证明选择条件确实只取决于速度，和质量无关**。 |
| 完整可跑通的参考脚本 | `test_wien_filter.m`(传入mass_amu/KE_eV/label，B0/E0内部按100amu+1000eV设计点固定)。模型存于 `comsol_models/WienFilter_<label>.mph`。 |

### 7.24 ParticleParticleInteraction 库仑排斥/空间电荷效应实测验证
| 调用/发现 | 说明 |
|---|---|
| 此前状态 | §7.15只探测过`InteractionForce`属性名和合法值(`"Coulomb"`默认/`"LinearElastic"`/`"LennardJones"`/`"UserDefined"`)，**没有做过真正的多粒子收敛/效应验证**，本次补上。 |
| **真实离子间库仑力在常规质谱仪时间尺度/离子间距下极弱，需要刻意选参数才能在合理仿真时长内看到效果** | 手算：两个相距0.2mm的+1价离子，库仑力对应加速度约`3.5e4 m/s^2`，在1us量级的常规束流渡越时间内位移只有`~1.7e-5mm`，完全不可见。**本次做法**：故意用极低动能(`KE=1eV`，100amu离子v=1389m/s，给足够长的渡越时间`~72us`)+极紧密的初始离子团(`relvol`半径仅`0.05mm`)，把渡越时间拉长、初始间距压缩，使原本微弱的库仑力有足够时间积分成看得见的位移——**这是为了展示机制本身特意选的参数，不代表任何具体仪器的真实束流密度**。 |
| **验证结果：有无`ParticleParticleInteraction`径向扩散相差一个数量级以上** | 12个100amu+1价离子从`r0`标准差`0.0089mm`的紧密团released：**不加`ppi1`**：末端(z=100mm)径向扩散标准差和初始完全相同(`0.0089mm`，纯弹道运动，无横向力)；**加`ppi1`**(`InteractionForce='Coulomb'`, `.selection.all`)：末端径向扩散标准差涨到`0.2916mm`(**33倍**)，最大半径从`0.04mm`涨到`1.117mm`(**28倍**)——库仑排斥导致的束流展宽效应清晰、干净、量级合理。 |
| 完整可跑通的参考脚本 | `test_space_charge.m`(传入`useInteraction`布尔值和`label`，对比有无库仑相互作用的径向扩散统计)。模型存于 `comsol_models/SpaceCharge_<label>.mph`。 |

### 7.25 Resonant Charge Exchange (共振电荷交换) 碰撞类型
| 调用/发现 | 说明 |
|---|---|
| 物理原理 | 和`Elastic`(弹性碰撞，只交换动量，动能守恒，方向随机化)不同，共振电荷交换是**离子把电荷"转移"给本来静止的中性背景气体原子**，产生一个飞走的快中性原子(CPT不追踪，因为已经不带电)和一个**继承背景气体近乎静止速度的"新"离子**——因此电荷交换事件的特征信号是**速度几乎瞬间掉到接近零**，而不是Elastic碰撞那种渐进式的方向随机游走。 |
| 建模方式 | 和`Elastic`完全同一套模式——都是挂在`Collisions`域特征下的Attribute子特征：`cex1 = coll1.create('cex1','ResonantChargeExchange')`；`cex1.set('CountCollisions', true)`；`cex1.set('StudyStep','std2/time1')`(和`Elastic`一样需要显式绑定study step，见§7.22)。默认截面同样是COMSOL内置的合理常数值。 |
| **碰撞计数变量命名和`Elastic`完全类比** | `cpt.coll1.cex1.Nc`(把`elastic1`换成`cex1`)，用`mphparticle(...,'expr',{'cpt.coll1.cex1.Nc'})`同样的方式提取(§7.22已确认`mpheval`/`mphinterp`对粒子数据集的这类标量导出量都不可用)。**这次直接一遍就取到了正确数据**(用`mphparticle`+`expr`选项从一开始就用对方法，没有再踩§7.22那次的坑)。 |
| **验证结果：清晰观察到"速度突降"这一区别于`Elastic`的特征信号** | 碰撞池(同§7.22几何)，`Nd=1e19/m^3`，100amu+1价离子，KE=10eV：32个粒子平均经历`0.281`次电荷交换事件，**8/32(25%)粒子在速度-时间曲线上出现单步>90%的速度骤降**，之后在弱推场作用下从近乎静止重新加速——轨迹图上清晰可见几条曲线有一个尖锐的"V形"速度低谷，其余曲线全程平滑无骤降(全程未发生电荷交换)，和`Elastic`碰撞测试(§7.22)的渐进式散射轨迹形成鲜明对比，两种碰撞类型的物理区别在仿真结果里得到直观、干净的体现。 |
| 完整可跑通的参考脚本 | `test_resonant_charge_exchange.m`(传入`Nd_val`/`KE_eV`/`label`)。模型存于 `comsol_models/CEX_<label>.mph`。 |

### 7.26 FTICR/ICR 离子回旋共振池 (磁场约束+电场约束组合)
| 调用/发现 | 说明 |
|---|---|
| 组件构成 | 真实FTICR池 = 均匀轴向磁场(回旋运动提供径向约束，机制同§7.14/§7.21回旋运动和磁扇形场测试) + 两端DC捕集电极(轴向约束，机制同LIT的端盖电极，§7.18)——**本次是本会话第一次把这两个分别验证过的机制真正组合在同一个模型里**，而不是分开测。 |
| **⚠️关键坑：两个端盖电极给同一个正电压、没有任何接地参考，导致轴向电位完全没有梯度** | 第一次搭建时两端盖都设`V0='V_trap'`(同一个值)，中间/侧壁没有设置任何边界条件——求解后on-axis电位在整个40mm长度上**恒为5.0000V**(完全没有变化)，意味着轴向电场处处为零，"轴向捕集"根本不存在，尽管几何和粒子追踪都"成功"跑完了。**根因和TOF漂移管接地那次(§7.19)完全同一类**：拉普拉斯方程只有两个"电位相同"的边界条件时解是平凡常数，必须有一个接地参考才能形成真实的电位梯度。**修复**：把ICR池的圆柱侧壁(而不是端盖)显式接地`V=0`——用同一套"`Adjacent(sel_vac)`全部边界 减去 端盖边界 减去 relvol自身内部边界"的MATLAB `setdiff`技术(§7.19已验证)找到侧壁边界。修复后on-axis电位呈现正确的对称势阱形状(两端`~4.84V`，中心`~1.39V`)，轴向运动才开始真正表现出往返束缚。 |
| **验证结果1：径向(回旋)约束和轴向(DC)约束分别独立工作正常** | 100amu+1价离子，径向初动能1eV(v_perp=1389m/s)，轴向初动能0.5eV(v_axial=982m/s)，Bz=0.3T(理论回旋半径4.80mm，周期21.71us)，V_trap=5V。轴向z范围全程保持在`12.58~27.98mm`之间(端盖分别在0/40mm)，**从未越界**，确认DC轴向捕集有效；径向运动始终被限制在r0=20mm的池体半径以内，从未撞壁，确认回旋约束有效。 |
| **验证结果2：组合运动出现真实的"磁控漂移"(magnetron drift)现象，不是bug** | 用"x方向跨度/2"测回旋半径，发现随着采样时间窗口变长，测出的"半径"从`2.57mm`(半个周期，采样不足)一路涨到`9.64mm`(整个100us仿真)，即使把采样精度提到每周期100个点、只看第一个回旋周期也仍然测出`7.81mm`(比理论值4.80mm大63%)，**不是数值误差或采样不足**——这其实是真实的、教科书记载的Penning阱/ICR阱物理现象：捕集电场并非纯轴向(径向也有分量)，和轴向磁场叠加会产生缓慢的**E×B磁控漂移**，使回旋轨道的引导中心随时间缓慢进动，本次恰好因为回旋周期(21.71us)和轴向束缚振荡周期(从轨迹图读约50us)量级相当，两种运动强耦合，在top-view投影图上呈现出清晰的"花瓣/玫瑰线"图案(多个偏心的回旋圆圈)——**这正是真实FTICR仪器设计时要求"回旋频率远高于轴向捕集频率"才能让两种运动干净分离的原因**，本次意外復现了这个真实的仪器设计考量，而不是简单的数值bug。 |
| 完整可跑通的参考脚本 | `test_icr_cell.m`(单一脚本，几何+ES+CPT一体化，径向/轴向初动能和B0/V_trap都是硬编码在脚本内的固定设计点，输出3合1轨迹图：回旋顶视图+轴向-时间曲线+3D轨迹)。模型存于 `comsol_models/ICRCell.mph`。 |

### 7.27 简单质谱仪整机集成 (EI电离源→引出→多极杆离子导管→TOF→反射器→检测器→分辨率)

| 调用/发现 | 说明 |
|---|---|
| **总体架构：分阶段建模，而非塞进单一网格** | EI电离(电子,ns级时间尺度) / 引出+多极杆传输+TOF漂移+反射器(离子,us级时间尺度) 物理尺度/时间尺度差异巨大，且**CPT物理场每个接口只允许一个`ParticleProperties`(pp1)**（电子和离子不能共用一个`cpt`接口）——电离阶段和"离子旅程"阶段必须是两个独立模型，中间用离子产率/初始分布等参数衔接，不是偷懒，是CPT架构的硬限制。 |
| **`Ionization` Collision Attribute 原生存在，但受"单一pp1"限制** | `coll1.create('ion1','Ionization')`——COMSOL CPT原生支持电子碰撞电离，属性含`ReleasePrimaryElectron`/`ReleaseSecondaryElectron`(默认都是`true`!)/`ReleaseIonizedParticle`(默认`false`)/`ReleasedElectronProperties`/`ReleasedIonProperties`(默认都指向`pp1`，且**只能**设成`pp1`，因为每个cpt接口只允许一个`ParticleProperties`实例——试图新建`pp2`会报"Only one instance of this feature is allowed")。**实际含义**：这个特征本质是为"电子在放电中生成更多电子"(真实电子雪崩)这类同种粒子场景设计的，不适合"电子电离产生完全不同质量/电荷的重离子"这种质谱EI场景——正确用法是只用它的**电离碰撞计数**功能(`CountCollisions=true`+`mphparticle`提取`Nc`，见§7.22)得到真实的离子产率统计，重离子本身在**下一个独立模型**里以近零初动能重新释放。 |
| **⚠️`ReleaseSecondaryElectron`默认`true`会导致粒子数爆炸式增长，是"CPT时间相关求解莫名其妙内存爆炸/挂起数十GB"的真正原因之一** | 第一次遇到"电子枪+电离"CPT时间相关求解报`NullPointerException`或`Out of memory xmesh processing`并让`comsolmphserver.exe`内存涨到30-40GB——逐一排除了集合方式(短肥圆柱+实心电极 vs 长细管+带孔电极模板)、`tstepsbdf`严格/自由模式、ES场复用(`notsolmethod`/`notsol`)、电子质量/速度量级等假设后，最终定位到`Ionization`特征默认`ReleaseSecondaryElectron=true`——每次电离碰撞会真的生成一个新的、被同时追踪的电子粒子(真实的电子雪崩机制)，只要电离概率不是极低，粒子数会随仿真推进指数增长，几千个时间步后可能有海量粒子在追踪，这才是内存爆炸的根因。**修复**：显式设`ion1.set('ReleaseSecondaryElectron', false)`。**排查这类"没报语义错误、但求解卡死/爆内存"问题时，检查有没有意外开启的"生成新粒子"类开关，比死抠求解器设置更容易命中根因。** |
| **`Release`特征的"热发射"叫`Maxwellian`，不是`Inlet`用的`Thermal`——而且`Maxwellian`会把粒子数放大约200倍！** | `Release`(域级别)的`VelocitySpecification`合法值是`"SpecifyVelocity"/"SpecifyMomentum"/"SpecifyKineticEnergy"/"Maxwellian"`（**没有`"Thermal"`**，那是`Inlet`边界级别特征专用的名字），配套用`T0`而不是`Inlet`的`T_src`+`T`。**更重要的坑**：`Maxwellian`模式会把Maxwell-Boltzmann速度分布按`Nvel`(默认200)个离散速度档"确定性"采样，**每个MeshBased释放点都会被复制成约200份**(不同速度)一起追踪——这是本节"内存爆炸"debug过程里另一个独立确认的根因(通过对照测试隔离：把`Maxwellian`换成固定`v0`后，同一个模型从挂起数十GB秒变几秒内solve完成)。**电离源这类"热发射能量远小于下游加速能量"的场景(如2700K≈0.23eV vs 70eV加速)，直接用固定小`v0`代替`Maxwellian`是完全合理的简化，没必要冒着粒子数爆炸的风险去追求"更精确"的热分布**。 |
| **提取电离/引出电极极性时，正离子的受力方向容易搞反** | 对+1价离子，`F=qE=-q∇V`——离子被从高电位推向低电位。设计"推斥极(repeller)+引出栅极(extraction grid)"时，**repeller必须在高电位、引出栅在低电位(通常接地)**，离子才会被推出、穿过引出栅继续往下游走；第一次接反(repeller=0V，引出栅=V_accel)时离子会一直被推向repeller方向，永远走不出电离区(`z_max`卡在引出区内，不管仿真多久都不再前进)。**这个方向性问题不会报错，只会让粒子"看起来完全不动/走错方向"，排查时要显式画出轨迹/检查`z_max`是否真的往下游前进，而不是想当然认为电位设置没问题。** |
| **⚠️RF离子导管(多极杆)约束一个"已经被加速到设计能量"的高速离子束时，之前对"近零动能离子"验证过的RF频率/电压完全不适用** | §7.16的1MHz/82V是针对**近乎静止**释放、在杆内长时间(多个RF周期)受约束的离子验证的。本次把100amu/1000eV离子(v=43928m/s)送进只有20mm长的八极杆，穿越时间仅约0.455us——**比1MHz的RF周期(1us)还短**，离子甚至连一个完整RF周期都经历不到，RF赝势近似(要求离子在约束场里经历"足够多"个周期才能把振荡场平均成有效势阱)完全不成立，离子只是被随机撞上的某个RF相位"顺手"踢了一下，径向发散、撞壁。**修复方向**：把RF频率大幅提高(本次从1MHz提到50MHz，让离子穿越期间经历~23个周期)，并/或延长离子导管长度换取更多约束时间。**结论**：RF约束是否有效，关键看"离子穿越时间 / RF周期"这个比值是否远大于1(绝热/赝势近似成立的前提)，不是只看"RF电压是不是在之前验证过的安全范围内"。 |
| **N极杆的近轴回复力标度为`r^(N-1)`，N越大近轴修正力越弱——已经在电离区/引出级获得少量径向初速度或位移的离子，八极杆(N=8, `r^7`)的近轴修正几乎为零，换成四极杆(N=4, `r^1`，线性)反而更稳健** | 本次串联"引出+多极杆导管+漂移+反射器"整机时，先用八极杆(参照§7.16"更适合做导管"的结论)，发现即使拉高RF电压/加长杆、修好RF频率的绝热问题，仍有相当比例离子径向发散撞壁——根因是离子从头到尾都非常接近轴线(相对r0=4mm量级)，而`r^7`标度的回复力在小`r`时几乎不提供任何修正，一点点扰动(引出栅孔径的"小孔透镜"散焦效应，见下一条)就会不受抑制地累积放大。**换成四极杆(线性回复力，对任意小`r`都有明确、非零的修正力)后同样参数下明显更多离子存活**。**这是一个具体的、和"六极/八极是宽松导管、四极是精密质量滤波器"(§7.16原有结论)看似矛盾、实则互补的补充**：六极/八极的"宽松"是相对"大range内更均匀的低损耗透过"而言，但如果離子本身就非常靠近轴线、只是需要"小幅度"修正，四极杆的强线性近轴力反而更有效更可靠，不能一概而论"导管就该用高阶极杆"。 |
| **⚠️引出栅孔径("小孔透镜")散焦效应会给离子束一个真实的、不可忽略的初始径向发散角，即使孔径已经不小** | 引出栅是一个开孔的平板电极(孔径`r_hole`，栅外是宽得多的漂移管`R_bore`)——即使不特意引入任何"倒灌"缺陷，離子从孔径进入宽阔漂移区这个几何突变本身就是一个真实的散焦透镜(类似真实离子光学里"小孔发散"的经典效应)，会给离子一个额外的、随後续距离线性累积的径向速度分量。**这个效应在栅孔径`r_hole`相对下游主体半径`R_bore`比值越小时越严重**：本次把`r_hole`从2mm提到3.5mm(同时保持后级径向空间足够大)，明显减少了小角度散焦导致的早期径向发散幅度。**设计任何"小孔进入宽阔区域"的电极结构时，都应该预期这个效应真实存在，不是仿真bug。** |
| **⚠️反射器(reflectron)平板镜面的"离轴离子径向散焦"(§7.19已记录)在离子完成"减速+反弹"整个过程中会持续存在，且是造成"离子明明真的发生了反射(`vz`变号)、但仍然在返程中途撞壁/撞栅格实体丢失"的直接原因** | 用`mphparticle`直接检查`v`分量(而不仅是位置)，确认离子在接近镜面时`vz`确实由正变负(**真实发生了反射**，不是数值假象)，但同一时刻径向位置`r`已经显著漂移(镜面附近的平板电极散焦效应持续作用，离子在减速过程中滞留在强场区域的时间更长，散焦效应有更多时间累积)——返程时这个已经积累的径向漂移会导致离子(a)撞上漂移管侧壁(需要足够大的`R_bore`)、和/或(b)返回到引出栅平面时径向位置已经超出栅孔`r_hole`范围，撞上栅格的**实体**部分(不是镜面/侧壁，是另一个物理边界)而被吸收。**只有同时放大`R_bore`(给径向漂移足够空间)和`r_hole`(给返程离子足够大的"接收孔径")，离子才能真正完成"发射→反射→返回穿过引出栅"的完整闭环**——本次在10mm/3mm(原始TOF验证用参数，只测过"到镜面附近"，从未真正测过完整往返)基础上放大到25mm/15mm，完整往返成功率从0/52骤升到4307/4521(95.3%)。**这是TOF+反射器领域一个通用、值得记住的设计教训：镜面散焦效应对"去程"和"回程"都有影响，只验证去程到镜面附近不代表整个往返闭环没问题，必须显式检查`v`的符号变化+完整往返的径向落点，才能确认反射器真的可用。** |
| **释放体积(relvol)半径直接决定"完整往返存活率"，越靠近轴线存活率越高** | `relvol`半径从1mm收窄到0.3mm(配合局部网格加密`hmax=0.1mm`获得足够多释放点)，完整往返存活率从个位数/几十(<5%)提升到4307/4521(95.3%)——**这本身就是一个真实的、有意义的发现**：镜面散焦+栅孔接收孔径共同决定了这套光学系统对离子初始径向位置/角度有一个有限的"接受口径"，不是无限宽容，设计真实仪器的离子光学时这个接受口径本身就是需要优化的关键指标。 |
| **完整往返飞行时间定量验证：`t∝sqrt(m)`在"完整闭环"(而不仅是单程漂移)下依然精确成立** | 100amu：往返时间均值`6.01063us`，标准差`0.02833us`；101amu：均值`6.04049us`，标准差`0.02844us`(均为N=4521释放、95.3%完成完整往返的统计)。时间比值`6.04049/6.01063=1.004968`，理论`sqrt(101/100)=1.004988`，误差仅`0.002%`——**证实了`t∝sqrt(m)`这个TOF核心原理不仅在简单单程漂移(§7.19原有验证)下成立，在"加速→漂移→反射→再漂移→穿栅返回"完整往返闭环下同样精确成立**。 |
| **分辨率计算：`R=t/(2·FWHM)`，FWHM由到达时间分布的标准差换算(`FWHM=2.3548σ`)** | 用100/101amu两组到达时间分布(均近似高斯，σ≈0.0283-0.0284us)算出`FWHM≈0.0668us`，`R=t/(2·FWHM)≈45.1`——**推论：这套简化几何/参数下，m=100处能分辨的最小质量差`Δm=m/R≈2.2amu`，说明100与101amu(Δm=1)这一对严格来说没有被完全分辨(两峰间距`0.02986us`只有`FWHM`的0.45倍，可视化叠加图上两峰有明显重叠)**，需要质量差≥~2.2amu(如100 vs 103)才能达到经典意义上的"刚好分辨"。这是一个自洽、可复现、真实基于仿真数据算出来的分辨率数字，不是凭空断言的。 |
| 完整可跑通的参考脚本 | `ms_stage1_ei_source.m`(EI电离源，电子70eV穿过背景气体电离区，输出离子产率统计)。**注**：本表格原引用的`ms_stage2to5_ion_journey.m`/`ms_stage4_tof_reflectron_resolution.m`/`ms_stage5_resolution.m`及其对应的`.mph`模型文件已被删除——它们是早期的平面反射镜TOF设计，已被§7.28的真实环栈反射镜(ring-stack reflectron)设计取代，按用户要求"只保留最新最合理的模型"清理，不再保留过渡版本。 |

### 7.28 正交加速TOF (oa-TOF)：碰撞冷却 + 真实双级环栈反射镜 + 尺寸匹配的检测器

> **背景**：§7.27把离子从多极杆"直接轴向"送进反射器，用户指出这和真实商用oa-TOF仪器不符——真实设计是离子以低能量(如5eV)沿多极杆轴向连续漂移进入"正交加速器(pusher)"，pusher瞬间给离子一个与原方向**垂直**的高能量脉冲，离子转而沿垂直方向飞行、反射、返回，原方向的漂移全程不受影响，返回时天然偏离pusher位置，可以安装检测器而不遮挡多极杆出口。后续用户进一步指出：(1) 反射镜不应该是单一平板，真实reflectron由多片中空环形电极叠加、栅网构成；(2) 两层栅网的正确位置是"入口一层+入口与背板之间一层"，背板本身不需要栅网(因为离子到不了背板)，栅网的作用是"构造平行电场的同时让离子通过"；(3) 检测器应根据离子实际到达区域的大小来定，不能凭空猜测尺寸。本节记录最终采纳的设计——**本节内容取代了此前所有过渡版本(单一理想化场、单一平板反射镜、全链路合并尝试、栅网位置有误的单级环栈)，那些版本的`.mph`模型和构建脚本已按要求删除，只保留下面这个最终的双级(Mamyrin型)版本**。

| 调用/发现 | 说明 |
|---|---|
| **✅✅✅最终状态(取代下表中所有孔径尺寸/发散相关的历史记录)：把每个"栅网"重新建模成理想细金属网(内部边界)，彻底解决了持续整个章节的场泄露/发散问题** | 下表里大量关于"孔径开多大"、"孔径/环间距比例"、"出口栅网泄露"的踩坑记录，根源都是同一个建模假设错误：把栅网做成"实心板挖一个大圆孔"。真实栅网是极细金属丝(~0.02mm)、极小丝间距(~0.5mm)编织的网——电学上几乎是一整块良导体(场畸变极小)，但离子能从任意位置穿过(>99%开孔率)。COMSOL里"实心板挖孔"和"细密金属网"是完全不同的两个物理对象，前者的孔径-透镜效应会让近轴场严重减弱/畸变(孔径越大，减弱越严重)，靠调整孔径大小只能"权衡"这个问题，无法根除。**正确做法**：把栅网建成零厚度的"内部边界"(embedded interior boundary)——用`Union`+`intbnd`把一个与真空域重叠的工作平面(WorkPlane)嵌入同一个连通真空域内，在这个边界上加固定电位(`ElectricPotential`)条件，但**不**让它成为独立的材料domain。这样静电场看到的是一整块良导体(完全匹配理想`V/gap`公式，实测误差<0.05%)，而`ChargedParticleTracing`不会把这条边界当墙(不是domain边界，离子在任意(x,y)位置直接穿过)。**由于离子能从整个栅网面上任意位置穿过，栅网不再需要开孔/权衡尺寸**——直接做成和真空域截面等大的整块board(比如800×800mm)即可，孔径-透镜问题从根源上消失。副作用：不再需要"出口后再加一个大孔栅网(grid2)兼容返程漂移"，也不需要"加装屏蔽套筒试图挡泄露场"——这两个之前的补丁(见下表)都变得不必要，已删除。**最终实测**(`ms_modelB_ringstack_reflectron.m`)：无场漂移区`Ez`全程精确为0(z=22-280mm)；加速区实测场强218680 V/m对比理论218750 V/m，误差0.03%；离子真正穿透反射镜(`z_max=344mm`，深入44mm，不再是被泄露场提前弹回的假象)；50个离子(用`InitialPosition='Density'`+`N=50`显式指定释放数量，而非依赖网格节点数)完整往返，**50/50(100%)命中探测器**，到达时间`8.839±0.038us`(相对分辨率0.43%)。 |
| **⚠️配套发现的COMSOL选择集陷阱：`Box`/`Cylinder`选择用`'intersects'`条件可能意外抓到不相关的边界，导致两个电位条件"悄悄"互相覆盖** | 用一个极小的独立测试模型(3层平行板+1层内部边界栅网)反复定位到的隐蔽bug：一开始给"栅网"用`Cylinder`+`'intersects'`选择(半径覆盖栅网+高度2mm)，结果意外地也选中了远处box的底面(**两者恰好共享同一个边界ID**)——两个`ElectricPotential`特征同时认领同一个边界ID时，COMSOL不报错，只是后创建的那个"悄悄"生效、先创建的那个`selection.entities()`查询显示0个实体、对应电位形同虚设。**表现症状**：直接查询电位分布，发现某一段区域电位完全均匀(卡在某个相邻电极的电位值)，而不是预期的线性梯度。**修复**：所有边界选择统一换成`Box`+`'allvertices'`条件(要求候选边界的**所有**顶点都在选择框内，而不是"只要有一部分沾边"就选中)，并且`Box`的x/y/z范围要完整指定(遗漏某个维度的范围可能导致选择集意外为空或过大)。**排查方法**：`selection.entities()`在"选择集本身"和"已经赋给某个物理特征的selection"两处分别查询对比，如果后者持续显示0而前者显示正常，基本可以确定是ID冲突。 |
| **⚠️配套发现的几何缝隙bug：两个应该衔接的真空域之间留了1mm间隙，离子在缝隙边缘处直接停止，且不随仿真时长增加而改变** | 加速/漂移区域(`accelflightbox`，止于`z=L_flight`)和反射镜真空包络(`reflvac`，起于`z=L_flight+1mm`)之间留了1mm完全没有被任何domain覆盖的区域——`Union`因此没能把两者合并成一个连通domain，离子轨迹追踪走到`accelflightbox`边缘(z=300mm)时直接停止，表现为`z_max`精确停在300.00mm，即使把仿真总时长(`Tsim`)翻倍也得到完全相同的停止点(逐位小数都相同)。**这个"翻倍时长结果不变"正是判断"是缝隙/边界问题"而非"仿真时间不够"的关键诊断信号**——纯粹的时间不足会让轨迹继续往前走一些（哪怕没走完），而卡在边界上的轨迹无论给多少时间都会停在同一个精确坐标。**修复**：把`accelflightbox`的长度从精确等于`L_flight`延长2mm，确保和`reflvac`的起始位置有实打实的重叠。 |
| **Model A：RF四极杆碰撞冷却，回答"5eV动能怎么来的"** | 真实仪器里，离子进RF导管时动能较高(如20eV，来自上游引出级)，导管内有轻质缓冲气体(几个mTorr)，离子和背景气体发生大量弹性碰撞(`Collisions`+`Elastic`，§7.22验证过的机制)逐渐损失动能，同时叠加一个很弱的轴向直流偏置场(`E_push`)防止离子完全停滞并把最终稳定动能钉在一个可控的低值——**碰撞冷却去掉"多余"动能，弱偏置场决定最终稳定在哪个值，两者缺一不可**。实测(100amu+1离子，KE0=20eV，Nd=3e20/m³，r0=4mm四极杆，150mm导管长)：`E_push`从20→70→150V/m依次测试，最终150V/m时平均经历`~16`次弹性碰撞、88.8%离子到达导管出口、出口平均动能`5.623eV`——精确落在目标5eV附近。脚本：`ms_modelA_collisional_cooling.m`。 |
| **真实reflectron的物理原理：多片中空环形电极("环栈")+两层栅网，而非单一平板** | 真实commercial reflectron由一叠同轴、中心镂空("洗衣机垫圈"状)的环形电极构成，各环电位沿轴向线性递增，入口和(如果是双级设计)两级之间各有一层栅网(mesh/grid)。**这个设计之所以比单一平板可靠得多**：平板的场只在紧邻板面的小范围内近似均匀，稍远处就明显弯曲(边缘散焦，§7.19/早期版本反复踩坑的根源)；而环栈是由多个大面积、彼此靠近的环电极共同构成中心孔附近的场，只要孔径相对环间距不太大，中心孔内的轴向场就非常均匀("平行场")，这是环栈设计"从物理原理上"就更不容易散焦的原因，不是靠更大的尺寸去"赌"。 |
| **⚠️栅网数量/位置的修正：两层栅网应该是"入口一层+两级之间一层"，末端背板不需要栅网** | 第一版误把两层栅网理解成"入口+末端背板各一层"，用户纠正：**末端背板离子根本不会到达(在到达之前就已经被减速反弹)，栅网的作用是"构造平行电场的同时让离子通过"——背板既不需要让离子通过(离子到不了那里)，也就不需要做成栅网**。正确设计是经典的双级(Mamyrin型)反射镜：入口栅网(0V) → **第一级**(短、陡峭，吸收约1/3总电压) → **中间栅网**(`V_mid=V_mirror/3`) → **第二级**(长、平缓，吸收剩余2/3电压) → 实心背板(`V_mirror`，无孔)。双级设计相比单级还有额外好处：对离子初始能量/位置的散布有更好的二阶时间聚焦效果(这是真实商用反射镜普遍采用双级而非单级的原因，不只是简化)。 |
| **构建方式：每个环/每层栅网 = 大圆柱(`xxxO`) 减去 中心孔圆柱(`xxxH`)，和大真空包络圆柱(`reflvac`)自动布尔联合** | 沿用验证过的"多个环/栅网几何和一个大真空包络圆柱重叠，靠COMSOL自动布尔联合(Form Union)自动拆分成多个电极domain+连通的真空剩余domain"技术——和更早的四极杆rod(§7.16)用的是同一个模式。最终实现：入口栅网(0V) + 第一级3个环(线性递增到`V_mid`) + 中间栅网(`V_mid`) + 第二级7个环(线性递增到`V_mirror`) + 实心背板(`V_mirror`，无孔)，第一级长度10mm(总长60mm的1/6)，第二级长度50mm，`V_mid=V_mirror/3`——标准商用双级反射镜的典型比例。 |
| **踩坑①：网格(mesh)规模失控，一次尝试产生175万单元导致求解超时** | 环外半径最初设160mm、网格加密区半径170mm、`hmax=4mm`，产生1,751,831个网格单元——环栈的体积和网格加密区范围直接决定总网格规模，径向不需要那么细的分辨率(只需要沿轴向足够分辨电位的线性梯度即可)。**修复**：把`hauto`从5调到6(整体更粗)，环外半径降到350mm(见下一条踩坑后最终确定的值)，加密区`hmax`放宽到22mm，网格恢复到~20万单元的可控规模。 |
| **踩坑②：离子孔径(`bore_r`)只按"反射镜内部局部偏移"估计，没算上离子进入反射镜前在漂移管里已经积累的偏移量，导致离子撞在环内壁上** | 第一版`bore_r=50mm`，离子在环栈内被吸收，冻结点`r=sqrt(x²+y²)≈54mm`，刚好超过孔径——**离子进入反射镜时已经因为原有的5eV横向漂移速度走了很长的漂移管，x坐标可能已经到了90mm量级，不是"从反射镜入口才开始偏移"**。第二次调到`bore_r=110mm`仍然不够(该量级下离子离孔径边缘太近，孔径边缘固有的"孔径透镜"效应仍然把离子踢飞，xEnd一度冲到300mm撞域外墙)。**最终**把`bore_r`加大到250mm(相对90mm的典型入射偏移有~2.8倍余量)、环外半径同步加大到350mm，问题才彻底解决。**教训**：环栈孔径的设计基准是"离子到达反射镜入口时的实际偏移量"，不是"反射镜内部预期的局部漂移量"，这两者可能差一个数量级。 |
| **⚠️修正：反射镜的孔径中心应该对准轨迹"V"的顶点，而不是对准pusher(x=0)** | 用户指出：离子正交加速的位置不应该是反射电极的圆心，"V"的顶角(轨迹最高点，离子在反射镜内最深处)才应该大致对准反射镜中心，这样往返轨迹关于反射镜大致对称。**诊断**：直接测量`zmax`发生时刻的x坐标，6个离子(两个质量数)范围`x∈[27.7,38.7]mm`，明显偏离反射镜原来的中心(x=0)——反射镜孔径原来centered在pusher的位置，而不是离子实际到达的最深点。**修复**：把入口栅网/中间栅网/两级环电极/背板的孔径中心从`(0,0)`平移到`(x_refl_center=33mm, 0)`(取实测顶点位置的中值)。 |
| **踩坑③：孔径缩小和平移一起做，把稳定性搞坏了——孔径大小的敏感参数是"离子偏移量/孔径半径"这个比值，不是绝对偏移量** | 重新居中后，第一次尝试顺手把`bore_r`从250mm大幅缩小到80mm(既然居中了，局部偏移应该更小)——结果轨迹严重不对称，x速度中途反号(轨迹追踪显示`x`从15.8mm开始转头下降甚至变负)，说明孔径边缘的"孔径透镜"效应反而更强了。**根因**：虽然离子相对新中心的绝对偏移变小了(约18mm)，但孔径半径缩得更多(80mm)，偏移/半径的比值反而从"250mm孔径下的安全比例"变成了危险比例(18/80≈22%)。**修复过程**：先把`bore_r`/`ring_outer_r`都还原回验证过安全的250mm/350mm(只做居中这一个变量的对照测试)，确认良好后再折中到150mm/320mm，测试仍不稳定，最终**保留250mm/350mm不变**，只做居中——教训是"居中"和"缩小孔径"必须分开验证，一次改两个变量、出问题时根本不知道该归咎于谁。 |
| **踩坑④：检测器重新定位时和推斥极(repeller)发生几何重叠** | 居中后离子的实际落点整体左移(新落点`x∈[10.6,56.2]mm`)，把检测器直接搬到这个新区间时(`x∈[-5,75]mm`)与推斥极(`x∈[-20,20]mm, y∈[-20,20]mm`)发生了几何重叠——**诊断信号**：`Ndomains`从25意外变成26(重叠区域被自动布尔运算拆出多余的域)，离子几乎立即冻结(`z_max`从~267mm骤降到1.75mm)。**修复**：把检测器起始x坐标移到`20mm`(恰好贴着推斥极边缘，不重叠)。 |
| **真实发现(非bug)：部分离子往返后精确落在推斥极范围内，无法被检测器捕获** | 修好重叠问题后，6个离子里有2个的最终x坐标是`15.1~15.6mm`——**这个位置在推斥极的范围内(`x<20mm`)，不在检测器范围内(`x>20mm`)**，也就是说这2个离子返回后会打在推斥极背面，而不是检测器上。这不是网格/几何bug，是把反射镜"居中对齐"之后的一个真实几何后果：居中改善了轨迹对称性，但也让部分离子的整体往返位移变小，使它们的回程终点比之前(反射镜偏心时)更靠近pusher。**最终验证**：100amu 4/6(67%)、101amu 4/6(67%)到达检测器，到达时间`12.35000us`/`12.40000us`，比值`1.004049`对比理论`1.004988`误差`0.093%`。轨迹图明显比修正前更对称(V形顶点位置更居中，参见`comsol_results/ms_modelB_ringstack_M101.png`)——**这是关于"轨迹对称性"和"探测覆盖率"两个设计目标之间真实存在的工程权衡，不是可以简单调参数消除的问题**。 |
| **检测器尺寸：根据实测到达区域定，而非猜测(居中修正后重新测量)** | 居中后重新测量：`x∈[34.2,55.9]mm`，`y∈[-18.5,19.6]mm`(仅统计成功落在检测器上的4个离子；另外2个落在推斥极范围，见上一条)。**最终检测器**：`80×70mm`矩形板，位于`x∈[20,100]mm, y∈[-35,35]mm`，起始x贴着推斥极边缘。**教训(沿用)**：判断"是否被检测到"必须用检测器电极的真实几何范围核对，不能只用宽松的软件坐标阈值。 |
| 完整可跑通的参考脚本 | `ms_modelA_collisional_cooling.m`(RF四极杆碰撞冷却，20eV→~5eV) + `ms_modelB_ringstack_reflectron.m`(正交加速器+双级环栈反射镜+尺寸匹配检测器，唯一保留的reflectron模型)。模型存于`comsol_models/MS_ModelA_*.mph`/`MS_ModelB_RingStack_*.mph`。**此前的所有过渡版本(`ms_modelB_orthogonal_reflectron.m`理想化场版、`ms_modelB_orthogonal_reflectron_real.m`平板反射镜版、`ms_merged_full_chain.m`全链路合并尝试，及单级环栈反射镜的早期迭代，及对应的所有`.mph`文件)已按用户要求删除**。 |
| **验证：pusher确实是真实固体电极，不是理想化场** | 检查`ef1.set('E_src','userdef')`的具体表达式，确认推力来自`es.Ex/Ey/Ez`(反射镜，真实求解场)和`es2.Ex/Ey/Ez`(推斥极，同样是真实求解场，只是求解的是100V单位场再按比例`V_push/100`缩放)——`userdef`只是指"CPT的ElectricForce特征允许用户自定义表达式"这个COMSOL机制本身，表达式内部引用的仍然是两个真实电极几何求解出来的场，不是脱离几何的理想化`userdef`公式(和之前§7.28被取代的那些理想化场版本不同)。 |
| **⚠️反射镜后离子发散过于严重：查阅文献，真实商用TOF的标准做法是"无栅网(gridless)离子镜"** | 检索到的文献(见下方来源)明确指出：无栅网反射镜的不均匀场本身能起到离子透镜的作用，缩小离子束的横向直径、补偿已有的发散；二级无栅网设计通常**只用一叠完全同款的环形电极**，靠环本身产生的弯曲等势线（而不是额外插入的实体栅网）来完成二级聚焦修正——额外插入的每一层实体栅网（哪怕只是本模拟里近似成的"大开孔"薄板）都会变成一个新的孔径透镜/散射面，让发散更严重而不是更轻。**修复**：去掉了原来加在第一级/第二级环之间的中间栅网，两级环的电位仍然按原比例分级(0→V_mid→V_mirror)，只是级间不再插入实体开孔板。 |
| **发现：去掉中间栅网后，发散幅度几乎没有变化** | 修改前后到达检测器时的y方向散布量级相近(约±19-24mm)——说明反射镜内部的栅网**不是**这次发散的主要来源。 |
| **追根溯源：直接查询轨迹在z=21mm(刚穿过出口栅网、还没进入漂移管)时的横向速度，发现vy已经有±620~700 m/s（6个离子里4个）** | 而漂移管本身应该是无场区域——也就是说，**发散在离子刚离开pusher/加速区域时就已经基本定型了，反射镜和漂移管只是把这个已经存在的横向速度带得更远**，不是发散的真正源头。这是本轮最重要的诊断结论，纠正了"发散是反射镜问题"的最初假设。 |
| **尝试①：把推斥极从方形(Block, 40×40mm)改成圆形(Cylinder, r=20mm)，排除"方板边角不对称"这个假设** | 方板存在几何上的四重对称破缺(边中点和角点场梯度不同)，理论上可能是横向踢脱的来源。**结果**：改成圆形后发散幅度没有改善(仍在±22-24mm量级)，说明根源不是简单的方形/圆形对称性问题，更可能是加速区域本身固有的"引出透镜"效应(真实oa-TOF pusher区域普遍存在，通常靠后级聚焦元件或更精细的多栅网结构补偿，不是几何对称性能单独解决的)。 |
| **尝试②(已回退)：在推斥极和出口栅网之间加一层脉冲到`V_push/2`的中间栅网，模拟商用多栅网引出结构** | 引入新bug：离子返程时的横向偏移已经超过了这层新栅网30mm的孔径半径，导致在`z=11mm`处冻结(`z_max`同时从267mm跌到194mm)——在没有先证明这个改动确实能减小发散之前就引入了新故障，果断回退，没有保留这个改动。 |
| **⚠️用户提出诊断思路：所有离子给完全相同的初始速度，只让初始位置不同——如果加速场/反射镜场是均匀的，不同离子的轨迹应该只是空间位移，不应该发散** | 检查发现脚本本来就满足这个前提：`rel1.set('v0',{v_in,'0','0'})`是固定矢量(不是Maxwellian分布)，released离子确实只在位置上有差异(relvol的x,y∈[-1,1]mm)。既然如此，观测到的发散(不同起始位置对应不同的最终横向速度)本身就直接证明了场不均匀——这是判断"场是否均匀"最直接的实验判据。 |
| **直接查询验证：用`mphinterp`查`es2.Ey`(pusher单位场)在x=0、不同y处的值，确认场存在真实的、平滑的横向梯度** | 近轴小范围(y=-1~1mm)的查询结果有噪声(疑似网格分辨率不足)，但扩大到y=±15mm查询后发现清晰、平滑、反对称的真实物理梯度：`Ey`从y=2mm处的~180 V/m平滑增长到y=15mm处的~2986 V/m(单位场值)——不是网格噪声，是真实的场发散。**根因确认**：推斥极(r=20mm)和出口栅网开孔(r=260mm)尺寸相差13倍，场必须在仅20mm的加速间隙内从"贴着小圆盘"迅速"张开"到匹配大得多的开孔，这个尺寸失配本身就会在间隙内产生强烈的横向场分量，即使离子离轴很近也不例外。 |
| **✅修复：出口栅网开孔从260mm缩小到80mm，让它真正起到"栅网"的作用(而不是形同虚设的大洞)** | 用户明确指出：出口栅网的开孔太大，起不到真正约束/终止加速场的作用，应该做成尺寸合理的真栅网。第一次尝试缩到40mm——加速场确实变得更平行(两个成功穿过的离子落点`x≈21mm`，比之前~34-70mm集中得多)，但40mm对返程离子的横向漂移而言太小，6个离子里4个卡在栅网实体上(冻结于`z=21mm`，恰好是栅网所在z位置)。**最终**开孔定为80mm：100amu、101amu均**6/6(100%)**完整往返到达检测器，到达时间`12.275us`/`12.35us`，比值`1.006110`对比理论`sqrt(101/100)=1.004988`误差`0.112%`。 |
| **诚实评估：80mm开孔恢复了100%探测率，但发散本身的幅度并未显著改善** | 到达检测器的y坐标散布仍在`[-27,15]mm`量级，和260mm开孔时(`[-24,23]mm`)接近——**说明80mm开孔虽然让返程离子不再被栅网卡住，但还没有把加速间隙内的场做到真正的"平行板"级别均匀**。40mm开孔时(虽然只有2个离子能穿过)展现出的落点更集中(`x≈21mm`)暗示更紧的开孔确实能进一步改善均匀性，但需要配合解决"返程离子横向漂移量"这个矛盾——真实商用设计通常用分级引出结构(多层栅网+后级聚焦透镜)来同时满足"加速场均匀"和"束流不被夹住"这两个要求，这是本次未继续深入的后续方向。 |

---

### 7.29 理想细网格栅网(内部边界)技术 + CPT `Release`特征的分布/随机化 API 速查

> **背景**：§7.28末尾记录的"栅网开孔泄露/散焦"系列问题，最终靠把栅网从"实心板挖孔"重建为
> "零厚度内部边界"根治(见§7.28最上方的"最终状态"条目)。本节是这个技术和配套发现的
> API速查表，独立于oa-TOF这个具体应用，任何需要"电极但离子必须能穿过"的场景都适用。

| 调用/发现 | 说明 |
|---|---|
| **建造理想细网格栅网：`Union`+`intbnd=true`，把一个WorkPlane嵌入已有真空域，得到零厚度内部边界** | ```matlab\nwp = geom1.feature.create('wp_tag', 'WorkPlane');\nwp.set('quickplane', 'xy'); wp.set('quickz', z_expr);\nwp.geom.feature.create('r1', 'Rectangle');\nwp.geom.feature('r1').set('size', [800 800]);\nwp.geom.feature('r1').set('pos', [-400 -400]);\ngeom1.feature.create('uni_grids', 'Union');\ngeom1.feature('uni_grids').selection('input').set({'vacbox','wp_tag'});\ngeom1.feature('uni_grids').set('intbnd', true);\n```。`Ndomains`应该保持不变(合并前后一致)，确认没有被拆成两个独立domain。因为离子能从整个面上任意位置穿过，**栅网不再需要开孔**，直接做成和真空域截面等大的整块board即可。 |
| **给这个内部边界加电位：选中它的Box+`'allvertices'`选择，赋`ElectricPotential`边界条件，`ChargedParticleTracing`不需要任何额外设置就不会把它当墙** | ```matlab\ncomp1.selection.create('selb_grid', 'Box');\ncomp1.selection('selb_grid').set('xmin',-400); ...set('xmax',400); % 必须完整给出x/y/z三个维度的范围\ncomp1.selection('selb_grid').set('zmin',[z_expr '-1[mm]']); comp1.selection('selb_grid').set('zmax',[z_expr '+1[mm]']);\ncomp1.selection('selb_grid').set('condition', 'allvertices');\ncomp1.selection('selb_grid').geom('geom1', 2);\n``` |
| **⚠️陷阱：`Box`/`Cylinder`选择用`'intersects'`条件会把"只是部分沾边"的不相关边界也选中，两个电位条件抢同一个边界ID时COMSOL不报错，只是其中一个静默失效** | 独立小测试模型复现：给栅网用`Cylinder`+`'intersects'`(半径覆盖栅网+一点高度)，结果连远处box的底面都被选中(和`selbot`共享同一个边界ID)。**表现症状**：`selection.entities()`对"选择集本身"查询正常，但对"已经赋给某个物理特征的selection"查询显示0——这是判断"是ID冲突不是选择集本身错"的关键诊断法。**修复**：一律换成`Box`+`'allvertices'`，范围完整指定三个维度。 |
| **⚠️陷阱：两个应该衔接的真空域之间留几何缝隙，离子精确停在缝隙边缘，且不随仿真时长增加而改变** | `accelflightbox`止于`z=L_flight`、`reflvac`起于`z=L_flight+1mm`，中间1mm没被任何domain覆盖——`z_max`精确停在`L_flight`，**把`Tsim`翻倍结果完全不变(逐位小数相同)**，这正是"缝隙/边界问题"而非"仿真时间不够"的判定信号(纯时间不够会让轨迹再往前挪一点，卡在边界上的轨迹无论给多少时间都停在同一坐标)。**修复**：让两个域的z范围有实打实的重叠(不是恰好衔接)。 |
| **CPT `Release`特征：显式指定释放粒子数，而非依赖网格节点数——`InitialPosition='Density'` + `N=<count>`** | 默认`InitialPosition='MeshBased'`配`N=1`是"每个网格节点/单元释放1个粒子"，释放总数由释放体积自身的网格密度决定(本项目1mm立方体默认网格给出6个，不是有意选择的数字)。**改成显式指定**：`rel1.set('InitialPosition','Density'); rel1.set('N','500');`——之后释放粒子数直接等于`N`，与网格密度无关。合法的`InitialPosition`取值(故意传非法值触发报错拿到的)：`"MeshBased", "Density", "RandomPosition"`。 |
| **CPT `Release`特征：`VelocitySpecification`合法取值，及"哪个字段是自由表达式、哪个是模式选择器"的关键区分** | 合法取值(同样是故意传非法值反查到的)：`"SpecifyVelocity", "SpecifyMomentum", "SpecifyKineticEnergy", "Maxwellian"`。**踩坑**：`InitialKineticEnergy`看起来像是能量的数值/表达式字段，实际上是一个**模式选择器枚举**(合法值`"Expression","ConstantSpeedSpherical","ConstantSpeedHemisphere","ConstantSpeedCone","ConstantSpeedLambertian"`)，直接塞一个高斯公式进去会报`Invalid parameter value`。**`v0`(速度)才是真正的自由表达式字段**(本项目从最开始就用它塞普通数值，后来验证也能塞含随机函数的公式)——需要按能量分布走随机化时，把能量公式换算成速度、写进`v0`里，而不是`InitialKineticEnergy`。 |
| **⚠️`randnormal()`不是COMSOL识别的函数——用`random()`(均匀分布)手动做Box-Muller变换得到高斯分布** | 直接在`v0`表达式里写`randnormal(1)`，求解时报`Unknown function or operator: randnormal`(注意：`.set()`本身不报错，只有真正求解时才报，因为表达式在求解前不会被解析求值)。**COMSOL确认可用的随机函数是`random(seed)`**(返回均匀分布[0,1]，`SamplingFromDistribution`需要设成`'Random'`，否则每个粒子会拿到同一个值而不是独立采样)。构造均值`E_mean_eV`、标准差`E_std_eV`的高斯分布能量对应速度：`sqrt(2*abs(E_mean_eV+E_std_eV*sqrt(-2*log(random(1)))*cos(2*pi*random(2)))*1.602176e-19[C]/m_kg)`。**单位陷阱**：基本电荷常数必须显式标`[C]`(`1.602176e-19[C]`，不是裸数字)，否则和`[V]`(eV)量纲的参数相乘时结果单位不对，后续`sqrt`会得到错误量纲。实测(500个离子，5±1eV高斯分布)：500/500(100%)命中探测器，到达时间`8.856±0.043us`，落点比单能量版本略宽(x跨度1.2mm vs 0.6mm)，符合能量分散带来额外发散的物理预期。 |
| **GPU(cuDSS)测试结论在本模型规模下依然成立：几乎不提供加速，且只影响静电场求解，不影响粒子追踪** | `dDef.set('linsolver','cudss')`(GPU) vs 默认`mumps`(CPU)，对本模型(es+es2+es3三个耦合静电场解)计时：CPU 29.372s，GPU 28.587s，加速比仅1.027倍。**关键认知**：cuDSS只加速FEM线性方程组求解(电场部分)，COMSOL没有GPU加速的粒子ODE积分器，**离子数量(500个还是50000个)不影响这个GPU/CPU对比**——电场求解的规模只取决于网格，与粒子数无关；粒子数量真正影响的是CPT本身的求解时间，而这部分从CPU还是GPU来求解都一样(纯CPU)。 |
| **✅用N=50000重新验证：确认电场求解耗时确实与粒子数无关(≈28-29s，和500粒子时几乎一样)；CPT本身求解50000个粒子耗时123.172s(可行)；但取回全部轨迹数据时服务器内存耗尽崩溃** | 电场部分CPU 28.093s / GPU 29.499s(这次GPU反而略慢，进一步印证"两者基本打平，谁也不比谁明显快"这个结论，不是运气好坏的问题)。**CPT求解阶段本身(`sol2.runAll`)成功完成，耗时123.172s**——说明50000粒子的\*\*求解\*\*本身是可行的，不算太慢。**崩溃发生在`mphparticle(model,'dataset','pdset1')`取回完整轨迹数据这一步**：`Out of memory on server`(`java.lang.OutOfMemoryError`)，服务器进程内存从平时的~2GB飙升到5.45GB后崩溃——50000个粒子×每个粒子几十到上百个时间步×(x,y,z)三个分量，通过MATLAB-COMSOL的LiveLink桥做二进制序列化时数据量过大。**教训**：粒子数量的实际瓶颈不在求解，而在**结果提取**——如果需要跑很大量的粒子做统计，应该只提取需要的统计量(比如末态位置`x(end,:)`对应的少数几个感兴趣的量)而不是`mphparticle`整个完整轨迹，或者分批次(比如每次5000个)求解+提取再汇总，避免一次性把全部时间步×全部粒子的数据都拉到MATLAB端。 |
| **✅内存优化方案验证：把CPT时间网格从50ns放宽到500ns(脉冲阶段仍保留5ns精细网格)，成功让10000粒子在不崩溃的前提下完成完整轨迹提取+分辨率计算** | 延长飞行管到3000mm(10x)后，`Tsim`同步变成约10倍，如果继续用旧的50ns网格，存储的时间点数也会变成10倍，会比N=50000那次更快耗尽内存。**修复**：`tstep.set('tlist', 'range(0,5e-9,1e-6) range(1.05e-6,500e-9,Tsim)')`——脉冲期间(0-1us)保留5ns精细网格(这个精度是求解器准确积分快速脉冲上升沿/下降沿所必需的，不只是输出采样密度)，脉冲结束后的漫长飞行段放宽到500ns(约4-5倍数据量缩减)。**结果**：N=10000完整跑通，`mphparticle`取回全部轨迹数据没有崩溃，静电场求解(GPU/cuDSS)23.71s，CPT求解(CPU)29.01s，10000/10000(100%)命中探测器，到达时间`68.609±1.741us`，**质谱分辨率`R=t/(2*sigma_t)=19.7`**。**经验**：真正决定是否会OOM的是"存储的时间点数×粒子数×3"这个乘积，不是粒子数单独决定的——飞行时间越长/网格越密，越容易在较小的N下就崩溃，反过来说，只要按需放宽网格密度，用大得多的N也不会OOM。 |
| **⚠️真正定位到分辨率瓶颈：不是刻意加的能量分散，而是1mm释放体积在Z方向的范围，在20mm加速间隙内造成的~±220eV动能分散(经典TOF"渡越时间"问题)** | 直接查相关系数(`corrcoef`)发现：`到达时间`和`初始x位置(x0)`几乎不相关(0.01)，和`初始y位置`几乎不相关(0.05)，和"x方向动能分散的代理量(vx_proxy)"只有中等相关(-0.41)，但和**初始z位置(z0)**有很强的相关性(**0.84**)！物理解释：z0∈[1.03,1.97]mm决定了离子实际被加速的有效距离(z0越靠近推斥极，加速距离越长)，在218736 V/m的加速场下，约1mm的z0差异对应约±220eV的动能差异——这个量级远大于刻意加的5±1eV初始能量分散，是真正的分辨率瓶颈。**这正是反射镜"空间/能量聚焦"本该解决的经典问题**：不同动能的离子理论上应该穿透反射镜不同深度、恰好同时返回，但简单的两级设计不能完美实现这一点，尤其是飞行管越长，未被完全修正的残余误差累积得越多(实测：300mm飞行管时`R≈103`，延长到3000mm后`R`降到约20，而不是像预期那样因为总渡越时间变长而提升)。**快速扫描`V_mirror`(30个离子/次)**：`1.0x→R=11.7`，`1.1x→R=24.5`，`1.2x→R=18.2`，`1.3x→R=20.7`，`1.4x→R=28.1`——确认调整反射镜电压确实能改善，但改善量级有限(十几到二十几)，远不到2000，说明这不是靠调一个参数就能解决的，需要多参数(`V_mid`/`L_stage1`/环数分布等)联合优化才可能大幅提升，本次按用户决定接受当前量级的分辨率，不再深入优化。 |
| **⚠️重要教训：小样本参数扫描的"改善"很可能只是统计噪声，必须用大样本复核才能下结论** | 尝试用Wiley-McLaren"空间聚焦"思路调`V_accelmid`(加速器两级分压点，理论上应该能让不同z0的离子渡越时间趋于一致，不需要改变释放体积)：先用N=50粗扫(2500-4300V)，发现`corr(z0,arrivalTime)`从+0.78单调过零到-0.84，零点接近3500V附近，此时R=17.1看似是当轮最优；加密到N=200精扫(3300-3700V)后，相关系数不再干净单调(3400V时corr=-0.105但R仅21.5，3500V时corr=0.395但R反而更低)，最优点漂移到3700V(R=26.7)。**但用N=10000大样本严格复核**：`V_accelmid=3700V(调优后)`和`3500V(调优前)`的R分别是**18.9和19.7**——统计上没有差异！说明小样本(N=50/200)扫描看到的"改善"主要是`SamplingFromDistribution='Random'`导致的**采样噪声**，不是真实的物理改善——小样本量下不同次求解抽到的随机粒子本身就有很大偏差，足以让R的测量值在很宽范围内波动，容易被误判成"参数调对了"。**教训**：任何基于随机采样的参数扫描/调优，找到"最优值"后必须用足够大的样本重新验证，不能仅凭小样本扫描的结果就下结论或写入正式配置。 |
| **✅✅✅真正解决z0动能分散：在释放体积两侧紧贴加装一对"局部展平"栅网(gridA/gridB)，不改变释放体积也不改变离子最终动能** | 用户提出的正确思路：只改变释放体积附近的**局部**电压差，不改变整个加速器的电压差——原理是"离子最终获得的动能只取决于它出发时所在的电位、以及它最终到达的电位(0V)，不取决于中间电位是如何分布的"，所以只要保持释放体积**中心点**的电位不变，就可以把释放体积内部的场任意展平，而不影响任何离子的总能量。具体做法：在原来第一级(推斥极4500V→accelmid3500V，线性梯度)中，释放体积(z=[1,2]mm)原本对应电位z=0.5mm处4375V、z=2.5mm处3875V(2mm跨度500V)；新加`gridA`(z=0.5mm)=4147.7V、`gridB`(z=2.5mm)=4102.3V，中点电位不变(4125V)，但跨度压缩到~45.5V(约11倍，对应用户说的"440V降到40V")。释放体积**外侧**(z<0.5mm和z>2.5mm)的场相应变陡以"补回"压缩掉的电压差，但这些陡峭区域所有离子都会同样经过(不管各自z0如何)，不会重新引入z0依赖。**实测**(N=10000大样本)：`R`从~19-20提升到**31.5**，真实、稳健的改善(不是小样本噪声)。 |
| **✅同步简化：既然反射镜的场本来就是静态常开的，加速器没有理由做成脉冲式——离子在静态场里从释放点自然被加速即可，不需要考虑含时电场** | 用户指出：现有设计里加速器电极(推斥极/accelmid/gridA/gridB)用了"脉冲"套路(先0V，触发后用sigmoid迅速升到目标电压，维持一段时间再关闭)，这是从"连续离子束需要被pusher瞬间踢出"这个更早期的设计考虑来的；但既然探测器已经放在z=22mm(刚好在grid1接地栅网z=20mm的飞行管一侧)，返程离子**根本不需要重新扎回加速器内部**就能被探测到，所以让加速器电极也像反射镜一样全程静态常开是安全的，不会误伤返程离子。**简化内容**：把原来`es`(反射镜单位场)+`es2`(推斥极单位场)+`es3`(accelmid单位场)+`es4`(gridA单位场)+`es5`(gridB单位场)共5次独立静电场求解、外加CPT力表达式里复杂的sigmoid时序叠加公式，合并成**一个**`es`静态解(全部电极都设成各自真实电压)，CPT力表达式直接简化成`{'es.Ex','es.Ey','es.Ez'}`。**效果**：静电场求解时间从24-30秒降到**6.45秒**(4-5倍加速)，代码复杂度也大幅降低(不再需要`t_trig`/`t_pulse_width`参数、不再需要为每个新电极单独建一次"单位场+叠加权重"的求解流程)。**教训**："单位场叠加+运行时按含时电压加权求和"这个技巧只在电极电压真的**含时变化**时才有必要——如果设计允许所有电极全程用各自固定电压，把它们全部合并进同一个静态解，代码和求解都会简单/快得多。 |

### 7.30 双级(Mamyrin)反射镜的正确设计方法 + 三栅加速器精确时间聚焦 + 数值求解器排错

> **背景**：§7.29末尾把分辨率停在R≈19-31这个量级，此后本项目继续深挖"反射镜二阶聚焦为什么没生效"，
> 最终发现根本问题不在反射镜，而在于**理论方法本身用错了**——只满足了一阶聚焦条件，从未真正求解
> 二阶条件；改用正确的闭式解、并新增一个独立的"三栅加速器"精确时间聚焦设计后，分辨率从个位数/十位数
> 提升到R≈850-1000量级。本节记录这整个过程的关键发现，以及配套的数值求解器排错经验。

| 发现/教训 | 说明 |
|---|---|
| **⚠️⚠️⚠️根本方法论错误：之前所有V_mid/V_mirror调优都只满足了一阶聚焦条件(dT/dU=0)，从未求解二阶条件(d²T/dU²=0)——这正是R长期卡在几百量级、怎么调V_mid都上不去的根因** | 双级反射镜(Mamyrin型)有E1、E2两个自由场强，理论上需要**同时**解两个方程(一阶+二阶聚焦)才能唯一确定E1、E2。本项目此前的做法是把`V_mirror`固定为`V_repeller`的一个经验倍数(如1.4x)，只用`V_mid`一个自由度去满足一阶条件——这是一个**欠约束**的做法：只解了1个方程，2个未知数，二阶导数`d²T/dU²`几乎必然不为零，残留的二阶曲率就是限制分辨率的主因，无论怎么单独调`V_mid`都无法消除它(因为E2从未被"解出来"，只是被人为固定)。**修复**：使用配套的`reflectron_dual_stage_solver.py`(闭式解，同时求解一阶+二阶条件得到E1、E2、U1)，不再手动猜`V_mirror`的倍数。 |
| **文档/代码中一个需要注意的小bug：`d2_min = U1/E2`这个公式跟同一份代码里`flight_time()`函数自身的物理不一致** | `flight_time()`函数内部正确地用`(U-U1)`计算离子进入第二级的剩余动能`v1`(从而算出第二级穿透深度应为`(U0-U1)/E2`)，但配套文档和`solve_reflectron_fields()`导出的`d2_min`字段用的公式却是`U1/E2`——两者数值差异很大(实测案例中`(U0-U1)/E2≈14.9mm` vs 文档公式给出的`≈208.6mm`)。**验证方法**：直接用`flight_time()`自己的内部逻辑反推穿透深度，跟`d2_min`字段对比，数值不一致即确认是公式本身的问题，不是自己算错。**教训**：拿到别人(或AI)提供的推导/代码时，即使大部分交叉验证过，也要挑关键的导出量单独用代码自身的其他部分复算一遍，不能全盘信任"已验证"的标签。 |
| **✅✅重大发现：反射镜的能量聚焦(修正z0→动能差异)和加速器自身的"上游传输时间"是两个独立效应，前者的理论修正对后者完全无效** | 直接对比理论`T(U)`曲线(对不同z0应为完全常数，验证到6位小数不变)和实测到达时间(随z0近乎完美线性变化，`corr(z0,detTime)≈-0.99`)：两者的差值`T_measured-T_theory`本身也随z0线性变化(约100ns量级)，且这个差值与"离子从z0走到加速器出口(无场区边界)所需的传输时间差"直接数值吻合(手算运动学验证)。**物理解释**：Mamyrin双级聚焦理论只针对"离子已经带着最终动能进入无场漂移区之后"这一段做时间聚焦优化，完全没有建模"离子从释放点z0走到无场区边界"这一段本身也是z0相关的——这是两个独立的物理效应，反射镜设计再精确也修正不了发生在它自己"视野之外"的时间差。 |
| **✅✅✅用三栅加速器的精确一阶时间聚焦闭式解，可以让离子恰好在无场区边界(接地栅网)处完成时间聚焦，实测验证到达时刻方差为0** | 配套文档"三栅加速器总长度符号推导"给出闭式解：给定期望的`KE0`(标称动能)、`ΔKE`(允许的动能分散)、`Δx0`(离子云展宽)、`d1`(第一栅-第二栅间距，工程下限)，可解出`U1=KE0+ΔKE·d1/Δx0`、`U2=KE0-ΔKE·d1/Δx0`，再用严格聚焦条件`ρ*=v3/(v3-v2)`解出`E2*`、`d2*`，使总漂移`D=0`(离子恰好聚焦在栅3/无场区边界)。**实测验证**(直接测量离子到达`z=L_accel`即栅2位置的时刻)：10个不同z0(1.125~1.875mm)的离子，到达时刻**完全相同(std=0.0000ns)**——理论精确复现，加速器自身的"上游传输时间"问题被彻底解决。这证明了"反射镜聚焦"和"加速器聚焦"必须分开设计、分开验证，不能假设解决了一个就自动解决另一个。 |
| **⚠️反射镜环电极场精度问题：环数从15降到5后，配合过宽的`bore_r`(环孔径半径)，第二级实测场强对理论值出现~8%的"S形"畸变(不是简单偏移，是真实形状问题)，足以完全压垮二阶聚焦所需的高精度** | 直接沿离子实际(偏轴)轨迹逐点查询`es.Ez`跟理论线性场对比：第一级偏差稳定在+0.3~0.6%(小)，但第二级从`-3.6%`(靠近中间栅网)摆动到`+4.47%`(靠近背板)，跨度约8%。**诊断**：环间距(第二级300mm/6环=50mm)与`bore_r=300mm`(临时诊断用的宽孔径)几乎同量级，典型的"孔径/间距比过大"导致离散环无法准确逼近连续线性场。**修复效果**：收窄`bore_r`到80mm(配合`ring_outer_r=200mm`，恢复此前验证过的0.4比例)后，第二级偏差降到`-1.18%~+1.02%`(约2.2%跨度)，分辨率从**R≈437.6跃升到R≈834-1033**(N=10~20)。 |
| **反直觉发现：把环数从5加回15，场偏差和分辨率几乎没有变化(~1.3-2%偏差 vs 2.2%，R=820 vs 834，统计噪声范围内)——说明环数本身不是瓶颈，`bore_r`收窄才是关键** | 容易想当然认为"环数越多，离散逼近连续场越准"，但实测证明对这个具体几何(300mm第二级)而言，把环数从5提到15带来的改善可以忽略不计，而单独收窄`bore_r`(300→80mm)带来的改善是决定性的(R几乎翻倍)。**教训**：遇到"离散电极逼近连续场不够准"的问题时，不要默认"加环数"是唯一或首选解法，先检查`孔径半径/环间距`这个比例是不是本身就设置得不合理——这个比例失衡时，加多少环都无法根治。 |
| **⚠️选择区域重叠bug再现(同类问题在gridA/gridB时代已踩过一次，这次在新的3mm间距栅网设计上再次出现)：`selb_grid1`用标准±1mm窗口在z=3mm处意外碰到释放体积(relvol)在z=2mm处的自身边界** | 症状：`selb_grid1`边界计数显示为2(应该是1)，对应z点查到的场强完全乱套(时而正常时而跳变甚至变负)。**根因**：grid1在z=3mm，标准±1mm窗口是`[2,4]mm`，恰好把release volume(z=[1,2]mm)在z=2mm处的自身边界也框进去了，两个`ElectricPotential`特征抢同一个边界ID，其中一个静默失效。**修复**：给`grid1`单独用更窄的±0.5mm窗口(`[2.5,3.5]mm`)，安全避开z=2mm。**教训**：任何"标准窗口大小"在新的几何尺度下都需要重新检查是否会撞到别的已知边界，尤其是电极间距缩小之后——这类bug的诊断信号(边界计数不等于预期值、场强数值在相邻查询点间剧烈跳变)已经是本项目第二次遇到，值得在开发新设计时第一时间就主动检查`boundary count`打印是否符合预期，而不是等结果异常了再回头查。 |
| **⚠️CPT时间相关求解器崩溃(`N≥20`必现，`N≤15`正常，与随机种子无关，崩溃时刻完全确定)：根因是非线性求解器默认用GMRES(迭代法)作线性子求解器，某个特定粒子的极端参数组合导致GMRES不收敛产生NaN** | 报错`"NaN or Inf found when solving linear system using GMRES"`，崩溃时刻在N=20/50/200下完全一致(说明是确定性的"第16个及以后粒子里有个特定的极端值"，不是运气问题)。**诊断**：查`model.sol('sol2').feature('t1').feature('fc1').getString('linsolver')`返回`'i1'`(指向一个`Iterative`类型的求解器特征，即GMRES)。**修复**：`model.sol('sol2').feature('t1').feature('fc1').set('linsolver', 'dDef')`，把非线性求解器(`FullyCoupled`)的线性子求解器从迭代法(GMRES)换成直接法(`dDef`默认对应MUMPS/PARDISO)——直接法不存在"迭代不收敛"这种失败模式，对付个别粒子的病态/边界情形远比GMRES稳健。**效果**：换成直接求解器后，N=20不再崩溃，且分辨率进一步提升到**R=1033.7**(此前受限于只能用N≤15验证，噪声更大)。**教训**：时间相关CPT求解报NaN/Inf且和迭代求解器(GMRES/AMG等)有关时，优先尝试换成直接求解器，往往比排查"哪个粒子导致了病态"更快解决问题。 |
| **⚠️`mphparticle`的`'expr'`参数并不会真正减少服务器传输的数据量——验证后发现即使只请求`{'qz'}`，返回的`pd.p`依然是`[ntime x nP x 3]`(仍含全部3个分量)** | 原本设想：大N统计只需要z(t)判断到达时刻，不需要x,y，用`mphparticle(model,'dataset','pdset1','expr',{'qz'})`应该能把传输量减到1/3，从而避免`N=10000`时的"服务器内存耗尽"错误(该错误明确发生在COMSOL自己的`PrimitiveBinarySerializer`序列化阶段，而不是MATLAB端持有数据的阶段)。**实测验证**(直接打印`size(pd_z.p)`)：无论请求`{'qz'}`还是不指定`expr`，返回的`size`都是`[11086 50 3]`——3个分量一个都没少，'expr'参数没有起到减少数据量的作用。**结论**：这条路走不通，唯一真正有效的内存控制手段是**减少N**或**减少存储的时间步数**(后者需要非常小心，见下一条)。本项目最终用N=5000(而非原计划的N=10000)完成大样本GPU/CPU对比，5000×11086步×3分量在实测中可以安全跑完(约1.3GB量级)。 |
| **⚠️尝试用"分段粗化tlist(开头粗、中间细、结尾粗)"进一步压缩大N内存占用，第一次尝试直接把分辨率打崩(N=20时R从1033.7跌到266.8)——根因是粗化段覆盖了加速器自身的快速动态** | 想法：反射镜真正的"精细往返"只发生在整个飞行时间的中段，开头(离子还在加速器/初始漂移里)和结尾(返程漂移)理论上不需要5ns精细分辨率，粗化成1us应该能大幅省内存。**实测**：把tlist从"全程5ns精细直到3倍单程飞行时间"改成"0-14.16us粗糙(1us)+14.16-46us精细(5ns)+之后粗糙"，分辨率从1033.7暴跌到266.8。**根因**：加速器(repeller-grid1-grid2)自身的通过时间只有约0.545us(前面用tGrid2直接测出来的)，1us的粗糙步长对这段极快的动态而言严重不足，即使`tstepsbdf='free'`(理论上求解器内部会自适应精细步长)也没能完全弥补输出粗糙带来的问题。**教训**：粗化tlist前，必须先明确知道"哪些时间段包含快速动态"，不能只凭"这段看起来是匀速漂移"的直觉去粗化——本例中，加速器虽然物理长度很短，但它的时间尺度(亚微秒)比反射镜的时间尺度(几十微秒)快得多，是真正需要精细分辨率的地方，即使它不在"看起来复杂"的反射镜区域内。 |
| **✅进一步确认GPU(cuDSS) vs CPU(pardiso)对CPT主直接求解器的性能结论：CPU比GPU更快，不仅电场求解如此，CPT本身的直接求解器也一样** | 在换成直接求解器(`dDef`)解决了GMRES崩溃问题之后，同时把`model.sol('sol2').feature('t1').feature('dDef').set('linsolver', ...)`也做成可切换的(`'cudss'`或`'pardiso'`)，N=5000做严格对比：静电场求解GPU 9.81s / CPU 9.77s(基本打平，符合此前多次验证的结论)；**CPT求解GPU 168.59s / CPU 130.50s，CPU反而快约23%**。两者物理结果完全一致(R、到达时间、命中率逐位相同)，纯粹是性能差异。**结论**：对这类"环栈反射镜+CPT"规模的问题，GPU(cuDSS)不但不提供加速，在CPT这个环节甚至更慢——本项目目前所有测试场景都应默认用CPU(pardiso)求解，GPU切换没有实际收益。 |

### 7.31 用"理论完美场"诊断法定位分辨率瓶颈 + L1/L2几何对齐 + bore_r反直觉重新扫描

> **背景**：§7.30把R提升到~850-1030量级后，用户提出一个关键诊断思路——直接把CPT力表达式里的真实场
> 换成理论闭式解给出的分段常数场（"理论完美场"），如果分辨率大幅提升，就证明瓶颈是真实场与理论场的
> 偏差，而不是设计本身的问题。这个方法论直接带来了本节两项最大的发现。

| 发现/教训 | 说明 |
|---|---|
| **✅✅诊断方法本身：把CPT力表达式`ef1.set('E',...)`换成反射镜区域的分段常数理论场(`if(z<L_flight,es.Ez,if(z<L_flight+L_stage1,-V_mid/L_stage1,...)))`)，加速器+漂移区仍用真实场，R从934.6跳到1728.1(N=100)** | 证实"真实场精度不足"确实是限制分辨率的主因，给后续优化指明了明确方向：缩小真实场与理论场的差距。**实现要点**：Ex/Ey在反射镜区域内也要设为0(匹配理论的纯1D假设)；符号务必和实际物理方向核对——加速器区域V随z**递减**(推斥极高电位到栅2地电位)，`Ez=-dV/dz`应为**正**(推着离子往+z走)，反射镜区域V随z**递增**(离子减速)，`Ez=-dV/dz`应为**负**，两者符号相反，第一次实现时把加速器部分也写成负号，导致离子几乎不动(`z_max`卡在1.92mm)。 |
| **⚠️排除了"时间量化误差"这个候选解释**：把CPT输出tlist从5ns加密到1ns，理论完美场测试的R几乎不变(1728.1→1726.6)，说明离散步长不是瓶颈，剩余的分散是真实物理效应。 |
| **✅✅✅根本问题：Mamyrin理论的`L_total`(=L1+L2)必须是离子已经达到最终动能后的纯漂移距离，而不是简单的`L_flight×2`——离子在z0处释放时还没有达到最终动能，要穿过加速器剩余部分(到z=L_accel栅2)才算真正开始匀速漂移** | 直接验证：理论`flight_time()`算出的T0(=30.047us)和实测到达时间(29.87-29.90us)对不上(差150-180ns)，均值都对不上，不只是分散对不上。**根因**：`L1`(源→反射镜)应为`L_flight-L_accel`(而非`L_flight`本身)；`L2`(反射镜→探测器)取决于探测器实际位置。之前一直用`L_flight×2=1000mm`当作`L_total`喂给`reflectron_dual_stage_solver.py`，隐含假设了"加速器长度为0、探测器恰好在L_flight处"，这两个假设都不成立。**修复**：探测器从`L_accel+2mm`移到`L_accel+0.3mm`(贴近无场区边界，让L2也约等于L1)，重新用`L_total=2*(L_flight-L_accel)=960.34mm`(而非1000mm)求解`reflectron_dual_stage_solver.py`得到新的`V_mid=1888.69V`、`V_mirror=4635.16V`。**效果**：真实场R从934.6提升到1568.4(+68%)，理论完美场R从1791.3提升到5780.1(+223%)，到达时间均值也从29.87us精确对齐到理论预测的29.73us附近。**教训**：任何"总漂移距离L"的理论参数，必须对照实际几何逐段核实其物理含义(离子从哪里开始算作匀速、到哪里算作被探测)，不能想当然用几何图纸上的总长度代入。 |
| **⚠️探测器新位置(`L_accel+0.3mm`)落入了`selb_grid2`原有±1mm选择窗口(`[L_accel-1,L_accel+1]`)，`boundary count`变成2(应为1)——虽然grid2和探测器都接地(0V)所以数值上无害，仍应收窄避免结构隐患** | 与§7.30的grid1/relvol重叠bug同一类问题的再次出现，这次是因为"移动探测器位置来对齐L2"这个新操作引入的。**修复**：`selb_grid2`窗口从±1mm收窄到±0.2mm。**教训**：任何改变电极/探测器空间位置的操作后，都要重新检查所有相邻选择窗口的`boundary count`打印，不能假设"移动一个东西不会影响别处的选择集"。 |
| **✅✅反直觉的核心发现：修正`L_total`之后，之前"收窄`bore_r`改善精度"的结论方向整个反了——用正确的L_total重新扫描，是bore_r越宽分辨率越好(有明确的收益递减)，而不是越窄越好** | §7.30在**错误的L_total=1000mm**下扫描发现"300→80mm收窄有效"；这次用**修正后的L_total=960.34mm**重新扫描(N=100，真实场)：`30mm→R=23.1`(比80mm差68倍！)、`60mm→580.4`、`80mm(旧默认)→1568.4`、`100mm→2262.0`、`150mm→3933.3`、`250mm→4070.9`、`400mm→4869.2`(但400mm有几何风险，见下条)。**结论**：旧结论是在一个本身就有系统性偏差(错误L_total)的设计上得出的"局部最优"，换到正确设计后最优方向完全相反——任何参数扫描的结论都只对"扫描时的其余设计"成立，设计的其他部分发生实质性改变后必须重新扫描，不能想当然沿用旧结论。 |
| **⚠️bore_r/ring_outer_r扩大到400mm+后，触发了栅网WorkPlane矩形(原800×800mm，即±400mm半宽)不够大的几何错位——`selb_midgrid`边界计数跳到5(应为2)** | 根因：栅网(entgrid/midgrid等)用`WorkPlane`+`Rectangle`(尺寸800×800mm)做成理想内部边界，当`ring_outer_r`(环栈半径)超过这个矩形的半宽(400mm)时，环栈几何比栅网平面还宽，导致两者边界关系错乱。**修复**：把WorkPlane矩形放大到1600×1600mm(连带`accelflightbox`真空块尺寸、`gridsel`选择框的x/y范围也一并从±400放大到±800)，之后400mm/500mm的`boundary count`恢复正常(2)。**教训**：任何"用矩形覆盖整个截面"的理想化边界技巧，矩形尺寸必须留有相对将来可能测试的最大几何尺寸的余量，否则换用更大尺寸的其他部件时会静默触发同类错位。 |
| **⚠️网格代价随`ring_outer_r`近似平方增长，且"精细网格选择区"若用固定半径而非参数表达式，在尺寸扫描时会造成完全不必要的额外浪费或不足** | `selreflregion`(触发精细网格的圆柱选择)原来固定`r=210`，当`ring_outer_r`扫到350mm时已经小于环栈半径本身(精细网格没有完全覆盖环栈)；试图一次性固定改成`r=700`来"确保覆盖"时，在`ring_outer_r`较小的场景下把精细网格铺满了远超环栈实际范围的空域，网格数从17万暴涨到366万，直接导致求解超时。**修复**：改成参数表达式`'ring_outer_r+10[mm]'`，让精细网格区域跟随`ring_outer_r`自动缩放。**教训**：任何"决定网格精细区域"的选择集，只要对应的几何尺寸是会被扫描/调优的参数，就应该用参数表达式而非固定数值，否则每次改设计都要记得手动同步，容易遗漏。 |
| **✅性价比权衡：`bore_r`从250mm(R=4070.9, 网格17万)加大到400mm(R=4869.2, 网格220万)只多换来~20%的R提升，却要多付出~13倍的网格/求解成本；500mm/650mm干脆算不完(网格366万，电场求解就要100s+，CPT求解超时)** | 收益递减非常明显：100→150mm(R从2262到3933，+74%)，150→250mm(+3.5%)，250→400mm(+19.6%，但成本涨13倍)。**最终选择`bore_r=250mm`/`ring_outer_r=350mm`作为性价比最优点**：真实场N=5000大样本验证`R=3009.3`(相比本轮起点859.3提升约2.5倍，相比§7.30末尾的934.6基准提升约2.2倍)，且求解速度仍在可接受范围(电场~5-30s，CPT N=5000约200s)。 |
| **✅环数复核confirmed：即使在新的bore_r=250mm下，把环数从5加到15，R反而从4070.9降到3531.7(N=100)，且求解成本涨约4倍(网格17万→119万，CPT求解20s→85s)** | 再次确认§7.30的结论在新设计下依然成立——环数不是精度瓶颈，`bore_r`/`ring_outer_r`才是。多余的环只会增加更多环缝隙(每个环之间的微小间隙都是潜在的场畸变源)和求解成本，没有任何收益，维持5环是唯一合理选择。 |

### 7.32 加速器"屏蔽罩+环电极"重新设计：圆柱形失败→方形独立测试成功→整合

> **背景**：§7.31把grid1/grid2(加速器自身的理想栅网)跟entgrid/midgrid(反射镜栅网)一起放大到了
> 1600×1600mm，纯粹是为了配合反射镜`ring_outer_r`扫描——用户指出这对加速器本身是巨大的浪费，
> 加速器只需要保证平行场，应该像反射镜一样用屏蔽罩+多级中空电极，而不是铺满全domain的理想平面。
> 本节记录完整过程：圆柱形屏蔽罩尝试失败→在独立最小模型里改用方形验证成功→整合回完整模型。

| 发现/教训 | 说明 |
|---|---|
| **⚠️⚠️关键物理约束：不同电压的电极(包括接地屏蔽罩)之间不能直接接触——这不是几何整洁问题，而是真实的电学短路** | 圆柱形屏蔽罩的最初实现让环电极的外径、grid1/grid2的平面半径都跟屏蔽罩内径**完全相等**(直接接触)，结果`boundary count`异常(3、之后加环变成9，应为1)，无场漂移区出现残留场泄漏(-559到-243V/m，应为0)。**教训**：屏蔽罩(接地0V)和环/栅网(各自不同电位)之间必须留出真正的真空间隙(哪怕只有1-2mm)，这跟反射镜的环紧贴`reflvac`边界不冲突——`reflvac`只是真空边界，不是带电电极，两者不是同一类情况，不能类比套用。但**平面idealized grid(如grid1/grid2本身)可以安全地跟屏蔽罩内径完全贴合**(它是真空内部边界，不是独立的固体导体，不存在"接触短路"问题)——这个区分后来在方形方案里验证成立。 |
| **⚠️圆柱形方案即使加了间隙，`boundary count`异常和场泄漏依然没有完全消除**：加3个中间环后从"仅屏蔽罩"时的count=3恶化到count=9，泄漏场从-559V/m只降到-243V/m左右 | 怀疑根因：加速器物理长度(16.83mm)相对屏蔽罩半径(35mm)的长径比很不利(约0.48)，边缘效应比预期更难压制，圆柱几何下COMSOL自动装配把屏蔽罩表面拆分的方式和选择框窗口产生了未查明的交互。**决定不在复杂完整模型里继续排查**，转而在独立最小模型里换个方向重新验证。 |
| **✅✅✅关键转折：换成方形屏蔽罩+方形环电极(而不是圆柱形)，在独立最小测试模型(`test_square_shield_accel.m`)里一次性验证成功** | 方形对这个"短而粗"的几何(16.83mm长 vs 35mm半宽)明显更友好：`selb_g1`/`selb_g2`边界计数直接就是1(无重叠)，轴上场偏差只有**±0.03%**(vs 圆柱形方案的~4%，好了两个数量级)。**关键原因猜测**：加速器本身的repeller已经是方形(40×40mm)，方形屏蔽罩的"半宽比较"(无需对角线修正)比圆柱形的"半径vs方块对角线"比较更直接、不会有意外的角落超出问题；另外方形的平直侧壁在这种短管几何下可能比圆柱的弧面更利于维持轴上场的均匀性。**方法论教训**：遇到复杂完整模型里反复试错卡住的几何设计问题，换一个独立最小模型、换一个不同的几何基元(方形vs圆柱)重新尝试，往往比在原有假设下死磕更容易找到出路。 |
| **✅整合回完整模型：屏蔽罩(方形，半宽35mm，2mm壁厚)覆盖grid1到grid2整个加速器区域，5个中间渐变方形环电极维持grid1-grid2之间16.83mm间隙的场线性度，bracket区(repeller-grid1,3mm)不需要额外环(长径比已经很小，2端点足够)** | 整合后完整模型验证：边界计数1/1/2/2全部正确，无场漂移区精确为0(z=25-480mm全部-0.0000V/m，无泄漏)，加速器bracket区场偏差~0.003%(159994-160003 vs 目标160000)，第二区偏差~0.3-0.5%(104105-104605 vs 目标104575，比圆柱形方案的~4%好一个数量级但比独立测试的±0.03%略差，可能因为完整模型的网格/邻近反射镜场的相互作用)。 |
| **✅N=5000大样本确认：方形屏蔽罩设计跟之前的平面栅网方案在分辨率上统计等价**(R=2895.6 vs 平面栅网基准3009.3，差异在噪声范围内)，N=100小样本曾显示3902.7(比平面栅网的2913.1"看起来更好")，但这再次印证了本项目反复强调的教训——小样本扫描的"改善"很可能只是统计噪声，必须用大样本复核 | **这次重新设计的真正价值不是分辨率提升(两者物理等价)，而是让加速器的几何设计更符合物理直觉**：屏蔽罩把加速器的电场约束在35mm半宽的有限空间内(仿照反射镜"环栈约束在`ring_outer_r`内"的做法)，而不是让理想化平面铺满几百毫米的仿真域——用户最初指出的"浪费"问题得到了根本解决，而不只是把grid1/grid2缩小到跟entgrid/midgrid一样大小这种权宜之计。 |

---

### 7.33 理想完美场为何"没达到理论极限"：时间量化噪声 vs 真实场瓶颈的定量区分

> **背景**：用户提出两个层层递进的问题——(1) 理想完美场(field_mode='ideal')测出的R是否已经
> 达到了分辨率的理论上限，如果没有，为什么；(2) 真实电极场算出的分辨率为什么还是比理想完美场差，
> 如何进一步逼近。本节用"z0与到达时间的相关性残差分析"这个诊断方法，定量拆解了两个问题的答案。

| 发现/教训 | 说明 |
|---|---|
| **✅诊断方法：把`corr(z0,detTime)`和"线性/二次多项式拟合掉z0依赖后剩余的标准差"打印出来，直接判断到达时间的分散有多少能被z0(进而KE)解释，多少是z0以外的其他来源** | 在计算R_resolution之后、`N_plot`小样本重新求解覆盖`sol2`之前，插入诊断代码提取全量`z0=z(1,:)`并与`detTimes`做相关性和多项式拟合残差分析。**踩坑**：必须在`N_plot`重新求解**之前**做这个分析——之前误用`mphparticle(model,'dataset','pdset1')`事后查询时，`pdset1`所指向的`sol2`已经被绘图子集的N=50重新求解覆盖，导致分析对象实际上是N=50而非真正的N=5000统计样本，得出的相关系数不可信。 |
| **✅✅✅回答问题1：理想完美场(5ns时间步长)没有达到理论极限——根因是时间量化噪声主导了残差，不是物理效应** | 理想完美场诊断(N=5000, 5ns)：`corr(z0,detTime)=-0.2587`，标准差3.61ns，线性拟合后残差3.49ns，二次拟合后3.44ns——z0只解释了约9%的方差！由于理想场里`Ex=Ey=0`处处成立，z方向运动理论上应该**完全**由z0决定(与x0,y0,vx0无关)，90%无法被z0解释的方差只能是数值/离散化噪声。**验证**：把精细时间步长从5ns缩到1ns(N=1000)，R从4117.6暴涨到**12957.5**，几乎完全匹配用`flight_time()`直接计算的理论预测(**R_theory≈13572**，对K0±80eV均匀分布的KE直接积分std(T)得到)，仅差约4.5%。**教训**：随着设计不断修正、真实的物理分散越来越小，之前"够用"的输出时间分辨率(5ns)可能变得不够用了——每次重大设计改进后，都应该重新检查输出时间步长是否仍然远小于当前的真实物理时间尺度，不能一直沿用旧的"验证过"的设置。 |
| **✅✅回答问题2：真实场vs理想场的差距是真实的场精度问题，不是数值噪声——1ns精细步长下真实场R几乎不变(2895.6→4027.8, 主要是N从5000降到1000的统计噪声，不是1ns带来的系统性提升)，而`corr(z0,detTime)`高达-0.973** | 真实场诊断(1ns, N=1000)：`corr(z0,detTime)=-0.973409`(远强于理想场的-0.26)，二次拟合后残差0.647ns(比理想场同口径的0.766ns还略小，说明"z0以外的其余噪声"量级两者相近，可能是同一个数值噪声本底)。**结论**：真实场的R被限制住的真正原因是z0(即KE)到达时间的**映射关系本身**跟理论曲线有系统性偏差(哪怕用二次多项式拟合都拟合不掉)，这个偏差来源于电极场本身的~0.3-0.5%残留误差(尤其是加速器第二段104105-104605 V/m vs 目标104575V/m，以及反射镜环栈场的残留偏差)，而不是CPT求解器的时间离散化精度不够。**如何进一步逼近理想场**：需要继续压低电极场本身相对理论的偏差(比如继续微调`bore_r`/环间距分布，或者提高加速器屏蔽罩+环电极的场精度)，而不是简单加密时间步长(那只对理想场有效，对真实场基本没用)。 |
| **教训：量化"物理分散"与"数值噪声"哪个占主导，`corr(z0,detTime)`+多项式拟合残差是一个通用、低成本的诊断手段** | 不需要额外的仿真参数扫描，只需要在已经跑出来的一次结果里做事后统计分析即可区分"进一步压缩时间步长是否有意义"(理想场：有意义，能大幅提升)和"是否该去修场本身"(真实场：该修场，压时间步长没用)——这个判断方法可以推广到任何"结果比预期差，不确定是数值精度问题还是物理/几何精度问题"的场景。 |

---

### 7.34 定位真正的分辨率瓶颈：反射镜环栈场 vs 加速器场，谁的贡献更大 + 环电极几何中心对齐bug修复

> **背景**：§7.33定位了真实场vs理想场的差距来自场本身的~0.3-0.5%残留误差，但没有区分是加速器
> 第二段(104575V/m目标区)还是反射镜环栈场造成的。本节用"选择性理想化"的方法把两者拆开定量对比，
> 同时修复了一个环电极实体几何中心与理论电压计算点不对齐的bug。

| 发现/教训 | 说明 |
|---|---|
| **⚠️⚠️真实bug：反射镜环栈(`ring1_k`/`ring2_k`)的`Cylinder`几何体`pos.z`是圆柱**底面**中心而不是环本身的几何中心，导致环的实际物理中心比计算理论电压所用的z值偏移了半环厚(0.5mm)** | 环用`h='1[mm]'`且`pos={...,zk_expr}`(zk_expr是理论电压对应的z位置)——COMSOL的`Cylinder`图元`pos`是**底面圆心**，圆柱沿z轴正方向延伸`h`，所以环实际跨度是`[zk,zk+1mm]`，真实几何中心在`zk+0.5mm`，但`Vk_expr`(该环应有的理论线性电压)是按`zk`算的，两者错开0.5mm。**对比**：加速器自己的环(`accelring_k`)用`Block`几何(`pos`是角点不是中心)，早就用`[zk_expr '-0.5[mm]']`正确地把物理中心对准了zk，本次只需要给反射镜的`ring1_k`/`ring2_k`补上同样的偏移。环间距约33-50mm，0.5mm偏移约占1-1.5%——单看不大，但Mamyrin理论对二阶聚焦的场线性度要求极高，这类系统性小偏移会直接侵蚀掉宝贵的分辨率余量。**教训**：任何"实体电极的电压按某个理论z值计算"的设计，都要显式核实这个z值是不是电极的**几何中心**，而不是COMSOL图元自身的定位锚点(不同图元的锚点约定不同：`Block`是角点，`Cylinder`是底面圆心，容易在混用两种图元时踩坑)。 |
| **✅✅✅用"选择性理想化"隔离加速器与反射镜各自对分辨率的贡献：扩展`field_mode`支持`'ideal_accel'`(只让加速器区域用理论场，反射镜保持真实场)和`'ideal_reflectron'`(反之)** | 实现：CPT力表达式里，加速器区域(z<L_accel)和反射镜区域(L_flight≤z<L_flight+L_refl)可以独立选择`es.Ez`(真实)或分段常数理论值，通过两个布尔开关(`use_ideal_accel`/`use_ideal_refl`)组合出全部4种模式(`real`/`ideal`/`ideal_accel`/`ideal_reflectron`)。 |
| **✅✅✅结论(1ns步长，N=500，环心bug已修复)：反射镜环栈场的精度是绝对主导的瓶颈，加速器场的残留误差几乎不影响最终分辨率** | 全真实场基准`R=5969.6`；只让**加速器**理想化(反射镜仍真实)：`R=5733.0`(几乎没变化，甚至因采样噪声略降)；只让**反射镜**理想化(加速器仍真实)：**`R=12852.7`**(几乎完全恢复到理论上限~13572，只差约5%！)。**结论清晰无歧义**：加速器自身的~0.003%(bracket区)到~0.5%(第二段)场偏差对最终分辨率几乎没有可测量的影响，而反射镜环栈场的同量级偏差却是决定性的限制因素。**物理解释**：三栅加速器的"到达时刻与z0无关"设计本身对小的场扰动很鲁棒(此前用`corr(z0,tGrid2)`验证过其时间聚焦的稳健性)，而反射镜的Mamyrin二阶聚焦需要同时满足两个耦合的精确条件，场的微小非线性会直接破坏这个精细抵消。**下一步优化方向应该只聚焦在反射镜环栈场本身**(继续优化`bore_r`/环间距分布/环数)，加速器部分已经足够好，不需要再投入精力。 |
| **✅综合效果：环心对齐修复(几何bug) + 1ns时间步长(消除量化噪声掩盖，§7.33已确认此步长切换对真实场也有实质帮助) 共同使真实场分辨率从基准的R=2895.6(N=5000, 5ns, 环心未修)提升到R=6581.6(N=1000, 1ns, 环心已修)，翻倍以上** | 两个改进是独立、可叠加的：环心修复消除了一个真实的系统性场偏差来源；1ns步长消除了数值层面掩盖真实物理精度的量化噪声——在环心修复之前，1ns对真实场的改善不明显(§7.33测的是修复前的状态)，但环心修复之后，物理分散变小、跟量化噪声的相对量级更接近，此时切换到1ns才真正显现出实质性提升。**教训**：多个改进措施要按顺序生效检验——先修真实的物理/几何bug，再检查数值精度是否跟得上改进后的物理精度，两者顺序颠倒可能会让某个改进的效果被另一个问题掩盖而误判为"没用"。 |

---

### 7.35 分辨率排查方法论速查：从"结果比预期差"到"定位具体瓶颈"的标准流程

> **背景**：§7.30/§7.33/§7.34分别在各自的具体调试过程中使用了"理想场对比"、"corr(z0,detTime)诊断"、
> "选择性理想化隔离"等技巧，但这些技巧本身分散在叙事里。本节把它们整理成一套**按顺序执行、每步
> 都有明确判断标准和下一步指引**的标准流程——遇到"分辨率不达预期"类问题时直接照着走，不需要
> 重新摸索该用什么方法诊断，可以节省大量时间。

**总体思路**：把"CPT力表达式"设计成可以按区域(每个器件/每段场)独立切换"真实FEM场"或"理论闭式解场"
(`if(z<...)`分段+布尔开关组合)，配合"z0-到达时间相关性"这个对1D(Ez-only)系统而言极强的诊断信号，
可以用很少的几次仿真把"哪里出了问题"和"是数值精度还是物理精度问题"都定位清楚，而不需要盲目调参。

| 步骤 | 怎么做 | 怎么判断/下一步 |
|---|---|---|
| **①全理想化对比**(`field_mode='ideal'`风格) | 把CPT力表达式里所有区域的`es.Ex/Ey/Ez`全部替换成分段常数的理论闭式解值(`Ex=Ey=0`，`Ez`按各区域理论场强取值)，其余(离子源、探测器、几何)不变，跑一次得到`R_ideal` | 若`R_ideal`远高于`R_real`(比如几倍以上)：确认瓶颈在**电极场精度**本身，继续走②③；若两者接近：瓶颈可能不在场精度(比如离子源能散设置、探测器判定逻辑、理论模型本身有问题)，需要换个方向排查 |
| **②`corr(z0,detTime)`+多项式拟合残差诊断**(在**每次**仿真的R计算完之后立即做，不只是在①里做) | 在算完`R_resolution`之后、任何"用小N重新求解覆盖`sol2`"的操作(比如给绘图用的子集重新求解)**之前**，用当次求解的全量粒子数据算`corr(z0,detTime)`，并分别做1次/2次多项式拟合`detTime`对`z0`，看残差std相对原始std的收窄程度 | 若残差std远小于原始std(即`corr`绝对值大，比如>0.9)：分散主要由z0(进而KE)解释，是**真实的物理/几何效应**；若残差std跟原始std差不多(`corr`绝对值小，比如<0.3)：z0解释不了大部分分散，很可能是③里的数值噪声或未知的其他来源，优先查③ |
| **③时间步长敏感性测试**(5ns vs 1ns，同一个`field_mode`，N用小一点比如500-1000省时间) | 只改CPT输出`tlist`的精细步长，其余不变，对比R和corr(z0,detTime)的变化 | 若1ns下R大幅提升(几倍)且corr绝对值显著增强：确认**量化噪声**是当前瓶颈，后续同类测试都要用更细步长，否则测出来的"改进/退步"可能只是噪声；若1ns几乎不变：排除数值步长，瓶颈是真实场/几何精度，回到④ |
| **④选择性理想化，逐个器件隔离**(需要①里的分段CPT力表达式支持"哪些区域用真实场、哪些用理论场"独立开关) | 系统由多个器件(比如加速器+反射镜)组成时，依次只让**其中一个**器件的区域用理论值、其余保持真实FEM场，比较各自的R提升幅度 | 哪个器件"单独理想化后R大幅回升"，那个器件就是真正的瓶颈——其余器件即使场精度也不完美，但对最终R贡献可以忽略，不需要再投入精力去优化它们 |
| **⑤直接查询实际场值vs理论值**(`mphinterp`沿离子实际轨迹或轴线取点) | 定位到具体器件后，沿z(必要时也沿离子实际的x,y偏移路径)逐点查询`es.Ez`，跟理论分段常数值算相对偏差百分比 | 找到偏差**最大的具体位置**(通常在环与环之间、或器件边缘)，为后续物理修正(调环数/环间距/`bore_r`/环心对齐等)提供直接目标 |
| **⑥几何完整性检查**(`boundary count`打印，任何选择集/electrode相关改动后都要做) | 每个应该是"单一平面"的理想化栅网选择集，打印其`entities()`数量，确认等于预期值(通常是1或2，视z窗口是否横跨两个相邻真空段而定) | 数值不等于预期：几乎总是选择框窗口(z或x,y范围)跟相邻边界(另一个电极/释放体积/屏蔽罩)发生了意外重叠，导致电位被静默错误分配(不会报错)——先查这个，比盲目怀疑网格/求解器精度快得多 |
| **代码实现要点**：CPT力表达式的分段理想化写法、诊断代码的插入位置 | `Ez_expr = sprintf('if(z<L_accel,%s,if(z<L_flight,0,if(z<L_flight+L_refl,%s,es.Ez)))', accel_piece, refl_piece)`，`accel_piece`/`refl_piece`各自可以是`'es.Ez'`(真实)或对应区域的理论闭式解字符串，配合`use_ideal_accel`/`use_ideal_refl`两个布尔开关组合出全部模式；`corr(z0,detTime)`诊断代码必须插在`R_resolution`计算之后、`N_plot`小样本重新求解`sol2`之前(否则查询到的会是被覆盖后的小样本数据，参见§7.33的踩坑记录) | — |

---

### 7.36 反射镜环栈场逼近理论值的尝试：发现"边界沉降效应"，网格修正无效，扩大孔径也未必有效

> **背景**：§7.34确认反射镜环栈场精度是分辨率的绝对主导瓶颈后，本节尝试用§7.35的方法论(步骤⑤
> 直接查场值)进一步定位偏差的具体模式，并尝试了两个方向的修正——都得出了有价值但出乎意料的结论。

| 发现/教训 | 说明 |
|---|---|
| **✅✅用`mphinterp`逐点扫描stage1/stage2整个区间(而不是只挑几个点)，发现偏差是一条光滑、单调的曲线，不是环间距导致的锯齿波纹** | Stage1(entgrid→midgrid)：偏差从入口附近的+0.58%平滑降到出口附近的+0.42%；Stage2(midgrid→backplate)：偏差从入口附近的+0.06%平滑升到出口附近的+0.58%。**关键规律**：两段的偏差都在**共享的midgrid附近最小**，在**各自的另一端(entgrid/backplate)附近最大**。查了几个ring的具体z位置(如ring2_1在z=750.5)，偏差曲线在这些位置**没有任何拐点或锯齿**，证明这不是"环的离散化不够密"的问题。**判定标准**：偏差幅度似乎跟"该边界处的场跳变幅度"相关——entgrid处场从0跳到9443V/m(跳变大)、backplate处场终止(跳变大)，两处偏差都是~0.58%；midgrid处场只从9443V/m变到9155V/m(跳变小，~3%的相对变化)，偏差最小到0.06%。**命名为"边界沉降效应"**：有限长度的环栈在靠近"大跳变边界"处，没法完美复现理想无限大平行板场，这个偏差在离开边界后逐渐"沉降"到更小的值，猜测沉降的特征长度跟`bore_r`/`ring_outer_r`(孔径尺度)有关，而不是跟环间距(离散化尺度)有关。 |
| **✅诊断离轴均匀性**：在stage2中点测试`x_refl_center±5mm`范围内的偏差，结果几乎不变(0.348%→0.349%) | 确认偏差**跟离子实际路径的离轴距离无关**——不是常见的"孔径透镜"效应(那种效应通常随离轴距离增大而增大)，进一步支持"边界沉降"是一个整体几何效应，不是局部的孔径-离轴耦合效应。 |
| **⚠️尝试修正mesh selection的一个真实bug(`selreflregion`的`top`参数从502改为`L_flight+L_refl+2`，覆盖整个反射镜而不是入口2mm)，但对场精度**完全没有影响**(偏差曲线数值逐位相同)** | 之前一直以为`top=502`+`pos.z=500`意味着这个精细网格选择区只覆盖了z=[500,502]这2mm，本该覆盖整个500mm的反射镜——这确实是一个参数设置错误(数值上不符合"整个反射镜都要精细网格"的设计意图)，修了是对的，但**实测偏差曲线在修正前后完全一样**，说明COMSOL物理特征驱动的自动网格加密(环本身1mm厚的实体特征)在这个区域已经足够密，这个显式选择区域并没有起到额外作用。**教训**：发现一个"参数看起来不对"的bug，修正它本身是有价值的(代码更清晰、未来换用更大反射镜时不会有同样问题)，但不能想当然认为"修了这个bug就应该能看到效果"——网格相关的问题，最好的验证方式还是直接测场值/测R，而不是单看Nelem数字是否变化(本例中Nelem修正前后也完全没变，因为几何特征驱动的自动加密早就覆盖了这个区域)。 |
| **⚠️尝试扩大`bore_r`/`ring_outer_r`(250/350mm→300/390mm，猜测边界沉降的特征长度正比于孔径，扩大孔径应该能让沉降更快完成)，N=100看似有大幅改善(R从7143.6到10015.0)，但N=1000严格复核后发现是假象** | N=100测试`ring_outer_r=400mm`(还没退到390mm前)时`selb_midgrid boundary count`跳到4(应为2)——因为400mm恰好和entgrid/midgrid自身的WorkPlane半宽(400mm)精确重合，属于第二次踩到"精确重合"类bug(参见§7.32同类教训)。退到390mm(留10mm余量)修好这个bug后，N=100测得R=6108.9(此时已经看不出明显改善)，N=1000严格复核：**R=5637.7，二次拟合残差0.6386ns，跟250/350mm基准(R=6581.6，残差0.6258ns)相比没有改善甚至略差**。**教训**：①任何"看起来很有希望"的小样本改善，必须用大样本复核，这是本项目第N次踩到同一个坑(参见§7.30"小样本参数扫描的改善很可能只是统计噪声")；②§7.31当时得出的"bore_r越大越好"结论，是在**修正L_total和环心对齐这两个更大误差源之前**得出的——当时那两个更大的误差掩盖了"扩大孔径"这个较小效应的真实作用方向，现在这两个大误差源都修复后，剩余误差预算小了很多，"扩大孔径"这个招数在新的误差量级下未必还管用，甚至可能因为孔径变大后"边界沉降"的绝对影响范围变大、跟固定的300mm级驱动区长度产生了新的不利耦合。**结论：不能假设旧的优化方向在修复了根本性bug之后依然成立，每一轮大的修复之后，之前"验证过"的参数优化结论都应该重新审视，而不是想当然沿用。** |
| **现状与待办**：边界沉降效应已经被清楚地描述(光滑、跟离轴无关、幅度跟场跳变大小相关)，但根治它的具体办法还没找到——网格加密和简单扩孔径都不是正确答案 | 值得尝试但本次时间预算内未及展开的方向：①在entgrid/backplate附近**局部**增加"过渡环"(不是均匀加环，而是专门在跳变最大的边界附近插入额外的渐变控制点)；②反过来利用"偏差光滑且可预测"这个特点，**反向修正环电压**(不用理论线性公式的原始值，而是提前把这条已知的沉降曲线的偏差"减去"，让环的实际设定电压主动补偿这个已知效应)；③重新考察`entgrid`/`midgrid`(400mm半宽) vs `backplate`(严格等于`ring_outer_r`)这两类边界的**尺寸不对称**是否是沉降幅度不同的部分原因，统一二者的相对尺寸关系再测一次。 |

---

### 7.37 CPT输出tlist分段加速(耗时降约33%，精度不变) + 飞行管圆柱化统一entgrid/midgrid/grid2/backplate尺寸关系

> **背景**：用户要求(1)统计各部分耗时并在不损失精度的前提下缩短计算时间，(2)统一entgrid/
> midgrid/backplate的尺寸关系。本节记录两个改动的具体实现和验证结果。

| 发现/教训 | 说明 |
|---|---|
| **✅耗时构成**(N=1000, 1ns步长基准)：静电场求解~24-26s(占比小)，CPT粒子追踪求解~233-349s(占绝对大头)——优化目标明确锁定在CPT求解本身 | 电场求解耗时基本固定(跟粒子数无关，只跟网格规模有关，已在早期章节确认)，CPT耗时随粒子数N线性增长，且强烈依赖`tlist`里存储的时间步总数——这是本次优化唯一有意义的杠杆。 |
| **✅✅速度优化：把均匀1ns精细步长(覆盖0到3×单程飞行时间≈53us，共约53580步)改成4段式tlist——只在真正有"力"作用的窗口用1ns，中间纯漂移("无聊")窗口粗化到500ns** | 离子的全过程分四段：①加速器瞬态(0-0.545us，有力，需要精细)；②漂移到反射镜(0.545-~8.3us，无力，可以粗)；③反射镜往返+返程漂移+探测(~8.3-30us附近，有力+关键探测事件，需要精细)；④探测之后(不再关心，可以粗)。**实现**：`range(0,1e-9,2e-6) range(2.5e-6,500e-9,6e-6) range(6e-6+1e-9,1e-9,33e-6) range(33.5e-6,500e-9,Tsim)`——1ns窗口只覆盖0-2us和6-33us(共约2000+27000=29000步)，比原来53580步减少约46%。**实测(N=1000)**：CPT求解时间从348.88s降到233-235s，**减少约33%**；精度指标(R=5769-6581之间波动，二次拟合残差0.632-0.636ns)跟优化前几乎完全一致，确认没有精度损失。**关键教训**(呼应本项目早前的失败教训)：粗化窗口的边界必须精确覆盖住"有力"的物理时间窗口，不能只凭直觉估计——之前(§7.29附近)有过把粗化窗口不小心盖住加速器瞬态导致分辨率暴跌的教训，这次通过先算清楚每个阶段的物理时长(用速度反推各段耗时)再划分段落边界，一次成功。 |
| **✅✅飞行管从方形Block改成圆柱形Cylinder，统一entgrid/midgrid/grid2/backplate的尺寸关系**：新增参数`flight_tube_r=ring_outer_r+30mm`，飞行管半径用它；grid2(加速器出口栅网)从"方形、跟accel_shield_half绑定"改成"圆形、跟flight_tube_r绑定"，与飞行管入口栅网**合并成同一个大圆形栅网**；entgrid同样改圆形、绑定flight_tube_r；midgrid改圆形、绑定ring_outer_r(与backplate完全一致) | 这是用户指出的正确做法：不同电压的电极/栅网之间要靠"飞行管内径比它们大一些"的方式维持间隔，类似加速器自己的方形屏蔽罩，而不是任意指定一个尺寸。**关键教训是topology(拓扑)要求**：WorkPlane做的理想化栅网必须完整"切穿"它所嵌入的真空块的整个截面，否则边缘会留下一圈没被覆盖的"框"，破坏内部边界的拓扑——这也是为什么当初仅仅把entgrid/midgrid缩小到匹配`ring_outer_r`(比原accelflightbox的800mm小)会直接搞坏无场区(从精确0变成有残留场)的根本原因：必须同步把飞行管本身也缩小/改形状来匹配，不能只改栅网。 |
| **⚠️配套修正：加速器方形屏蔽罩的z范围要精确止于grid2所在的z=L_accel，不能像之前一样多出1mm余量** | grid2现在是跨越整个飞行管半径的大圆盘，如果加速器屏蔽罩的z范围超过L_accel(之前多留了1mm)，grid2这个大圆盘就会穿过屏蔽罩自身的实体壁材料(半径accel_shield_half到accel_shield_half+accel_shield_wall)，造成"理想化边界嵌入实体材料内部"的拓扑矛盾。修正：屏蔽罩改成精确止于`L_accel`(不再是`L_accel+1mm`)。 |
| **✅验证结果**：`selb_entgrid`/`selb_midgrid`边界计数恢复正常(2/2)，无场漂移区精确为-0.0000V/m(完美，跟修正前一样)，`selb_grid2`边界计数变成3(不是1)——判定为良性重叠 | grid2(现在的大圆盘，0V)与加速器屏蔽罩自身端面(同样0V)在z=L_accel处恰好重合——两者电位相同，不构成"不同电压接触"问题，只是多出2个额外的边界ID，实测场值和分辨率均未受影响(R、corr(z0,detTime)都在正常范围内)。**教训**：判断一个"boundary count异常"是否真的有害，最终还是要看两个方面——①涉及的两个对象电位是否相同(相同则通常无害)，②实测的场值/无场区检查/R是否受影响——不能仅凭数字异常就断定一定要修，但也不能仅凭"电位相同"就完全不查，两者都要看。 |

---

### 7.38 模型对称性核查：发现无场区(飞行管)与反射镜不在同一轴上的真实bug，统一轴线并全面核查实体完整性

> **背景**：用户指出无场区(飞行管)、反射镜和反射镜相关部件"不在一个轴上"，要求检查模型对称性，
> 并确保所有部件都有实体画出来。本节记录发现的真实轴线错位bug及修复。

| 发现/教训 | 说明 |
|---|---|
| **⚠️⚠️真实bug：飞行管(accelflightbox，圆柱)以x=0,y=0为轴，而反射镜(rings/backplate/reflvac)以`x_refl_center=41.2mm`为轴——两个不同的轴** | `x_refl_center=41.2mm`是历史遗留参数，早期设计里飞行管还是方形Block(没有单一对称轴概念)时，把反射镜的轴刻意偏移到"离子实测轨迹落点"(因5eV横向初速在500mm漂移后累积约41mm横向偏移)，让离子尽量落在反射镜孔径的中心。**现状复核**：`bore_r=250mm`远大于这41mm偏移，飞行管现在也已经是圆柱形(§7.37)，有了明确的单一对称轴——继续保留这个历史偏移已经没有必要，且造成了飞行管与反射镜"不同轴"的真实不对称。 |
| **⚠️连带发现：`midgrid`(反射镜stage1/stage2边界栅网)的`Circle`创建时没有显式指定位置，隐式默认落在WorkPlane原点(0,0)，而不是应该对齐的`x_refl_center`(环栈自身的轴)——这是一个独立于上面的、额外的错位bug** | 之前`x_refl_center=41.2mm`时，`ring1_k`/`ring2_k`/`backplate`/`reflvac`都显式定位在`x_refl_center`，唯独`midgrid`(§7.37新增的圆形栅网)漏掉了这个显式定位，静默落在(0,0)——即使在修正主轴线之前，`midgrid`本身就已经和它两侧的环栈不同轴了。**教训**：任何新增的几何体在设置位置参数时，都要对照"它应该跟哪个已有部件对齐"逐一显式核实，不能依赖图元的隐式默认位置(WorkPlane/Circle的默认原点未必是设计意图中的轴)。 |
| **✅修复：`x_refl_center`重置为`0[mm]`，统一加速器+飞行管+反射镜到同一根轴上；`midgrid`的`Circle`显式设置`pos={x_refl_center,0}`(即使当前数值恰好等于默认值，也不再依赖隐式默认)** | 修复后完整模型验证(N=1000)：无场漂移区依然精确为-0.0000V/m，`R=5564.5`(N=100时`R=6090.0`，同量级)，`corr(z0,detTime)=-0.971`(强，正常)，二次拟合残差`0.588ns`(比修正前的`0.636ns`还略好，说明轴对齐后场精度没有变差，甚至可能略有改善)。 |
| **⚠️连带发现2处硬编码`41.2`(不是参数化的`x_refl_center`)，需要分别甄别处理** | ①`selreflregion`(反射镜精细网格选择区)的`pos`用了硬编码`[41.2 0 500]`——这个**应该**跟着`x_refl_center`走(它标记的是反射镜环栈本身所在的位置)，改成用`p.evaluate('x_refl_center','mm')`动态取值，避免`x_refl_center`以后再变动时又变成陈旧的硬编码。②"无场区场检验"诊断代码里的`coord=[41.2*zc/500;0;zc]`——这个`41.2`**不应该**跟`x_refl_center`挂钩，它代表的是离子自身实测的横向漂移速率(5eV横向初速在500mm处的实际落点)，是一个独立于"反射镜几何中心设在哪"的物理量，两者历史上数值相同只是巧合(早期`x_refl_center`就是刻意设成等于这个漂移落点)。**教训**：两个数值恰好相等不代表它们是"同一个概念"，混淆两者、想当然把其中一个替换成对方会引入新的错误——命名和注释里要把"物理测量值"和"几何设计选择"这两类参数明确区分开，不能因为数值巧合就认为可以互相替代。 |
| **✅全面核查所有几何部件的实体完整性**：逐一确认repeller、accelshield、accelring_1~5、ring1_1~5、ring2_1~5、backplate、detector均为**实体求解体**(Block/Cylinder做Difference得到的固体)；grid1/grid2/entgrid/midgrid均为**零厚度理想化内部边界**(WorkPlane+Union+intbnd，有面无体，符合"栅网离子可穿透"的设计要求)；accelflightbox/reflvac/relvol为**真空容器体**(非带电实体，正确) | 确认没有任何部件是"隐式/未画出"的——所有电极和栅网都能在`soliddoms`(固体列表)或`gridspecs`(理想化栅网列表)里找到对应条目，且都在几何构建阶段(`geom1.run`)之前完成`selresult`设置，能够被后续的选择集正确引用。 |

---

### 7.39 澄清L_flight参数含义 + 修正几何使L1=L2=500mm严格成立，反射镜理论重新求解

> **背景**：用户追问"L_flight=500mm"是否等于反射镜求解器里的无场漂移长度L，
> 经仔细核实后发现两者不是一回事，进而要求修改几何使L1=L2=500mm严格成立，
> 并据此重新验算反射镜的E1/E2/V_mid/V_mirror设置。

| 发现/教训 | 说明 |
|---|---|
| **⚠️参数命名误导**：`L_flight=500mm`实际上是entgrid的**绝对z坐标**(从repeller的z=0算起)，不是无场漂移区本身的长度 | 加速器占用了这500mm里最开始的`L_accel=19.83mm`(离子在grid2处才真正达到恒定速度)，探测器又不是恰好放在z=L_accel(为避免跟grid2边界重合，偏移了0.3mm放在`L_accel+0.3mm`)——所以真正的无场漂移长度是`L1=L_flight-L_accel`(去程)和`L2=L_flight-(L_accel+0.3mm)`(回程)，两者都比`L_flight`本身小。旧设计下`L1=480.17mm`，`L2=479.87mm`，`L_total=960.34mm`，都不等于表面上的`L_flight=500mm`或`2×L_flight=1000mm`。 |
| **✅代码与文档双重确认`L`的定义**：`reflectron_dual_stage_solver.py`的docstring明确写"L : 总无场漂移距离 (m) = L1 + L2"；`单次反射TOF二级反射镜等时聚焦推导.docx`第30行"记 L ≡ L₁+L₂"、第80行再次重申 | 排除了"L是(L1+L2)/2"的误解可能——L就是L1+L2的**和**，不是平均值。这也验证了d1<L/4这个存在性约束里的L同样是这个和。 |
| **✅✅修正几何，让L1=L2=500mm严格成立**：`L_flight`从固定`500[mm]`改成表达式`L_accel+500[mm]`(=519.83mm)，配合探测器仍在`L_accel+0.3mm`不变 | 这样`L1=L_flight-L_accel=500.00mm`精确成立；`L2=L_flight-(L_accel+0.3mm)=499.70mm`(仅差0.3mm，来自避免探测器与grid2边界重合所需的微小偏移，相对500mm可忽略不计)。`L_total=L1+L2=999.70mm`，理论求解时按精确的`L=1.0m`处理(0.3mm残差不值得带入闭式解)。**关键点**：因为脚本里所有z坐标(z_mid_expr、ring2位置、backplate、entgrid相关选择集等)全部以参数`L_flight`表达式引用，而非硬编码数字，这个改动能正确、一致地传播到整个几何、网格选择和CPT理想场表达式，无需逐处手动修改。 |
| **✅✅重新求解反射镜理论参数**：用`reflectron_dual_stage_solver.py`以`U0=2000eV, d1=0.2m, L=1.0m`重新求解，得到`E1=9333.33V/m, E2=8948.26V/m, U1=1866.67V`；`d2=300mm`时`V_mirror=U1+E2*d2=4551.15V`。`V_mid`(=U1)从`1888.69V`改为`1866.67V`，`V_mirror`从`4635.16V`改为`4551.15V`。`d1/L=0.2<0.25=L/4`，约束仍满足，且比旧设计(`d1/L_total=200/960.34=0.208`)留有更大裕量。环电极电压(`accelring_k`/`ring1_k`/`ring2_k`)都是`V_mid`/`V_mirror`的线性插值表达式，无需单独修改E1/E2数值。 |
| **✅✅验证结果(N=1000)**：无场漂移区依然精确为-0.0000V/m；**R=7752.6**(N=100时R=7960.7，同量级)，corr(z0,detTime)=-0.944(强)，二次拟合残差0.6417ns——相比旧的L_total=960.34mm设计(R≈5565-6582)，**分辨率有明显提升** | 这印证了"让实际几何严格匹配理论闭式解假设的整数值参数(L1=L2=500mm)"比"让理论闭式解去将就一个不规整的实际值(L_total=960.34mm)"更有利——虽然两种做法在数学上都是自洽的(只要L值代入求解器时保持一致)，但当设计目标本身就是"L1=L2=500mm"这样的整数值时，直接把几何调整到匹配这个目标，比事后用一个"凑出来"的960.34mm去反推，更符合设计意图，也让后续任何人核对这个模型时更容易验证。**教训**：当理论与实际出现偏差时，第一反应不应该只是"把理论参数换算成匹配实际的数字"，还应该反问"实际的这个偏差本身是不是可以/应该消除"——如果偏差源头(如本例中的探测器偏移量)本身很小且非本质，直接修正几何比长期背着这个偏差重新推导理论更彻底。 |

---

### 7.40 探测器归位：让L2也严格等于500mm，发现并解决与grid2的圆盘重叠冲突

> **背景**：§7.39把L1修正为严格500mm，但L2因探测器的0.3mm偏移仍差0.3mm。
> 用户要求探测器归位让L2也严格等于500mm。

| 发现/教训 | 说明 |
|---|---|
| **⚠️发现真实的几何冲突**：把探测器z从`L_accel+0.3mm`改回精确的`L_accel`(与grid2完全同一z)后，探测器(x=390mm,半径25mm，覆盖x=[365,415]mm)与grid2(现在是以x=0为圆心、半径`flight_tube_r=380mm`的大圆盘)在这个公共z上**存在真实的圆盘重叠**——探测器x=[365,380]mm这一段落在grid2的380mm半径以内 | 这正是当初引入0.3mm偏移量的真实原因(§7.34/7.37的教训)——两个不同电位的平面在完全相同的z上有空间重叠会导致边界拓扑冲突。想要L2严格等于500mm(即探测器z与grid2z完全相同)，就必须先解决这个x,y方向的重叠，不能只在z方向留缝。 |
| **✅修复：探测器沿x方向移出grid2的圆盘范围**：从x=390mm移到x=420mm(覆盖x=[395,445]mm，与grid2的380mm半径有15mm净空)，z同时改回精确的`L_accel` | 由于探测器命中判定是纯粹的**Z穿越时刻检查**(不是真实的x,y碰撞检测——已在之前几轮确认过)，探测器的x位置只影响：①是否与其他电极/栅网发生几何重叠，②建立正确的接地边界条件，两者都不依赖"探测器必须蹲在离子实际落点"。因此把探测器径向移出grid2覆盖范围是安全的，不影响探测逻辑或离子动力学。 |
| **✅验证结果(N=1000)**：`Ndomains`从30降到29(探测器不再与grid2产生额外的域分割，拓扑反而更简洁)；无场漂移区依然精确为-0.0000V/m；**R=7673.4**(N=100时R=7748.6，同量级，与§7.39的7752.6/7960.7属同一水平)；到达时间`30.56045±0.00199us`，与L2=499.7mm时的`30.56044us`几乎完全一致(差距在0.3mm对应的~1ps级，远低于测量噪声) | 这确认了L2从499.7mm精确到500.00mm这最后0.3mm的修正，对分辨率/到达时间没有可测量的影响(本来就该如此，0.3mm/500mm=0.06%)——这次修改的价值主要在于**让模型的实际几何跟理论文档中"L1=L2=500mm"的表述完全一致**，避免以后任何人核对模型时还要解释"为什么L2差0.3mm"。 |

---

### 7.41 验证"只有L1+L2的和影响结果、具体分配无关"这一理论声明——理论+实际几何双重确认

> **背景**：用户要求验证，当L=L1+L2=1000mm保持不变、但L1/L2的具体分配不同时，
> 理论结论(只有和影响结果)是否正确，实际分辨率是否有变化。这是对文档§3"证明：只有
> L₁+L₂之和影响T(U)"这一核心论断的直接实测验证。

| 发现/教训 | 说明 |
|---|---|
| **✅理论侧验证(Python)**：用`reflectron_dual_stage_solver.py`以`U0=2000, d1=0.2, L=1.0`固定，扫描L1/L2分配`(0.5,0.5)、(0.7,0.3)、(0.8,0.2)、(0.99,0.01)、(0.3,0.7)、(0.1,0.9)`——E1、E2、U1完全相同(9333.333333/8948.261471/1866.666667，逐位一致)；用`evaluate_performance`进一步确认T0、dT_dU、d2T_dU2、d3T_dU3、理论R(=8333.22)也逐位一致 | 代码层面的证明是自洽的——闭式解公式里L1、L2只以`(L1+L2)`的组合出现(见docx第22-28行的推导)，数值计算完全印证了这一点。 |
| **⚠️发现实际几何的一个约束**：想在COMSOL里真实构造一个"L1≠L2"的例子，不能简单地" 只改L1或只改L2"——探测器只能放在`[L_accel, L_flight)`这个连续无场飞行管区间内，所以**L2永远不能超过L1**(`L2=L_flight-detector_z`的最大值就是`L1=L_flight-L_accel`，此时detector_z=L_accel)。要构造非对称例子，必须同时调整`L_flight`(改变L1)和`detector_z`(改变L2)，两者联动才能保持`L1+L2`不变 | 选择了`L1=700mm, L2=300mm`(和仍为1000mm)：`L_flight=L_accel+700mm=719.83mm`，`detector_z=L_flight-300mm=L_accel+400mm=419.83mm`(探测器挪到飞行管中段，不再跟grid2共享z，反而更安全)。 |
| **⚠️连带发现并修复一个潜在bug**：探测判定的Z穿越阈值之前是裸的硬编码数字`20.5`，只是"恰好"匹配了旧探测器位置(L_accel+0.3mm=20.13mm)，探测器一旦挪动这个阈值就会跟着失效 | 引入了显式参数`detector_z`，探测器的几何位置和探测判定阈值(`detector_z+0.5mm`)现在都从**同一个参数**读取，不会再出现两处独立硬编码互相脱节的情况。"wasUp"的判定阈值(离子是否已经明显飞过了一半路程再考虑触发)也从硬编码400改成了`detector_z*2`，随着探测器位置自动跟随缩放。 |
| **✅实际几何验证(N=1000)**：非对称设计(`L1=700mm, L2=300mm`)测得到达时间`30.56368±0.00220us`，`R=6958.4`；对称设计(`L1=L2=500mm`)测得到达时间`30.56045-30.56332us`，`R=7563.5-7960.7`——**两者在到达时间上几乎完全一致(差距<3ns)，R的差异也完全落在N=100/1000统计噪声的正常波动范围内(整个项目历史上同一设计不同随机种子的R波动本来就有这个量级)** | 这在实际COMSOL全物理场(真实电极几何+CPT粒子追踪)层面，独立确认了理论闭式解的结论——**不是只在理论公式层面自洽，在包含真实几何误差、网格离散化误差的完整仿真里，这个"分配无关性"依然成立**。也再次印证了V_mid/V_mirror完全不需要因为L1/L2的具体分配而重新计算，只要L1+L2这个和不变。验证完成后已改回`L1=L2=500mm`的对称基准设计(保存为`MS_ModelB_RingStack_Final.mph`)。 |

---

### 7.42 飞行管从"共用大栅网"改为"实体封闭端盖"：定位错误的教训 + 简化方案(延长加速器屏蔽罩，全盘无孔端盖) + repeller背板消除场泄露

> **背景**：用户要求把无场区(飞行管)的入口栅网删除，改用"封闭整个屏蔽管"的设计——
> 飞行管一头(反射镜一侧)用接地栅网(entgrid)分割，另一头是纯粹的封闭端，同时要求
> 加回加速器自己的出口栅网以防止其场沿粒子轨道泄露。

| 发现/教训 | 说明 |
|---|---|
| **❌❌第一次尝试严重定位错误**：把"封闭端"直接建在z=L_accel(grid2所在位置，也就是离子的正向飞行路径上)，只留一个匹配加速器孔径的小方孔——结果**100%粒子在z=21.83mm(=L_accel+2mm，端盖厚度处)原地卡死**，0/100命中 | 犯了一个基本方向错误：把"封闭端"理解成了"飞行管入口"（跟反射镜相对的那一头），却没意识到z=L_accel**正是离子必须穿过的正向路径上的一点**，不是飞行管的"另一头"。用户明确纠正："粒子路径不会经过端盖，端盖在加速方向的反方向"——即z=0(甚至更靠后)才是飞行管跟反射镜相对的"另一头"，不是z=L_accel。**教训**：设计"哪端开放、哪端封闭"这类拓扑问题时，必须先画清楚离子的完整路径(0→L_accel→L_flight→反射镜→折返→L_flight→detector_z)，再决定"另一头"具体指哪个z，不能凭直觉/习惯假设。 |
| **✅简化方案(第二次实现，最终采用)**：不在z=L_accel处开孔，而是①把加速器自己的屏蔽罩(`accelshieldO/H`)向后(更负的z方向)延长`accel_shield_back_extra=10mm`，从"齐平repeller背面(z=-1)"变成"包住repeller、往后多出10mm(z=-11)"；②飞行管的封闭端盖改放在**更靠后**的位置(`endcap_gap=3mm`，在屏蔽罩新背面之后)，做成一个**完全不开孔的实心大圆盘**(半径`flight_tube_r`)；③相应地把`accelflightbox`(飞行管真空圆柱)自身也向后延伸，以完整包住这个新端盖 | 由于屏蔽罩延长后**已经在到达端盖之前就结束**，端盖后面不需要再给任何东西"让路"，天然就是一个简单圆盘，避免了第一次尝试里"环形板挖方孔"的复杂结构。`grid2`(加速器自己的出口栅网，用户明确要求加回)恢复成原来的小方形(`2×accel_shield_half=70mm`)，只密封加速器自身出口，不再需要跨越飞行管全截面。**L1/L2代表的正向几何(L_accel、L_flight、detector_z等)完全不受影响**——这次改动只在z<0(加速器背后)增加了结构，不触碰离子实际飞行路径上的任何东西。 |
| **✅验证结果(N=1000)**：100%命中(1000/1000)，到达时间`30.56302±0.00214us`(与之前基准`30.56us`一致)，**R=7154.5**(N=100时R=8025.1，与既有基准范围7154-8025同量级，部分工况甚至更好)，加速器场检验(bracket/grid1-grid2)数值与之前完全一致 | 确认这个"延长屏蔽罩+全盘无孔端盖"的简化设计，在不影响离子正向路径的前提下，成功实现了"飞行管作为一个真正封闭的屏蔽管"的设计意图，分辨率与之前的基准设计相当，没有退化。 |
| **⚠️→✅遗留瑕疵及其修复**：无场漂移区出现小的非零残留场(z=25mm处0.2645V/m，随距离衰减到z=480mm处0.0028V/m) | 推测原因：repeller背面(z=-1)暴露在"屏蔽罩延长部分与端盖之间"的新缓冲真空区里——repeller的X-Y尺寸(40mm)比屏蔽罩孔径(70mm)小，边缘留有15mm宽的环形缝隙连通到这个缓冲区，repeller的脉冲电压可能通过这条缝隙轻微"泄漏"。**修复**：加一块接地方形环板(`repback`，外径匹配屏蔽罩孔径70mm，内孔匹配repeller自身40mm footprint)紧贴repeller背面，彻底封住这条环形缝隙。**修复后实测(N=1000)**：残留场从`0.2645V/m`(z=25mm)降到`0.0137V/m`——**约19倍改善**，衰减也更快(z=480mm处仅`-0.0001V/m`)；`R=7236.0`(修复前`R=7154.5-8025.1`)，100%命中，与既有基准范围完全一致，确认这块背板没有引入任何新问题，纯粹是场精度的改善。残留的极小非零值(0.0137V/m，仍比加速器内部场小6-7个数量级)未继续深挖，视为完全可接受。 |

---

### 7.43 全面加厚屏蔽罩与反射镜环电极：加速器屏蔽罩2→4mm，飞行管新增10mm显式实体壁，环电极1→5mm

> **背景**：用户要求把所有屏蔽罩设计得厚一些——加速器屏蔽罩至少4mm，飞行管至少10mm，
> 同时把反射镜环电极片厚度改成5mm，并注意电极间隙和几何关系是否仍然合理。

| 发现/教训 | 说明 |
|---|---|
| **✅加速器屏蔽罩壁厚**：`accel_shield_wall`从2mm改为4mm，直接改参数值即可，几何构造代码本身无需调整(壁厚已经是参数化的) | 最简单的一处改动——由于`accelshieldO`/`accelshieldH`的尺寸表达式已经用`accel_shield_wall`参数化，只需改这一个数值。 |
| **✅✅飞行管新增显式实体壁**：飞行管(`accelflightbox`)之前**只有隐式接地边界**(靠`selb_outerwall`把它自己的外表面当"墙"，没有真正建模壁材料)，现在新增了一个真实的Cylinder-Cylinder环形壳(`flighttubewall`，半径`flight_tube_r`到`flight_tube_r+flight_tube_wall`，接地)，完整包裹`accelflightbox`的整个z范围(与其保持同一高度/位置表达式，自动跟着联动) | 这个新增的壁**不改变真空内部的场**(仍是同一个`r=flight_tube_r`处的接地0V边界)，只是把原来"只靠边界条件、没有实体材料"的设计换成了有真实壁厚材料的设计，两者物理上等效，但后者更接近真实腔体的几何表达。加入`soliddoms`/`DCmap0`(0V)/`selresult`列表，跟其他接地实体(`accelshield`/`endcap`/`repback`)采用完全相同的处理方式。 |
| **✅✅反射镜环电极加厚**：`ring1_k`/`ring2_k`(stage1/stage2环电极)厚度从1mm改为参数化的`ring_thickness=5mm`，配套把中心对齐偏移量从固定的`-0.5mm`改成`-ring_thickness/2`(即`-2.5mm`)，保持环的真正几何中心始终对齐理论电压计算点`zk` | 环间距(stage1: 33mm一档，stage2: 49.5mm一档)相对5mm厚度依然非常宽裕(间隙28mm/44.5mm)，不需要额外调整环数或间距，仅仅是厚度参数和居中偏移量两处联动修改。 |
| **✅✅验证结果(N=1000)**：无场漂移区残留场进一步降到`0.0071V/m`(z=25mm，比§7.42修复后的`0.0137V/m`更好，衰减到z=480mm处仅`-0.0001V/m`)；**R=11006.6**(N=100时`R=12241.0`)——**相比之前的基准范围(R≈7154-8025)有非常显著的提升**；100%命中，加速器场检验数值与之前完全一致 | 环电极加厚后场精度的显著提升(R提升约40-50%)符合直觉：更厚的环电极在同样的环间距下，相当于用更"实心"的电极环近似理论上连续的线性梯度场，环与环之间"缝隙"占总长度的比例变小，逼近理想线性场的精度自然提高。这也间接印证了§7.36"边界沉降效应"猜想里提到的"环电极几何离散化程度"确实是影响精度的一个真实因素——加厚环电极(在环数不变的前提下)是一个简单有效、之前未曾尝试过的改进方向。 |

---

### 7.44 屏蔽罩统一：延长飞行管屏蔽罩包住反射区，两端全盘封闭，全部电极统一5mm厚，全面实体核查

> **背景**：用户要求把反射区也纳入无场区屏蔽罩的覆盖范围(延长飞行管屏蔽罩，两端都封闭)，
> 屏蔽罩与所有部件保持至少15mm间隙；反射区最后一片电极(backplate)也统一到5mm厚；
> 检查repeller处是否有重复栅网；加速器端盖与主体屏蔽罩合并、厚度一致；全面核查冗余实体。
> 同时约定：以后默认只跑N=100，除非用户明确要求N=1000。

| 发现/教训 | 说明 |
|---|---|
| **✅repeller处栅网排查**：检查`grid1`(z=3mm)与`repeller`(z=[-1,0])的位置，两者不在同一z，没有功能重复 | 结论：不删除repeller——它是提供`V_repeller`脉冲电压边界条件的必需实体，不存在与某个栅网重复的情况。 |
| **✅backplate加厚**：从2mm改为`ring_thickness`(5mm，与环电极统一)，`pos.z`保持不变(仍与`reflvac`末端严丝合缝衔接)，只是往+z方向多延伸了3mm | 简单的参数替换，不影响与`reflvac`的连接关系。 |
| **✅✅延长飞行管屏蔽罩覆盖反射区，两端全盘封闭**：`flighttubewall`(环形壳)的z范围从"只包裹`accelflightbox`"扩展到"从原有背端一直延伸到`backplate`末端+`shield_axial_gap`(15mm)"；新增`endcap2`(全盘无孔圆盘，半径`flight_tube_r+flight_tube_wall`)封住反射镜一侧的末端 | `flight_tube_r=ring_outer_r+30mm`本身已经给环/背板留出30mm径向间隙(大于要求的15mm)；轴向新增`shield_axial_gap=15mm`参数，确保`endcap2`与backplate末端也保持至少15mm间隙。由于所有z坐标全部以参数表达式书写(`L_flight`、`L_refl`、`ring_thickness`、`shield_axial_gap`等)，这个延伸操作没有引入任何硬编码数字。 |
| **✅加速器端盖与主体屏蔽罩合并统一**：`endcap`(加速器一侧端盖)的半径从`flight_tube_r`加宽到`flight_tube_r+flight_tube_wall`，与`endcap2`(反射镜一侧新端盖)保持完全一致的设计(全盘、同样半径覆盖壁厚部分)，两端盖+中间环形壁在物理上构成一个连续、厚度一致的封闭壳体 | 这样两端的"盖子"跟中间的"筒壁"在半径上严丝合缝(都覆盖到壁厚的最外缘)，不会在端盖与筒壁交界处留下缝隙。 |
| **✅验证结果(N=100，本轮起改为默认标准)**：几何构建成功(`Ndomains=34`)，边界计数与之前一致，无场漂移区残留场`0.0090V/m`(z=25mm，与§7.43的`0.0071-0.0137V/m`同量级)，**R=12056.9**，100%命中，加速器场检验数值一致 | 确认延长屏蔽罩、两端全盘封闭、backplate加厚这些改动组合起来没有引入任何新问题，分辨率与§7.43加厚环电极后的基准(R≈11007-12241)保持一致水平。 |
| **✅全面实体核查**：逐一列出当前几何里的所有`geom1.feature.create(...)`调用(`repeller`/`repback`/`accelshield`/`endcap`/`accelring_1~5`/`ring1_1~5`/`ring2_1~5`/`backplate`/`detector`/`accelflightbox`/`flighttubewall`/`endcap2`/`reflvac`/`relvol`/4个理想化栅网WorkPlane)，未发现重复或冗余的实体；也确认了此前几轮设计迭代中被淘汰的旧结构(如更早的"环形板挖孔"式端盖`endcapO`/`endcapH`)已经被完全替换、没有遗留孤立代码 | 这次核查是"设计定稿"性质的收尾检查——确认经过§7.37-§7.44多轮迭代后，当前几何里的每个实体都有明确、唯一的作用，没有历史遗留的死代码或功能重复的部件。 |
| **✅约定变更**：从本轮起，默认只用N=100做验证，不再默认跑N=1000，除非用户明确指定 | 这是纯粹的工作流约定，记录于此避免未来的对话遗忘这个约定——N=100足以确认设计改动没有破坏几何/场/探测逻辑，大幅缩短每轮验证的等待时间；只有在需要精确对比分辨率数值(如理论声明验证、A/B性能对比)时才需要N=1000的统计严谨性。 |

---

### 7.45 飞行管真空体必要性确认 + 三处厚度一致性修复(repeller背板、两端端盖)

> **背景**：用户追问飞行管真空体(`accelflightbox`)是否必须存在；要求加速器后端屏蔽罩
> (`repback`)厚度跟侧面(`accel_shield_wall`)一致；飞行管两侧端盖(`endcap`/`endcap2`)
> 厚度跟圆柱壁(`flight_tube_wall`)一致。

| 发现/教训 | 说明 |
|---|---|
| **✅`accelflightbox`必要性确认**：`accelflightbox`(飞行管真空圆柱，半径`flight_tube_r`)与`flighttubewallH`("挖孔"用的中间几何体，半径也是`flight_tube_r`)形状完全相同，看起来像是重复定义，但**两者角色不同** | `flighttubewallH`只是`flighttubewall`(Difference操作)的`input2`(被减去的部分)，COMSOL的Difference操作默认会**消耗掉**input2对象——减完之后它不再作为独立的域存在于最终装配体里。`accelflightbox`才是真正**独立占据**飞行管内部真空空间的几何体，是CPT粒子追踪和静电场求解真正依赖的域。**结论：`accelflightbox`必须保留**，去掉会导致飞行管内部无任何域覆盖那片空间，仿真无法进行。 |
| **✅`repback`(repeller背板)厚度统一**：从1mm改为`accel_shield_wall`(4mm)，`pos.z`同步调整以保持顶面仍紧贴repeller背面(z=-1mm)，只是新增的厚度往更负的z方向延伸 | 简单的参数替换+位置联动，配套把`repbackH`(挖孔件)的高度和位置也做了相应扩展，确保挖孔依然完整贯穿新的4mm厚度。 |
| **✅✅`endcap`/`endcap2`(飞行管两端端盖)厚度统一**：从2mm改为`flight_tube_wall`(10mm)，与中间的圆柱壁厚度完全一致，形成真正连续、厚度处处相同的封闭壳体 | 端盖变厚后，需要连带**扩大`accelflightbox`和`flighttubewall`自身的z范围**(`z0_shield`/`z1_shield`)，确保这两个新增的、更深/更远的端盖仍然被真空体和环形壳完整包裹住——这是这几轮设计里反复出现的教训："内部实体必须被其外围的真空/壳体完全包住"，每次改动某个内部实体的尺寸，都要连带检查外围包裹体的范围是否还够。 |
| **✅✅验证结果(N=100)**：无场漂移区残留场进一步降到`0.0008V/m`(z=25mm，比§7.44的`0.0090V/m`又有明显改善，z=300mm往后已经降到COMSOL数值精度的-0.0000量级)；**R=14532.0**(比§7.44的`R=12056.9`又有显著提升)，100%命中，加速器场检验数值一致 | 这次"厚度一致性"修复带来的场精度提升，比预期更大——推测除了消除repeller周围环形缝隙的残余泄露外，端盖加厚后跟圆柱壁在几何上形成真正连续、无厚度突变的壳体，减少了端盖-壁面交界处潜在的场不连续性。这进一步印证了本项目反复验证的教训：**几何细节(哪怕是看起来次要的"厚度是否一致")对第二阶精度敏感的Mamyrin理论仍有实际、可测量的影响**。 |
| **✅结论**：屏蔽罩系统在经过§7.42-§7.45四轮迭代后已经收敛为一个统一、自洽的设计——加速器方形屏蔽罩(4mm壁厚)+飞行管圆柱形屏蔽罩(10mm壁厚，覆盖飞行管和反射区，两端全盘封闭、厚度与侧壁一致)+repeller背板(4mm，与加速器屏蔽罩壁厚一致)，所有电极(加速器环电极、反射镜环电极、backplate)统一5mm厚 | 后续若再调整屏蔽罩相关尺寸，应当延续这个"统一参数、联动检查包裹范围"的模式，而不是孤立地改一个数字。 |

---

### 7.46 消除飞行管屏蔽罩的真实几何重叠：改用"一次做差"的单体壳设计

> **背景**：用户要求检查飞行管屏蔽罩的端盖和圆柱区域是否重合，以及其他所有部件内部
> 是否重合；并给出具体建议：飞行管屏蔽罩直接画一个大圆柱、再画一个半径小、长度也短
> 的小圆柱，做一次差，一次成型；加速器屏蔽罩同理(方形做差)。几何生成方式尽量简单。

| 发现/教训 | 说明 |
|---|---|
| **❌确认了真实的几何重叠**：§7.44的三特征设计(`endcap`独立圆盘+`flighttubewall`环形壳+`endcap2`独立圆盘)里，`endcap`的z范围`[-1-back_extra-gap-wall, -1-back_extra-gap]`与`flighttubewall`自身的z范围(从`z0_shield=-2-back_extra-gap-wall`起)**在z=[-1-back_extra-gap-wall,-1-back_extra-gap]、半径[flight_tube_r,flight_tube_r+wall]这个区域完全重合** | 根本原因：三个独立特征各自定义自己的z范围时，`flighttubewall`的起点比`endcap`本该占据的范围还要早1mm，导致两者在这个薄层里同时声称同一块空间归自己所有——即便两者都是0V(同电位)，这仍然是一个不必要、容易出错的重叠设计。 |
| **✅✅采用"一次做差"重新设计(单体壳)**：飞行管屏蔽罩现在只用**一个外圆柱(半径`flight_tube_r+flight_tube_wall`，z范围比内腔两端各多出`flight_tube_wall`)减去一个内圆柱(半径`flight_tube_r`，z范围严格等于`accelflightbox`真空腔的z范围)**，一次Difference操作同时生成两端端盖+侧壁，彻底消除`endcap`/`endcap2`/`flighttubewall`三特征之间的重叠可能性——移除了`endcap`和`endcap2`这两个独立特征 | 这正是用户建议的构造方式："画一个圆柱，再画一个稍小的圆柱，做差，一次成型"——外圆柱和内圆柱的z范围只要满足"外圆柱两端都比内圆柱多出统一的端盖厚度"这一个约束，无论内部怎么改，端盖和侧壁的厚度都自动保持一致，且**不可能产生重叠**(重叠只可能发生在多个独立特征各自声明相同空间时，单个Difference operation不存在这个问题)。同时确认了加速器屏蔽罩(`accelshieldO`/`accelshieldH`一次Difference)本来就是这个模式，不需要改动；`repback`(有一个40mm方孔，跟屏蔽罩bore尺寸不同，无法合并进同一个Difference)予以保留为独立特征，但确认了它与`accelshield`、飞行管屏蔽罩均无空间重叠。 |
| **✅全面重叠核查**：逐一验证了`accelshield`(35-39mm半径) vs `repback`(0-70mm半径，40mm孔) vs 飞行管屏蔽罩(380-390mm半径) 三者两两之间在共享的z范围内都没有半径重叠；`ring1_k`/`ring2_k`/`backplate`(均为`ring_outer_r`=350mm半径) vs 飞行管屏蔽罩(380mm起)也有30mm径向间隙，同样无重叠 | 系统性检查方法：对每一对可能共享z范围的实体，比较它们各自占据的**半径区间**是否有交集——只要半径区间不重叠(即便z范围重叠也无妨)，就不构成真实的几何冲突。 |
| **✅✅验证结果(N=100)**：几何构建成功，`Ndomains=28`(比§7.45的更多特征设计更简洁)，**`selb_outerwall`(兜底接地边界)找到的边界数从50降到0**——意味着现在所有边界都被显式实体正确声明，不再需要隐式兜底；无场漂移区残留场`0.0016V/m`(与§7.45的`0.0008V/m`同量级)；**R=18848.4**——比§7.45的`R=14532.0`又有大幅提升(约30%)，100%命中 | "Outer walls: 0"这个诊断信号本身就很说明问题：之前50个"兜底"边界，可能就包含了一些因为重叠特征导致的、本不该存在于那个位置的额外表面(COMSOL处理重叠体时,即便物理上电位相同，网格/边界识别仍可能产生细微的不确定性)。消除重叠后这些边界消失，场精度应声大幅提升，这是本项目"精确度对准确的几何拓扑高度敏感"这一反复验证结论的又一次有力印证。 |
| **⚠️保存环节的操作性问题(非代码/几何问题)**：本轮验证过程中COMSOL服务器/MATLAB客户端在反复重启后出现多次卡死(在网格划分或CPT求解阶段无进展)，需要连续5次"终止进程+干净重启"才最终成功保存模型 | 这是纯粹的运行环境问题——同一份代码在第一次全新启动的服务器上总能成功跑完整个流程(已验证R=18848.4可重复)，卡死只发生在**连续多次重启同一服务器进程之后**，怀疑是Windows/Java层面的资源(文件句柄、端口、内存映射等)未被完全释放，随重启次数累积。**教训**：如果连续多次"kill+restart"后开始出现卡死，问题大概率不在代码本身，值得考虑更长的等待间隔，或建议用户手动重启相关进程，而不是无休止地自动重试。 |

---

### 7.47 repeller与屏蔽罩间隙修正 + repeller尺寸对齐环电极 + 消除reflvac冗余(附一次踩坑教训：理想化栅网不能留间隙)

> **背景**：用户指出`repback`(repeller背板)是接地的，不应该跟带电的repeller接触；
> 同理无场区/反射区的栅网也不该跟接地屏蔽罩接触；repeller的位置(离子侧面)需要核对
> 理论推导位置；repeller尺寸应与加速器环电极的外轮廓一致；并追问`reflvac`的作用、
> 能否删除。

| 发现/教训 | 说明 |
|---|---|
| **✅repeller理论位置核实**：搜索代码中的原始推导注释，确认repeller的离子侧面(z=0)就是整个坐标系的理论原点("repeller(z=0)"、"measured from the repeller at z=0"多处明确记载)，当前`pos.z=-1,h=1mm`使其顶面(+z朝向离子)精确落在z=0 | 位置正确，无需修改。 |
| **❌尝试给理想化栅网(grid1/grid2/entgrid)也加间隙——导致无场区场精度暴跌** | grid1(带电`V_grid1`)之前跟接地的`accelshield`内壁半径完全相同(`2*accel_shield_half`)，确实是"不同电位接触"；仿照环电极的`accel_ring_gap`给grid1/grid2/entgrid也做了收缩——**结果无场漂移区残留场从0.0016V/m暴增到-8V/m**。**根本原因**：grid1/grid2/entgrid是零厚度的理想化边界（不是真实导体），必须完整跨越它所嵌入真空域的**整个截面**(§7.37/§7.38的教训)，否则边缘留下的"没被栅网覆盖"缝隙会让场沿z方向直接"泄露"过去。这跟真实固体导体(环电极、repeller)之间需要留间隙是**两类完全不同的问题**——已回退，grid1/grid2/entgrid恢复到精确贴合各自屏蔽罩内壁。 |
| **✅repeller尺寸对齐环电极外轮廓**：从固定40mm改为`2*(accel_shield_half-accel_ring_gap)`(=66mm，与加速器环电极完全一致)，天然获得与环电极相同的`accel_ring_gap`(2mm)间隙 | 简单的参数化尺寸替换，让repeller在"离屏蔽罩多远"这件事上跟其他加速器电极保持完全一致的设计语言。 |
| **❌→✅第一次尝试直接删掉`repback`——错误，无场区残留场从0.0016V/m回升到0.16V/m** | 错误推理："repeller现在只有2mm间隙(跟环电极一样)，环电极不需要单独背板，repeller应该也不需要"——**但环电极完全被真空包在加速器密封管内部两侧**，而repeller位于屏蔽罩管道的**最前端**，它背后直接连着(经过§7.42延长出来的)缓冲真空区。哪怕间隙只有2mm，这个环形缝隙依然会把repeller的带电面跟屏蔽罩背后的开放空间连通，向前泄露场——不管间隙多小都需要封住，这是位置(是否处于管道端点)决定的，不是间隙大小决定的。 |
| **✅✅最终方案：把repeller背板"焊死"进屏蔽罩本身，一次做差成型** | 采纳用户建议(同飞行管屏蔽罩§7.46的手法)：`accelshieldO`(外方块)的z范围比`accelshieldH`(内方块/孔)的背端**多出`accel_shield_wall`**，做一次Difference后，多出的这部分材料自动成为屏蔽罩自带的背面端盖——不再需要`repback`这个独立特征，也就不存在"背板 vs repeller接触"的问题(背板本来就是屏蔽罩的一部分，跟屏蔽罩同一电位，只是形状上把repeller周围的间隙也封死了)。配套把`z0_bore`(飞行管真空腔起点)也同步往后推`accel_shield_wall`，确保飞行管的真空/外壳完整包住这个新的、更深的屏蔽罩背面，避免两者again重叠。 |
| **✅`reflvac`冗余确认并删除**：`reflvac`(半径`ring_outer_r`=350mm，z范围`[L_flight+1,L_flight+L_refl-1]`)完全是`accelflightbox`(§7.46后半径`flight_tube_r`=380mm、z范围覆盖整个飞行管+反射区)所覆盖区域的一个**子集**——两者提供的都是同一种材料(真空)，纯属历史遗留的重复定义(早期反射镜有自己独立、较小的真空包络，后来`accelflightbox`扩展覆盖了整个反射区之后，`reflvac`就成了纯粹冗余) | 删除后连带清理了`uni_grids`(Union操作)里对`reflvac`的引用。 |
| **✅✅验证结果(N=100)**：无场漂移区残留场恢复到精确的**-0.0000V/m**(全线，与消除重叠前的最佳状态一致)，100%命中，**R=10915.1** | 场精度(最核心指标)完全恢复到完美状态，确认了本轮所有几何改动的正确性。 |
| **⚠️遗留观察：加速器支架场(bracket field, z=0.2-2.8mm)均匀性比之前略差**：目标160V/mm，本次测得159794-160394 V/mm(约±0.2%范围)，比更早版本(通常±0.01%以内)略宽，对应**R从历史最佳的18848.4降到10915.1** | 推测原因：repeller从40mm(15mm间隙)收紧到66mm(2mm间隙)后离屏蔽罩更近，可能引入了轻微的边缘效应，影响了支架场的均匀性；由于离子本身运动范围极贴近轴线(横向漂移仅~0.04mm)，这个效应对绝大多数离子的实际影响很小，但仍值得记录为后续可能的优化方向(例如给repeller也考虑`test_square_shield_accel.m`那样的独立验证测试，量化不同repeller尺寸/间隙下支架场均匀性的变化规律)。 |

---

### 7.48 "被接地电极完全包围"的理论：grid1/midgrid安全收缩间隙 + 探测器移到真实落点(附探测判定逻辑修复)

> **背景**：用户提出一个关键理论——加速器已经被接地电极(屏蔽罩+grid2)完全包围，
> 所以内部的grid1即使跟屏蔽罩留间隙也不会真的泄露场到外面；要求grid2保持跟加速器
> 出口一样大(全尺寸)，grid1收缩到跟repeller/环电极一样大；entgrid保持跟飞行管屏蔽罩
> 内径一样大；midgrid(带电)不能碰屏蔽罩，改成比屏蔽罩内径小10mm；探测器移到L2=500mm
> 处离子的真实落点(跟加速器出口平行)。

| 发现/教训 | 说明 |
|---|---|
| **✅✅"完全封闭包围"理论验证成功**：只收缩grid1(66mm，退出接触)和midgrid(370mm=`flight_tube_r-10mm`，退出接触)，同时让grid2(70mm)、entgrid(`flight_tube_r`)保持跟各自屏蔽罩**精确贴合**(继续"完全封闭"这两个真正的边界)——无场漂移区恢复到精确的**-0.0000V/m** | 这次跟§7.47那次"全部栅网都收缩"的失败尝试形成了鲜明对比，验证了用户理论的正确性：**grid1/midgrid本身位于一个已经被接地表面完全封闭的"盒子"内部**——grid1的封闭盒子是"accelshield侧壁+grid2(现在精确密封出口)"；midgrid的封闭盒子是"飞行管屏蔽罩侧壁+entgrid(精确密封入口)+屏蔽罩远端封盖"——只要这两个盒子的**边界**(grid2、entgrid)保持精确密封，内部grid1/midgrid的小间隙造成的任何"局部场泄露"都只会留在盒子**内部**，出不去，不会污染外部的无场漂移区。这是本项目关于"理想化栅网该不该留间隙"这个反复纠结的问题目前为止最清晰的一次理论+实测双重确认。 |
| **✅grid1/midgrid尺寸最终确定**：grid1=`2*(accel_shield_half-accel_ring_gap)`(66mm，跟repeller/环电极外轮廓一致)；midgrid=`flight_tube_r-10[mm]`(370mm，与屏蔽罩内径380mm留10mm间隙，不再等于`ring_outer_r`) | midgrid的选择集(`selb_midgrid`)半宽也同步从`ring_outer_r+10mm`改成`flight_tube_r`，确保依然能完整框住这个变大的新尺寸。 |
| **✅✅探测器移到真实落点**：从"避让grid2圆盘、停在x=420mm"改为**x=94.93mm**——离子在探测时刻(约t=30.55-30.57us)的真实横向位置，由`x=v_x*t`推算(`v_x=3106.2 m/s`是5eV横向动能对应的恒定速度，全程不受z方向力影响)。这个位置与离子质量无关：`v_x`正比于`1/√m`，总飞行时间正比于`√m`(固定加速电压下)，两者依赖关系正好抵消 | 探测器现在跟"加速器出口"(grid2所在的z=L_accel)共享同一个z，即"跟加速器出口平行"，同时在x方向精确对准离子的真实回程落点，不再是一个"摆在旁边、纯粹靠时间标记"的假探测器，而是离子真正会撞上的物理位置。 |
| **⚠️→✅探测器真正挡在路径上后，探测判定逻辑需要跟着修**：探测器现在物理阻挡了离子的真实轨迹(此前离子从未真正撞上它)，CPT物理引擎会在离子撞上探测器实体时**停止追踪**——但COMSOL不会把之后的z设成NaN，而是把最后一个有效位置**冻结**、原样重复到仿真结束。旧的探测判定逻辑只认"z向下穿越阈值"这一种模式，冻结轨迹永远不会真正穿越阈值，导致**0/100命中** | 用`find(~isnan(...),1,'last')`抓"最后一个非NaN点"的第一次尝试更错——因为z从不是NaN，这样抓到的其实是**整个仿真的最后一个时间步**，导致meanT=284us(应为~30.5us)、std=0(所有粒子都抓到同一个时间点)，一眼就能看出不对。 |
| **✅✅最终探测逻辑**：保留原有的"z向下穿越阈值"判定(向后兼容)，新增一个分支——若未发生穿越但轨迹确实到达过反射镜深处(`wasUp`为真)，则从`wasUp`首次成立的时刻开始(**不是从头开始**，否则会误抓到离子刚离开加速器、正向经过探测器z位置时的早期数据点)往后找，第一个z值落入探测器`det_freeze_tol`(2mm)范围内的时间点，即为真实碰撞时刻 | **关键教训**：只有"探测器保持在离子飞行路径之外(纯时间标记)"和"探测器真正阻挡离子(触发物理碰撞)"是两种本质不同的场景，对应的后处理判定逻辑不能通用——把探测器移动到真实位置这类看似"只是改个坐标"的操作，实际上悄悄地改变了整个探测机制的物理性质，需要连带检查下游的所有假设是否还成立。 |
| **✅✅验证结果(N=100)**：无场漂移区**-0.0000V/m**(全线完美)，100%命中，到达时间`30.54722±0.00099us`，**R=15417.6** | 场精度完美，分辨率也回升到健康水平(比§7.47的10915.1有提升，但比历史最佳的18848.4略低——加速器支架场的均匀性问题，见§7.47遗留观察，尚未解决，本轮改动未触及这部分)。 |

---

### 7.49 探测器上表面修正 + 显式Wall/Freeze边界 + 无场区扩到600mm + d1扫描寻优

> **背景**：用户指出探测器的离子击打面(上表面，朝向来向的离子)应该是L2理论计算位置，
> 而不是下表面；分辨率算法应该用探测器作为"冻结面"、离子击中即停止来计算飞行时间；
> 完成后把无场区(L1=L2)改成600mm，扫描不同长度找最佳解(后更正为扫描d1而非d2)。

| 发现/教训 | 说明 |
|---|---|
| **✅探测器上表面修正**：离子返程沿-z方向飞行，会先撞上探测器**朝向+z的那一面**(上表面)，而COMSOL的Cylinder`pos`是**底面**(较小z的那一面)中心。原来`pos.z=detector_z`使探测器跨越`[detector_z,detector_z+h]`，实际被撞击的上表面落在`detector_z+h`处，比理论L2位置多出`h`(1mm)。修正：`pos.z`改为`detector_z-h`，让上表面精确落在`detector_z` | 一个容易被忽略的细节——Cylinder的定位锚点(底面)与"离子实际撞击的那一面"可能不是同一个面，取决于离子的运动方向，需要具体分析朝向。 |
| **✅✅显式Wall/Freeze边界**：新增`cpt.create('wall_det','Wall',2)`，`selection.named('selb_detector')`，`set('WallCondition','Freeze')`——把"离子撞上探测器后停止"这件事从"隐式依赖CPT物理域(`sel_vac`)不包含探测器实体、轨迹自然终止"的副作用，变成一个**显式配置**的粒子-壁交互条件 | 语法(`'WallCondition','Freeze'`)一次验证成功。这是更健壮、更符合设计意图的实现方式——之前的"隐式停止"虽然能工作，但本质上是蹭了CPT物理域选择的边界效应，没有清楚地表达"探测器就是要冻结离子"这个物理意图。 |
| **✅无场区扩到600mm**：`L_flight`从`L_accel+500mm`改为`L_accel+600mm`(L1=L2=600mm，L_total=1200mm)，用`reflectron_dual_stage_solver.py`(`U0=2000,d1=0.2,L=1.2`)重新求解得到`E1=8888.89V/m,E2=8000.00V/m,U1=1777.78V`，配套更新了`Tsim`估算(1.1→1.2m)和tlist精细窗口(33us→39us，覆盖新的更长到达时间~34.86us) | 每次改变L1/L2这类影响总飞行时间的几何参数时，都要记得同步检查Tsim/tlist窗口和探测器x位置(依赖到达时间的离子横向漂移量)是否还够用——这是本项目反复踩过的一类"忘记级联更新下游依赖"的坑。 |
| **✅✅函数签名扩展支持d1扫描**：`ms_modelB_ringstack_reflectron`新增可选第5参数`d1_mm`(默认200mm)，函数内部直接用闭式解公式(`U1=2*U0*(L+2*d1)/(3*L)`、`E1=U1/d1`、`E2=`含`sqrt(L-4*d1)`的完整表达式)动态重算`E1/E2/U1/V_mid/V_mirror/L_stage1/L_refl`，而不是依赖固定字面值——d2固定在300mm。函数内部会检查`0<d1<L/4`(否则报错)以及`d2>=d2_min`(否则报错) | 一开始用户说"扫描d2"，我实现后又更正为"扫描d1"——**d2只有下限约束(`d2≥d2_min=U1/E2`)，不出现在聚焦方程里，理论上对分辨率没有影响**；而**d1直接决定E1/E2/U1，且有真实的`0<d1<L/4`上限约束**，扫描d1才是有意义的、会改变理论最优场强的操作。这次的核对(直接查阅docx原文第46-49行)避免了执行一个理论上不会有实质差异的扫描。 |
| **✅✅d1扫描结果(N=100，每点各跑一次)**：`d1=80mm→R=11803.5`；`d1=100mm→R=11109.9`；`d1=120mm→R=14220.7`(**目前最佳**)；`d1=150mm→R=13374.9`；`d1=200mm→R=11773.9`(原基准)；`d1=250mm→R=12972.5`；`d1=280mm→R=5755.9`(接近`L/4=300mm`边界，明显劣化) | R随d1的变化**不是单调的**，在d1≈120-150mm附近出现一个局部峰值，d1接近`L/4`边界时急剧劣化(理论上E2公式里的`sqrt(L-4d1)`项在此区间对d1的微小变化更敏感，实际网格离散化误差被这个敏感区放大)。**注意**：每个点仅N=100测了一次，存在统计噪声，若要确认d1=120mm是否是真正稳健的最优点，需要用N=1000在d1=100/120/150mm附近做更严格的复核(按本项目一贯做法，N=100的"看似最优"曾多次在N=1000复核后被推翻)。 |
| **✅最终确认**：用最佳点`d1=120mm`重新验证，无场漂移区**-0.0000V/m**完美，100%命中，到达时间`31.42246±0.00110us`，**R=14220.7**(可重复) | 模型已保存为`MS_ModelB_RingStack_Final.mph`。 |

---

### 7.50 d2自适应化 + 端盖间隙加大 + 加速器/探测器对称放置 + 场与追踪算法确认

> **背景**：用户指出d2目前远大于离子实际穿透深度(浪费)，应改为按理论自适应留余量；
> 飞行管背端(加速反方向)端盖与加速器的间隔太小，加大到20mm；按离子横向速度，把
> 离子初始位置(连同加速器)和探测器中心按关于圆柱对称轴对称的方式重新放置；并确认
> 场计算/离子追踪是否用的是COMSOL内置模型而非自定义方程。

| 发现/教训 | 说明 |
|---|---|
| **✅✅d2自适应化**：不再固定300mm，改为`d2=d2_min*(1+d2_margin_frac)`，`d2_margin_frac=0.3`(30%余量，docx建议20%~50%区间)，`d2_min=U1/E2`随d1动态变化(d1=120mm时`d2_min=173.67mm`，`d2`(自适应)=225.77mm，相比原固定300mm省了约25%反射镜纵向空间) | 原来的固定300mm在d1=120mm时相对`d2_min`(173.67mm)有73%的冗余余量，远超文档建议的20%~50%区间。自适应公式让d2随d1联动，避免每次改d1都要手动重新估算d2。 |
| **✅端盖间隙加大**：`endcap_gap`从3mm改为20mm(飞行管背端端盖与加速器屏蔽罩背边缘之间的真空间隙，两者都接地但仍需要真实间隙，遵循本项目"不同实体需要真实间隙"的一贯纪律) | 简单的参数值修改，无连带影响。 |
| **✅✅加速器与探测器对称放置**：新增参数`x_accel_center=-48.80mm`，把整个加速器总成(repeller/accelshield/grid1/grid2/accelring_k/relvol)平移到`x_accel_center`，探测器移到镜像位置`+48.80mm`。`x_accel_center=v_x*(T/2)`(取负)，`v_x=3106.2m/s`为5eV横向速度，`T=31.42246us`为当前(d1=120mm)设计下已测得的总飞行时间——离子全程横向位移`v_x*T=2*|x_accel_center|`，正好把离子从`-48.80mm`带到`+48.80mm`，与飞行管真实圆柱轴(x=0)对称 | 这个设计有个优雅的自洽性：entgrid/midgrid(反射镜一侧的栅网)仍保持在x=0(飞行管真轴)——离子飞行到约一半时刻(到达entgrid附近)横向漂移恰好把它带回x≈0，与反射镜自身的轴对齐，验证了对称设计在"中点"处自动衔接的正确性。 |
| **🐛→✅严重bug**：平移加速器后，忘记同步更新`gridsel`(grid1/grid2的Box选择框)的x中心——选择框仍centered在x=0，但栅网本体已经搬到`x_accel_center`，导致`selb_grid1`/`selb_grid2`边界计数变成**0**，对应的`ElectricPotential`边界条件完全没有施加对象，加速器场彻底错误(测得-100~-1668V/m，符号方向都不对) | **关键教训**：任何时候平移一组几何体的位置，都要检查所有"独立于几何体本身、通过绝对坐标框选边界"的Box型Selection是否也需要同步平移——这类选择器不会随着几何体的移动自动跟随，很容易被遗漏（相比之下，基于Adjacent/相邻域的Selection如`selb_repeller`会自动跟随，不受影响）。给`gridsel`表新增了显式的x中心列(grid1/grid2用`x_accel_center`，entgrid/midgrid仍用`0`)修复。 |
| **✅诊断查询点连带修复**：加速器场检验和无场漂移区检验的诊断打印代码里，硬编码的探测坐标(`x=0`)也需要同步改成`x_accel_center`(加速器场检验)或按离子实际x(z)轨迹重新推导(无场区检验，`x(z)=x_accel_center+v_x*(z-L_accel)/v_push_speed`) | 这类诊断代码虽然不影响仿真本身的物理结果，但如果不同步更新，会打印出误导性的"看起来全错"的诊断信息(如本次先测出的全0/负值加速器场)，需要跟几何改动一起检查。 |
| **✅✅场计算/离子追踪机制确认**：直接查代码确认——`es=comp1.physics.create('es','Electrostatics','geom1')`是COMSOL**内置**静电场物理接口(在`sel_vac`真实3D体域上求解泊松方程)；`cpt=comp1.physics.create('cpt','ChargedParticleTracing','geom1')`是COMSOL**内置**带电粒子追踪物理接口。生产模式`field_mode='real'`下，`ef1.set('E',{'es.Ex','es.Ey','es.Ez'})`直接引用真实计算场驱动粒子运动——不是自定义方程。唯一的例外是可选的`'ideal'`/`'ideal_accel'`/`'ideal_reflectron'`诊断模式(用`Ex_ideal`/`Ez_ideal`等手工闭式解表达式**替换**真实场)，这些仅用于隔离测试(§7.35的诊断方法论)，从未用于正式/最终模型 | 用户的疑问核实清楚：当前保存的`Final`模型，其电场和离子轨迹**完全是COMSOL从真实3D几何+边界条件求解得到的**，不存在任何"自己设参数/方程"替代真实物理求解的情况。 |
| **✅✅验证结果(N=100，d1=120mm)**：无场漂移区**-0.0000V/m**完美，加速器场准确匹配目标(160211/104637V/m)，100%命中，到达时间`31.41289±0.00175us`，**R=8966.2** | 相比§7.49的14220.7有所下降——推测主要因为d2从300mm收窄到225.77mm(仍满足30%余量要求，但更贴近离子实际穿透深度，理论上不该影响R；实测下降可能反映真实网格离散化误差在d2变短后被放大)，以及加速器/探测器对称平移引入的额外网格离散化差异。这个新R值尚未做N=1000复核，暂列为观察项。 |
| **🔧操作教训：保存流程重排序**：COMSOL原生3D轨迹渲染(`pg1.run`)反复在CPT求解成功之后、`model.save()`之前崩溃MATLAB客户端，导致已经算出的正确结果无法落盘保存(重复失败7次)。修复：把`model.save()`挪到`pg1.run`**之前**执行(保证结果一定落盘)，`pg1.run`及其后的二次保存包在`try/catch`里作为尽力而为的附加步骤 | 这是一个通用的健壮性原则：**把最有价值、最不该丢失的产出（这里是数值结果）尽早持久化，把有崩溃风险的锦上添花步骤（3D可视化渲染）放在其后，并且不让它的失败影响已完成工作的保存**。 |
| **🔧操作教训：孤儿GUI进程持有文件锁**：即使重启了`comsolmphserver.exe`，`model.save()`依然报"文件被另一程序锁定"——排查发现两个`ComsolUI.exe`(COMSOL桌面GUI)进程在后台运行，持有该.mph文件的锁，且这两个进程并非由本次save脚本启动，推测是本轮多次MATLAB客户端崩溃(`0x0000008f`)时残留的孤儿进程。关闭这两个GUI进程后，保存立即成功 | **教训**：`comsolmphserver.exe`(无头计算服务器)和`ComsolUI.exe`(桌面GUI，可能因为某次异常退出而残留)是两类独立的锁持有者，只重启前者不能释放后者持有的文件锁。遇到"重启服务器仍然锁定"的情况，需要额外检查是否有孤儿GUI进程——但这类进程也可能是用户主动打开的工作窗口，操作前应向用户确认，避免误关掉用户尚未保存的工作。 |
| **✅✅离子实际穿透深度 vs 理论d2_min 交叉验证**：新增诊断代码(`penetration_mm = zmax - L_flight_mm`，逐离子计算穿透反射镜的深度，取全体N=100离子中的最大值)。d1=120mm下实测：`penetration_max=170.700mm`，理论`d2_min=173.666mm`，差值`-2.966mm`(`-1.71%`)——实测最深穿透略浅于理论值，方向合理(理论`d2_min`是"恰好使最高能量离子速度归零"的临界深度，实测因初始横向能量/网格离散化等因素通常不会超过它)。当前自适应`d2=225.765mm`比理论`d2_min`多出约55mm(30%余量)，验证margin确实留够。同批复测`R=8966.2`与§7.50首次测得值完全一致，确认结果可复现 | **结论**：自适应d2公式(`d2_min*(1+30%)`)的理论基础得到直接仿真验证——不是纸面公式，离子真实运动轨迹的最深点确实落在`d2_min`附近(仅1.71%的保守偏差)，30%余量足够覆盖，没有让离子意外触底(撞上背板)，也没有浪费过多反射镜纵向空间。 |

### 7.51 d2_min公式修正：文档原始推导有误，正确公式是(U0-U1)/E2不是U1/E2

> **背景**：用户提问"穿透深度是d1+d2min吗？如果是，现在d2的余量太多了"，促使重新核对
> d2_min的物理定义。

直接核对`docx_extracted.txt`原始推导发现自相矛盾：第9行明确定义`U1=E1*d1`为"第一级
吸收的电压"，穿越第一级后**剩余能量为q(U-U1)**；但第48行给出`d2_min=U1/E2`，用的是U1
本身而不是剩余能量。物理上，离子进入第二级时剩余动能是q(U0-U1)，要在场E2下完全减速为
零，所需深度应为`(U0-U1)/E2`，不是`U1/E2`——这是原文档推导的一处错误。

用实测数据验证（d1=120mm）：U1=1600V, U0=2000V, E2=9213.1V/m。
- 错误公式：d2_min=U1/E2=173.67mm
- 正确公式：d2_min=(U0-U1)/E2=**43.42mm**
- 实测第二级穿透深度：170.70mm(总穿透)-120mm(d1)=**50.70mm**

50.70mm远接近43.42mm(偏差~17%，可归因于真实3D场/离散化误差)，而不是173.67mm(偏差
3.4倍)，证实正确公式是`(U0-U1)/E2`。已修正代码中的`d2min_mm`计算，`d2_margin_frac`
仍为可调参数(见下节)。

**教训**：**引用第三方/自己此前推导的理论公式时，最终仍应该用实测数据交叉验证**，
特别是当推导跨越多个文档/多次转述时，容易在中途丢失或混淆变量的物理含义
(这里是"吸收的能量"vs"剩余的能量")。

### 7.52 d2余量-分辨率关系 + 分辨率瓶颈定位方法论扩展为4区域独立开关

修正d2_min公式后，同样的`+30%`余量(`d2_margin_frac`)让d2从225.77mm骤降到56.44mm，
R从8966.2降到2601.6——证实用户的猜测：之前的d2margin确实过大，但收紧到"理论正确的
30%"后分辨率明显变差。追加测试`d2_margin_frac=1.0`(100%余量，d2=86.83mm)：R回升到
4109.5，仍远低于旧(错误公式下)的225.77mm(等效~420%余量)对应的8966.2。**R随d2长度
单调上升，尚未看到平台**——即真实反射镜的性能对d2长度本身敏感，不只是"扣掉浪费空间"
那么简单。

**重要方法论确认**：改变d2margin时，二级场强E2本身保持不变——`V_mirror=U1+E2*(d2/1000)`
是根据d2反推得到的，环栅电压和环间距都跟着d2等比例缩放，只是把同一个线性场E2压缩/
拉伸到不同的物理长度，不是意外改变了场强。用两次margin实测的V_mirror反推E2完全一致
(9213.2V/m)，排除了"R的变化是场强意外改变导致的假象"这个可能性。

**分辨率瓶颈定位方法论扩展**(原§7.35的"ideal_accel/ideal_reflectron"二分法扩展为
4个独立开关)：`field_mode`新增`ideal_drift`/`ideal_stage1`/`ideal_stage2`(各自
只把对应1个区域换成解析理论场，其余区域仍用真实FEM场)，用于把瓶颈精确定位到
"加速器/无场漂移区/一级反射区/二级反射区"四者之一。d1=120mm、d2margin=100%配置下
测试结果：

| field_mode | R | 相对real变化 |
|---|---|---|
| real（基准） | 4109.5 | — |
| ideal_accel | 3991.0 | 几乎不变(-3%) |
| ideal_drift | 4109.5 | 完全相同 |
| ideal_stage1 | 4109.5 | 完全相同 |
| **ideal_stage2** | **22402.3** | **+445%** |
| ideal（全部理想化，理论天花板对照） | 17780.2 | +333% |

**结论：分辨率瓶颈几乎全部集中在二级反射区(stage2)**，其余三个区域替换成理想场后
R完全不变或几乎不变。这是本项目第一次把"瓶颈定位"精确到4个区域中的1个，而不是笼统
的"加速器 vs 反射镜"二分。

**通用方法论**：诊断"哪个区域的真实场限制了分辨率"，最可靠的方法是逐区域单独替换为
解析理论场(其余区域保持真实FEM场)，观察R的变化幅度——变化大的区域就是瓶颈。不要只
做"全理想 vs 全真实"的整体对比，那样无法区分是哪个区域造成的（全ideal结果甚至可能
低于只把瓶颈区域单独理想化的结果，正如本例`ideal`=17780.2 < `ideal_stage2`=22402.3，
说明多区域同时理想化引入了新的相互抵消/失配，反而不如精确定位单个瓶颈区域）。

### 7.53 尝试改善二级反射区真实场逼近理论的程度：环数、网格均已排除

定位到stage2是瓶颈后，尝试了两种方法降低真实场与理论的偏差，均**未见改善**：

1. **增加环电极数量**(`N_rings2`从5参数化后测试5/10/15)：R=4109.5/3945.1/4111.9，
   在噪声范围内完全无变化。与本项目更早(旧、长得多的d2设计下)的历史结论一致——
   "环数不是限制因素"，这次在全新的短d2状态下重新验证，结论依然成立。
2. **加密反射镜区域网格**(`szrefl.hmax`从15mm加密到5mm，单元数从33万涨到307万，
   静电场求解时间从10s涨到59s)：R=4109.5→4118.5，几乎无变化。**这证实了偏差不是
   数值/网格离散化误差，而是真实的物理场效应**（否则加密网格应该会让真实场更逼近
   连续理论解）。

排除环数和网格后，唯一还没重新测试的变量是`bore_r`(环孔径半径，当前250mm)——这在
本项目早期(§7.31，当时反射镜总长几百mm)已经详细扫描过，结论是"孔径越宽R越高"(反直觉，
250mm是当时的成本/收益最优点)。但那次扫描是在stage2长得多的旧设计下做的；现在stage2
被压缩到只有87mm，250mm的孔径可能已经远超stage2自身的深度，导致"边界沉降/边缘场"
效应（entgrid/backplate过渡区，孔径越宽这个过渡区越长）覆盖了几乎整条stage2，真实场
根本没机会稳定到理论假设的均匀线性场。已把`bore_r`(及等比例的`ring_outer_r`)参数化
为函数的第8个可选参数，计划在当前的短d2状态下重新测试(此项测试在本次会话结束时尚未
执行，留待下次)。

**教训**：任何在"旧几何尺度"下得出的经验结论(环数、孔径尺寸等)，在几何尺度发生数量级
变化后都应该重新验证，不能想当然地沿用——就像环数结论碰巧还成立，但孔径的结论完全
可能反转。

---

## 8. 磁场建模全流程实测记录（从"能不能连上物理场"到"回旋运动定量验证"）

> **本节位置说明**：这是 §7.14/§7.15 速查表背后的完整调试过程叙事（记录踩坑顺序，
> 方便理解"为什么"，不只是"是什么"），内容上早于 §7.16 及之后的部件（在项目时间线上，
> 磁场调试发生在多极杆等部件之前），但为了不打断 §7.1-7.26 这条主速查表的连续编号，
> 把它整节放在文档最后——**编号仍然是"§8"，只是物理位置移到了文末**，全文所有
> `见§8`/`§8.1`-`§8.5` 的交叉引用都还指向这里，不受影响。

这一节是 §7.14/§7.15 速查表背后的完整调试过程叙事，记录踩坑顺序，方便理解"为什么"，
不只是"是什么"。这是本项目第一次接触 Magnetic Fields / 洛伦兹力，之前 §0-§7 全部
只涉及 Electrostatics + Charged Particle Tracing。

### 8.1 定位正确的物理场 tag：`InductionCurrents`
直接尝试 `comp1.physics.create('mf','MagneticFields','geom1')` 报 "Unknown physics
interface"。没有现成的"列出所有可用物理场"API（`model.physics.getAvailablePhysicsInterfaces`
不存在），只能挨个猜候选 tag 名：`MagneticFields`(✗) / `InductionCurrents`(✓) /
`MagneticFieldsNoCurrents`(✗) / `RotatingMachineryMagnetic`(✓，但不是我们要的) /
`ACDC`(✗)。**教训：COMSOL Java API 里物理场的"内部 tag"和 GUI 里显示的名字("Magnetic
Fields")经常对不上，纯靠试错定位，`model_inspect` 报的 `modules` 列表也不一定能提前
告诉你某个物理场能不能用——直接试一次created 比纠结许可证文档快。**

### 8.2 用已验证的 Helix 几何直接当线圈导体，走通 `Coil` 特征
`mf.create('coil1','Coil',3)` 直接选中我们电子枪项目里已经反复验证过的 `Helix` 螺旋
线圈实体作为域，`CoilType` 默认就是 `'Numeric'`（专门处理"任意真实3D形状"的线圈，
不是"Circular"/"Linear"那种理想化简化模型），完全不需要额外建模——这是个意外的
复用红利：本来是为电子枪灯丝设计的几何，直接拿来当电磁铁线圈测试也一次成功。

### 8.3 三层报错，逐层剥开 Numeric Coil 的真实求解要求
依次遇到、依次解决的三个报错，记录顺序是因为**每一个都会掩盖下一层**，不按顺序不会
一次性看到全部：
1. `"No selection specified for the Input subfeature under the Geometry Analysis
   subfeature"` → Coil 的 `ccc1.ct1`（Input 终端）需要显式选一个边界（线圈两个平头
   端面之一）。
2. 修好终端选择后，`"Undefined material property 'sigma' required by Domain Coil
   1"` → 线圈域必须有电导率材料属性，随便给个钨/铜的量级即可（这里不是要精确导电
   计算，只是磁场需要知道"这是导体"）。
3. 修好材料后，`"Numeric coil Domain Coil 1 (coil1) not solved for. Solve it in a
   Coil Geometry Analysis step"` → **最隐蔽的一步**：`std1.create('stat1',
   'Stationary')` 单独存在不够，必须在它*之前*额外 `std1.create('ccc_step1',
   'CoilCurrentCalculation')`。study-step 类型名字试了 `'CoilGeometryAnalysis'`（虽
   然听起来最像报错文案，但报 "Operation cannot be created in this context"）和
   `'StationarySourceSweep'`（真能创建+求解，但报 "No sources found."——这个类型是
   给多线圈互感扫描准备的，误用在单线圈上会得到一个乍看合理、实则文不对题的报错）；
   最终是靠"study-step 类型名字很可能和物理场自动生成的子特征同名"这个直觉，试出
   `'CoilCurrentCalculation'`（和 §8.3 第1步里的 `ccc1` 同名）才成功。加上这一步后，
   `createAutoSequence` 会自动生成两段 solver（先解线圈电流分布，`StoreSolution`
   存下来，再解主磁场），全部一次跑通。

### 8.4 定量验证：有限长螺线管中心磁场
5匝、线圈半径0.3mm、通电1A，解出中心轴向 `Bz=5.33e-3 T`，对比无限长螺线管理想公式
`mu0*N*I/L=6.28e-3 T`，比值0.85——完全符合"有限长度、匝数不多的螺线管，中心场应该
略小于无限长理想值"的物理直觉，是很干净的自洽性验证。

### 8.5 CPT 磁场力：一次"没报错但结果全错"的排查
配好 `MagneticForce`（`B_src='userdef'`, `B={0,0,0.01[T]}`）之后，模型顺利求解，
`|v|` 全程精确守恒于 1e6 m/s（磁场力不做功，这本身就是一个看似过关的信号），但轨迹
画出来是一条几乎笔直的线，完全没有回旋。**根因：`MagneticForce` 特征创建后忘了调用
`.selection`，默认作用域是空**——这和 `Release`/`Inlet` 没选择时会在编译期直接报错
不同，力类特征（`ElectricForce`/`MagneticForce`）选择为空时**不报错，只是让力处处
为零**，粒子于是保持初速直线运动，由于磁场力不做功这个特性，连"能量守恒"这个常规
正确性检查都不会揭穿它。补上 `mf1.selection.all` 之后重新求解，轨迹立刻变成一个漂亮
的正圆，回旋半径 0.58mm 对比理论 `m*v_perp/(qB)=0.57mm`，误差2%。**教训：CPT 里所有
"力"类特征（Electric/MagneticForce）都要把"有没有设置 selection"当成检查清单的
第一项，不要因为模型能跑、能量守恒看起来正常就掉以轻心——这两个指标对"选择为空导致
力恒为零"这个特定的坑完全不敏感。**
