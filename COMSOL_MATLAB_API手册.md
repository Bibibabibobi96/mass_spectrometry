# COMSOL 6.4 + MATLAB LiveLink：通用 API / 调用速查手册

> **适用范围**：所有质谱仪(及同类粒子光学)COMSOL自动化建模项目都会用到的通用知识——
> 怎么建几何、怎么设物理场、怎么追踪粒子、怎么取数据、已经验证过的部件库。
> **不含**特定项目的具体参数/踩坑叙事(那些在`项目_*.md`文件里)，也**不含**通用调试
> 方法论(那些在`COMSOL_调试方法论.md`里)。

---

## 0. 技术路线：优先绕过 MCP 工具，直接走 Java API

如果项目要求"优先使用 MCP COMSOL 工具"，**先做一次最小连通性测试**（建模型+建组件+建最简几何），
不要假设 MCP 工具箱可靠。曾实测 MCP 的 `model_create_component` 工具存在代码级 bug（内部按3参数
重载调用 `ModelNodeListClient.create()`，但 COMSOL Java API 该方法只有1/2参数重载），换版本、换
启动参数都无法修复。

**可靠方案：MATLAB LiveLink for COMSOL，直接调用底层 Java API**：
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
- 这条路径不依赖 MATLAB 图形界面/许可证之外的东西，比"COMSOL Java 源码 + comsolcompile +
  comsolbatch"更适合迭代调试。

---

## 1. Java API 建模层的具体坑

### 1.1 组件与几何创建
```matlab
comp1 = model.component.create('comp1', true);      % 2参数 (tag, boolean)，没有维度参数
geom1 = comp1.geom.create('geom1', 3);               % 维度在这里指定
geom1.lengthUnit('mm');                               % 会影响后续插值坐标单位（见§2.6坑A）
```

### 1.2 Fillet / Chamfer 可能受许可证限制
`geom1.feature.create('fil1','Fillet')` / `'Chamfer'` 报错 "The requested geometry
operation is unknown or cannot be created in this context"——即使最简单的单个圆柱体也
失败，是许可证/模块限制（可能需要 Design Module）。**排查方法**：先在空白模型里对最简单
的图元单独测试，如果连这个都失败就直接切换方案。

**替代方案：用 Cone（圆锥台）− Cylinder 布尔差手工构造 45° 倒角**：
- 外圈顶部边缘：`Cylinder(r=R, h=d, pos=z_top-d)` 减去 `Cone(r=R, rtop=R-d, h=d, pos=z_top-d)`
- 外圈底部边缘：`Cylinder(r=R, h=d, pos=z_bot)` 减去 `Cone(r=R-d, rtop=R, h=d, pos=z_bot)`
- 内孔顶部边缘：`Cone(r=r_hole, rtop=r_hole+d, h=d, pos=z_top-d)` 减去 `Cylinder(r=r_hole, h=d, pos=z_top-d)`
- 内孔底部边缘：`Cone(r=r_hole+d, rtop=r_hole, h=d, pos=z_bot)` 减去 `Cylinder(r=r_hole, h=d, pos=z_bot)`
- 最后一次 `Difference` 把所有倒角工具体从母体减掉。

**Cone 图元属性名**（容易搞错）：
```matlab
geom1.feature(coneTag).set('r', baseRadius);          % 底面半径
geom1.feature(coneTag).set('specifytop', 'radius');   % 字符串'radius'，不是boolean
geom1.feature(coneTag).set('rtop', topRadius);         % 顶面绝对半径，不是'r2'/'ratio'
geom1.feature(coneTag).set('h', height);
```

### 1.3 几何信息查询
`geom1.getNEdge(tag)` 这类方法不存在，用：
```matlab
gi = mphgeominfo(model, 'geom1');   % 字段大写开头：Ndomains, Nboundaries, Nedges, Nvertices
```

### 1.4 命名选择集（Selection）的建立方式
- 给几何图元开启自动域选择：`geom1.feature(tag).set('selresult','on')`，之后用固定命名
  规则 `geom1_<featureTag>_dom` 引用。
- 拿"某个域的边界面"，建组件级 `Adjacent` 选择：
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
- `Slice` 图层切面方向属性是 `quickplane`，合法取值 `"xy"|"yz"|"zx"`（**不是** `"xz"`）。
- 默认一个方向会自动铺开好几个切面，只要单张切面需要显式设：
  ```matlab
  sl1.set('quickznumber','1'); sl1.set('quickxnumber','1'); sl1.set('quickynumber','1');
  ```
- 图片导出：`model.result.export.create(tag,'Image')`，设置 `plotgroup`、`pngfilename`、
  `width`、`height`，然后 `.run`。

---

## 2. 带电粒子追踪（CPT）专项坑

### 2.1 物理场与默认特征
```matlab
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
```
自动带有：`wall1`（Wall，默认`WallCondition=Freeze`且`Otherwise=Freeze`，即默认对所有边界
"冻结/吸收"粒子，同时天然充当"末端探测面"）、`pp1`（ParticleProperties，默认已经是电子：
`mp=me_const`, `Z=-1`）、`dpcon1`（PairContinuity，装配体配对用，普通模型忽略即可）。

### 2.2 从边界发射粒子：特征类型叫 `Inlet`，不是 `Release`/`ReleaseFromBoundary`
```matlab
inl1 = cpt.create('inl1', 'Inlet', 2);   % 2 = 边界级别
inl1.selection.named(sel_emit_surface);
% 默认 v0=0，方向默认沿边界法向
```

### 2.3 电场耦合到粒子受力：`ElectricForce` 是 cpt 物理场下的特征，不是顶层 multiphysics 节点
```matlab
% 错误：model.multiphysics.create('epf1','ElectricForce', ...)  -> "Unknown multiphysics coupling"
ef1 = cpt.create('ef1', 'ElectricForce', 3);   % 3 = 域级别
ef1.selection.named(sel_vac_tag);
ef1.set('E_src', 'root.comp1.es.Ex');          % 必须是这个完整限定字符串
```
**技巧**：不确定合法值时，先随便 set 一个错误值，COMSOL 报错信息通常会直接列出所有合法取值。

### 2.4 时间相关粒子追踪 Study：复用已求解的静电场
```matlab
std2 = model.study.create('std2');
tstep = std2.create('time1', 'Transient');
tstep.set('tlist', 'range(0,0.1[ns],40[ns])');
tstep.setEntry('activate','es', false);
tstep.setEntry('activate','cpt', true);

% !!! 高优先级坑：仅 setEntry('activate','es',false) 不会让 cpt 自动复用已解的 es 场！
% createAutoSequence 生成的 Variables 节点(v1)默认 notsolmethod='init'（未求解变量取值
% 落回初始值，对es场约等于全0），导致 ElectricForce 处处为0，粒子以v0=0释放后完全不动，
% 且不报任何错——比图形问题更隐蔽。必须显式指向 Study 1 的解：
model.sol.create('sol2'); model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');  % 'sol'=用存储解
model.sol('sol2').feature('v1').set('notsol', 'sol1');       % 属性名是notsol，不是notsolnum！
model.sol('sol2').runAll;
```
**排查方法**：怀疑粒子没有真正受力/运动时，直接对比同一坐标下 `es.normE` 在 `dset2`（CPT
study的解）和 `dset1`（纯静电场解）里的取值：
```matlab
mphinterp(model, 'es.normE', 'coord', coords, 'dataset', 'dset2')  % 应与dset1同量级
```
如果 `dset2` 上处处为0而`dset1`不为0，就是这个"未求解变量"配置问题。

时间步长估算：非相对论电子末速度 `v=sqrt(2*E_eV*1.602e-19/9.11e-31)`，除以渡越距离得到
量级，留30-50%余量。

### 2.5 求粒子末态动能：不要迷信 `cpt.Ep`，可能根本不存在
`cpt.Ep`/`Ek`/`KE`/`kin_en`/`Ekin`/`speed`/`U`，以及`comp1.qx`/`cpt.qx`/`cpt.vx`这类"看起
来应该对"的变量名在 `mpheval` 里全部报"Undefined variable"。

**稳健替代方案：用能量守恒代替去猜变量名**——如果粒子从阴极（V=0）附近以≈0eV初速释放，
它在任意后续位置的动能[eV] = 该位置的静电势V：
```matlab
pd = mphparticle(model, 'dataset', 'pdset1');
qx = pd.p(end,:,1).'; qy = pd.p(end,:,2).'; qz = pd.p(end,:,3).';
coords = [qx'; qy'; qz'];
KE_eV = mphinterp(model, 'V', 'coord', coords, 'dataset','dset1');
```
前提：粒子从V≈0处以≈0eV初速释放、纯静电场加速、无磁场/碰撞损耗。

### 2.6 取粒子坐标绝对不要用 mpheval，要用专用的 mphparticle
`mpheval(...,'dataset','dset2','edim',0)`（`dset2`=CPT study原始Solution数据集）**不会
报错，但取到的根本不是粒子位置**——安静退化成对底层FEM网格的0维几何顶点求值，坐标范围
正好等于真空域边界，且不随`t`变化。这曾直接导致误判"电子不运动"。

**正确写法**：
```matlab
pd = mphparticle(model, 'dataset', 'pdset1');   % pdset1 = Particle类型数据集(见2.9)
% pd.p, pd.v 都是 [nTimes x nParticles x 3] 的 double 数组（不是cell！）
% pd.t 是 1 x nTimes 的时间向量
z_all_particles_at_tk = pd.p(k, :, 3);        % 第k个时间步，所有粒子的z
z_of_particle_j_over_time = pd.p(:, j, 3);    % 第j个粒子，随时间变化的z
```
另外，`mpheval(...,'dataset','pdset1','edim',0)`（用对了数据集，但还留着`edim`参数）会
**卡死**（8分钟无响应，见`COMSOL_调试方法论.md`§卡死恢复）——`Particle`数据集不接受
`edim`，不要对它用`mpheval`，只用`mphparticle`。

### 2.7 mpheval/mphinterp 的两个隐蔽单位/维度坑
**坑A：坐标单位跟随模型的`geom.lengthUnit`，不一定是米。** 如果`geom1.lengthUnit('mm')`，
`mphinterp`的`coords`也必须用mm——用米传入不会报错，只会安静返回全0（坐标落在网格范围
外，插值默认给0，无异常提示）。

**坑B：`'outersolnum','end'`对"时间相关/粒子追踪"数据集不代表"最后一个时间步"。** 96个
粒子×301个时间输出点的CPT解用`'outersolnum','end'`取回28896个点（=所有粒子×所有时间步
混在一起），不是末态快照。**正确做法：显式指定具体时间值** `'t', tend`。

### 2.8 粒子轨迹图需要专门的 Particle 数据集
```matlab
% 错误：pg.set('data','dset2') -> "Operation cannot be performed on dataset dset2 (Solution)"
pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.set('solution', 'sol2');     % 属性名是solution，不是data！
pg3 = model.result.create('pg_traj','PlotGroup3D');
pg3.set('data', 'pdset1');
tr1 = pg3.create('traj1', 'ParticleTrajectories');
```

### 2.9 NaN 处理与统计陷阱
粒子中途被吸收后，`pd.p`/`pd.v`里后续时刻的值：有的场景冻结在最后有效坐标，有的场景
（大量粒子在第一个输出步之前就被吸收）直接是NaN，且从第一个记录点起就已经是NaN——不要
假设"被吸收=冻结在小z值"，两种表现都要处理，用`isnan(...)`单独统计。

**MATLAB陷阱**：`min`/`max`默认自动忽略NaN，但`mean`/`median`**不会**，数组里有一个NaN，
`mean`/`median`就返回NaN。统计前先用`isnan`过滤，或用`mean(x,'omitnan')`。

---

## 3. 会话/服务端/幂等性 相关运维事实

### 3.1 脚本可重复运行性（幂等性）：不要把中间产物存回自己读取的源文件
如果脚本一开始 `ModelUtil.load('Model', A.mph)`，跑完在末尾 `model.save(A.mph)`，下次再跑
会往一个已"被污染"的文件里重新创建同名节点，报"An object with the given name already
exists"。**约定：每个阶段脚本只从上一阶段产出、不会被本阶段覆盖的文件里读，本阶段新增
内容另存为新文件名，保证阶段脚本可以反复重跑。**

### 3.2 `ModelUtil` 模型标签会跨客户端进程残留
comsolmphserver 是持久进程，不同的 `matlab -batch` 调用只是不同的客户端连接，之前调用
创建的模型标签会一直存在服务端内存里，直到显式`ModelUtil.remove(...)`。**每次载入模型
前先检查并清理同名标签**：
```matlab
if any(strcmp(cell(ModelUtil.tags()), 'Model'))
    ModelUtil.remove('Model');
end
model = ModelUtil.load('Model', modelPath);
```
调试阶段容易积累一堆用完即弃的临时标签，建议定期批量清理：
```matlab
tags = cell(ModelUtil.tags());
for i=1:numel(tags), try, ModelUtil.remove(tags{i}); catch, end, end
```

---

## 4. GPU 求解器（cuDSS）实测结论

COMSOL 6.4 的 Direct 求解器特征暴露了 NVIDIA cuDSS GPU 直接求解器支持，属性名带`cudss`
前缀。启用方法：
```matlab
dDef.set('linsolver','cudss');
s1.feature('fc1').set('linsolver','dDef');   % 默认fc1.linsolver通常是'i1'(CPU迭代法)
```
**实测（几万自由度静电场模型，RTX 2060）：GPU 14.16s，反而比默认CPU迭代法(8.98s)慢
58%。** 小规模问题下GPU的上下文初始化/数据搬运开销超过并行收益。**GPU cuDSS只在自由度
规模远大于本例（经验百万级以上）时才可能有优势，小模型不要默认开GPU。**

同样的切换方法在时间相关(Transient)求解器上完全类比：
```matlab
t1 = model.sol('sol2').feature('t1');
t1.feature('dDef').set('linsolver','cudss');
t1.feature('fc1').set('linsolver','dDef');
```
**实测（碰撞池模型，32粒子×201时间步CPT）：CPU 0.982s，GPU 1.672s，GPU反而慢70%。**
物理结果完全一致（最大差异3.75e-12mm，纯浮点噪声），确认纯粹是性能层面的切换。

**后续oa-TOF项目的多次独立复测**（几万自由度静电场、以及CPT主直接求解器）**结论完全
一致**：CPU (pardiso) 稳定持平或快于 GPU (cudss)，本项目规模下不要默认开GPU。

---

## 5. 工程/物理层面的通用检查习惯

建好静电场之后、正式做粒子追踪之前，**先花一分钟沿粒子实际飞行路径算一遍电位分布**
（`mphinterp`在几个关键位置取V值），检查有没有电位"先降后升"形成的势垒——如果控制电极
负偏压相对目标能量偏大，会在发射点附近形成粒子翻不过去的势垒，届时粒子追踪会出现"大部分
粒子在发射点附近就被吸收"的结果。这个检查几乎不花时间，但能在正式跑粒子追踪（通常耗时
更长、调试成本更高）之前提前发现"参数设置在物理上是否自洽"的问题。

---

## 6. API / 函数 / 属性调用速查表（持续更新）

> **维护约定**：每次新发现一个可靠用法或一个无效/错误用法，都直接追加到下面对应的小节里
> （新增一行/一条即可）；确实找不到合适分类再新开一个小节，追加到末尾，编号只递增
> （旧编号`§7.x`保留作为本文件内部小节号延续，避免破坏其他文档里`见§7.x`的交叉引用）。
> 每条尽量只留"怎么写是对的"+一句话背景，详细踩坑过程见`项目_*.md`或`COMSOL_调试方法论.md`。
> **新增一个完整的部件（几何+物理场组合、有验证脚本）时，除了新开小节写细节，还要在§7.0的
> 部件库表格里加一行**。

### 7.0 已验证质谱仪/粒子光学部件库速查表

> **用途**：新任务第一步先扫一眼这张表——如果要建的部件已经在这里，直接复用/改造对应
> 脚本，不要从零重新摸索。

| 部件 | 核心物理机制 | 关键验证结果 | 参考脚本 | 详见 |
|---|---|---|---|---|
| 电子枪（螺旋灯丝+Wehnelt） | 热发射(`Thermal`)+Wehnelt偏压聚焦 | 横置线圈收集效率34.18% > 轴向线圈27.71%；Wehnelt偏压存在非单调最优点 | 电子枪 phase1-5 系列脚本 | `项目_电子枪.md` |
| 螺线管线圈 | `InductionCurrents`+`Coil`(Numeric) | 中心磁场/无限长理论值比值0.85 | `test_magnetic_coil.m` | §7.14, §8 |
| 均匀磁场回旋运动(裸测试) | 均匀Bz+`MagneticForce` | 回旋半径0.58mm vs理论0.57mm(2%误差)，轨迹为正圆 | `test_cpt_magnetic_force.m` | §7.15, §8.5 |
| 四极/六极/八极杆 | RF交替电位；仅四极有严格马蒂厄稳定性 | on-axis电位幂律`r^(N/2)`吻合4位有效数字；四极q=0.5稳定/q=1.2发散；六极/八极是"离子导管"而非质量滤波器 | `test_multipole_geometry.m` / `test_multipole_es.m` / `test_quadrupole_stability.m` | §7.16 |
| 爱因茨尔透镜(Einzel Lens) | 静电透镜聚焦 | 聚焦强度只取决于`KE_beam/|V_lens|`比值(标度律) | `test_einzel_lens.m` / `test_einzel_cpt.m` | §7.17 |
| 线性离子阱(LIT) | RF四极径向约束+DC端盖轴向约束 | 轴向束缚呈平滑抛物线往返运动，全程未接近电极 | `test_lit_geometry_es.m` / `test_lit_cpt.m` | §7.18 |
| TOF飞行时间分析器+反射器(基础版) | 加速→漂移→反射镜减速反弹 | `t∝sqrt(m)`吻合(误差0.5%)；漂移管必须接地侧壁 | 已被oa-TOF环栈反射镜取代 | §7.19 |
| ESA静电扇形场能量分析器 | 同轴柱形电容器径向场`E=V0/(r·ln(R2/R1))` | FEM与解析解吻合4位有效数字 | `test_esa.m` | §7.20 |
| 磁扇形场质谱仪 | 均匀B场回旋运动，固定KE下按质量分离 | `r∝sqrt(mass)`吻合5位有效数字 | `test_magnetic_sector.m` | §7.21 |
| 碰撞池/CID(背景气体碰撞) | `Collisions`+`Elastic`子特征(必须加子特征才生效) | 损失率随`Nd`单调变化 | `test_collision_cell.m` | §7.22 |
| 共振电荷交换碰撞 | `Collisions`+`ResonantChargeExchange`子特征 | 25%粒子出现单步>90%速度骤降 | `test_resonant_charge_exchange.m` | §7.25 |
| Wien滤波器(交叉E×B) | `v=E/B`只筛速度、与质量电荷无关 | 共振速度偏转≈0；质量无关性验证 | `test_wien_filter.m` | §7.23 |
| 空间电荷/库仑排斥 | `ParticleParticleInteraction`(`InteractionForce='Coulomb'`) | 有vs无相互作用，径向扩散标准差相差33倍 | `test_space_charge.m` | §7.24 |
| FTICR/ICR离子回旋共振池 | 均匀B场回旋+DC端盖组合捕集 | 出现真实磁控漂移(magnetron drift)现象 | `test_icr_cell.m` | §7.26 |
| 简单质谱仪整机(EI源→引出→多极杆→TOF→反射器→检测器) | 电子撞击电离+引出加速+RF多极杆+TOF | 电离产率与理论吻合 | `ms_stage1_ei_source.m` | §7.27 |
| oa-TOF环栈反射镜（正交加速+双级Mamyrin反射镜） | 见项目文件 | 见项目文件 | `ms_modelB_ringstack_reflectron.m` | `项目_oaTOF环栈反射镜_ModelB.md` |

### 7内容分类索引
- **环境/会话管理**：§7.1, §7.13
- **几何/材料/网格/静态求解通用套路**：§7.2, §7.3, §7.4, §7.5, §7.6
- **CPT粒子追踪核心机制**：§7.7, §7.8, §7.9, §7.10
- **磁场物理场**：§7.14（`InductionCurrents`/`Coil`特征，完整调试叙事见§8）
- **CPT里的力/碰撞/多体效应**：§7.15, §7.22, §7.24, §7.25
- **GPU求解器**：§7.11（结论：本项目规模下比CPU慢，不要默认开）
- **已验证的部件（几何+物理组合实例，对应§7.0表格）**：§7.16-§7.27
- **理想细网格栅网(内部边界技术) + Release分布/随机化API**：§7.29
- **黑名单**：§7.12（已确认无效的调用，不要重试）

### 7.1 会话 / 模型管理
| 调用 | 说明 |
|---|---|
| `mphstart(2036)` | 连接本机已启动的comsolmphserver。每个`matlab -batch`脚本开头都要单独调用一次。 |
| `ModelUtil.create('Model')` | 新建空模型，tag='Model'。 |
| `ModelUtil.load('Model', path)` | 从.mph文件加载模型到tag='Model'。 |
| `ModelUtil.remove('Model')` | 删除服务端内存里的模型tag。载入前先检查并清理同名tag（见§3.2）。 |
| `cell(ModelUtil.tags())` | 列出服务端当前所有模型tag。 |
| `model.save(path)` | 保存为.mph。注意幂等性（见§3.1）。 |
| `model.label('xxx')` | 给模型设标签。 |

### 7.2 几何建模
| 调用 | 说明 |
|---|---|
| `comp1 = model.component.create('comp1', true)` | 2参数(tag, boolean)，无维度参数。 |
| `geom1 = comp1.geom.create('geom1', 3)` | 维度在这里指定。 |
| `geom1.lengthUnit('mm')` | 影响后续坐标单位。 |
| `geom1.feature.create(tag,'Cylinder')` + `.set('r',...)/.set('h',...)/.set('pos',{'x','y','z'})/.set('axis',[0 0 1])` | 圆柱体图元。 |
| `geom1.feature.create(tag,'Cone')` + `.set('r',...)/.set('specifytop','radius')/.set('rtop',...)/.set('h',...)/.set('pos',...)` | 圆锥台图元（见§1.2）。 |
| `geom1.feature.create(tag,'Difference')` + `.selection('input').set({...})` + `.selection('input2').set({...})` | 布尔差；`input`=被减，`input2`=减去的。 |
| **Fillet / Chamfer** | 许可证不支持，改用Cone−Cylinder手工倒角（见§1.2）。 |
| `geom1.feature(tag).set('selresult','on')` | 开启自动域选择，之后用`geom1_<tag>_dom`引用。**警告**：如果该图元与其他图元大范围空间重叠（如包住所有电极的外层"真空域"圆柱体），生成的选择可能不"纯净"（解析出全部域）。**正确修复**：不要用外层大圆柱的selresult当真空域，改用`comp1.selection.create('sel_vac','Complement')`+`.set('input',{电极域1,电极域2,...})`对"真正独立不重叠"的电极域取补集。用之前先`entities()`打印检查实际解析到的域编号。 |
| `geom1.run` | 构建几何。 |
| `mphgeominfo(model,'geom1')` | 返回`Ndomains/Nboundaries/Nedges/Nvertices`（见§1.3）。 |
| `geom1.feature.create(tag,'Helix')` + `.set('rmaj',...)/.set('rmin',...)/.set('axialpitch',...)/.set('turns',...)/.set('pos',{'0' '0' 'z0'})` | 原生螺旋线圈实体图元，不需要额外Sweep。`type`默认`'solid'`，`rmaj`=线圈半径，`rmin`=线材截面半径，`axialpitch`=每匝轴向间距，`turns`=匝数。 |
| `hel1.set('axistype','x')`（或`'y'`/`'z'`/`'cartesian'`/`'spherical'`） | 螺旋轴朝向；默认`'z'`。改成`'x'`后`pos`是螺旋沿x轴的起点。 |
| `mphgeom(model,'geom1', 'facealpha',0.5)` + MATLAB `print(fig,'file.png','-dpng')` | 验证复杂几何最可靠的可视化方式：MATLAB自己的图形引擎（`figure('Visible','off')`），完全不经过comsolmphserver图形导出管线，不受渲染卡死风险影响。 |

### 7.3 选择集 (Selection)
| 调用 | 说明 |
|---|---|
| `comp1.selection.create(tag,'Adjacent')` + `.set('input',{'geom1_xxx_dom'})` | 组件级"相邻边界"选择，从域选择拿到该域的边界面。 |
| `feature.selection.named('tag')` | 材料/物理场特征引用命名选择的标准写法。 |
| `sel.entities()` | 返回该选择实际解析到的实体编号数组，排查选择是否解析对了的关键手段，不要只看名字。 |

### 7.4 材料
| 调用 | 说明 |
|---|---|
| `model.material.create(tag,'Common')` + `.selection.named(...)` + `.propertyGroup('def').set('relpermittivity',{'1'})` | 标准写法（见§1.5）。 |

### 7.5 静电场 (Electrostatics)
| 调用 | 说明 |
|---|---|
| `es = comp1.physics.create('es','Electrostatics','geom1')` + `.selection.named(sel_vac)` | 限定物理场作用域。 |
| `es.create('pot1','ElectricPotential', 2)` + `.selection.named(...)` + `.set('V0', 'V_expr_or_param')` | 电位边界条件，2=边界级别。 |

### 7.6 网格 / 稳态求解
| 调用 | 说明 |
|---|---|
| `mesh1 = comp1.mesh.create('mesh1')` + `.feature('size').set('hauto', N)` + `.run` | N: 1=最细...9=最粗，"Finer"≈3。**警告**：不保证真的生成域网格！见下面FreeTet那一行。 |
| `mesh1.feature.create('sz1','Size')` + `.selection.geom('geom1',2)` + `.selection.named(边界选择)` + `.set('custom','on')` + `.set('hmaxactive',true)` + `.set('hmax',...)` | 对特定边界显式指定局部网格尺寸。 |
| **`mesh1.feature.create('ftet1','FreeTet')`（域填充网格特征）** | **【高优先级坑】必须显式加**，不要假设`mesh.create()+size+run()`会自动补域填充网格！否则可能静默生成空网格，`mesh1.run()`不报错，后续求解也"成功"跑完但结果毫无意义（域级`mpheval`查询返回0个点，`mphinterp`对任意坐标都报"Cannot evaluate expression"）。**这是判断"网格其实是空的"的关键信号**：连远离精细几何的普通坐标点插值都失败，先怀疑网格没建好。 |
| `meshinfo = mphmeshstats(model,'mesh1')` + 检查 `meshinfo.isempty`/`.hasproblems`/`.iscomplete` | 网格建完后必须显式检查这三个字段再往下走，不要只看`mesh1.run`有没有抛异常。 |
| `model.study.create('std1')` + `.create('stat1','Stationary')` | 稳态study。 |
| `model.sol.create('sol1')` + `.study('std1')` + `.createAutoSequence('std1')` + `.runAll` | 标准求解四步。 |

### 7.7 带电粒子追踪 (CPT) 物理场
| 调用 | 说明 |
|---|---|
| `cpt = comp1.physics.create('cpt','ChargedParticleTracing','geom1')` | 自动带`wall1`(默认Freeze)、`pp1`(默认电子)、`dpcon1`（见§2.1）。 |
| `cpt.create('inl1','Inlet', 2)` + `.selection.named(...)` + `.set('N',1)` | 从边界发射粒子；默认`v0=0`、方向=边界法向。**不是**`Release`/`ReleaseFromBoundary`。 |
| `inl1.set('VelocitySpecification','Thermal')` + `.set('T_src','userdef')` + `.set('T','2700[K]')` | 内置热发射（Maxwell-Boltzmann通量加权分布）release模式。合法取值：`VelocitySpecification`∈`"SpecifyVelocity"`(默认)/`"SpecifyMomentum"`/`"SpecifyKineticEnergy"`/`"Thermal"`；`InitialVelocity`(另一个属性)∈`"Expression"`/`"ConstantSpeedHemisphere"`/`"ConstantSpeedCone"`/`"ConstantSpeedLambertian"`。`T`默认`293.15[K]`。 |
| `cpt.create('ef1','ElectricForce', 3)` + `.selection.named(sel_vac)` + `.set('E_src','root.comp1.es.Ex')` | 把es物理场的电场耦合进粒子受力（见§2.3）。**不是**`model.multiphysics.create(...)`。 |

### 7.8 时间相关粒子追踪 Study（含"复用已存 ES 场"的关键设置）
| 调用 | 说明 |
|---|---|
| `std2.create('time1','Transient')` + `.set('tlist','range(0,dt,tmax)')` + `.setEntry('activate','es',false)` + `.setEntry('activate','cpt',true)` | 只重新求解cpt，跳过重解es。 |
| `model.sol('sol2').feature('v1').set('notsolmethod','sol')` + `.set('notsol','sol1')` | 必须显式加这两行，否则粒子受力为0（见§2.4）。属性名是`notsol`，**不是**`notsolnum`。 |
| 排查手段 | `mphinterp(model,'es.normE','coord',coords,'dataset','dset2')`对比`'dataset','dset1'`，处处为0说明踩了这个坑。 |

### 7.9 结果绘图 / 导出
| 调用 | 说明 |
|---|---|
| `pg = model.result.create(tag,'PlotGroup3D')` | 三维绘图组。 |
| `pg.create('slice1','Slice')` + `.set('quickplane','xy'/'yz'/'zx')` + `.set('quickznumber','1')` + `.set('expr','V'/'es.normE')` | 切面图。 |
| `pdset1 = model.result.dataset.create('pdset1','Particle')` + `.set('solution','sol2')` | 粒子轨迹图必须用专门的Particle数据集，属性名是`solution`不是`data`（见§2.8）。 |
| `pg3.create('traj1','ParticleTrajectories')` | 轨迹图层，`data`指向`pdset1`。 |
| `model.result.export.create(tag,'Image')` + `.set('plotgroup',...)` + `.set('pngfilename',...)` + `.run` | 图片导出。**批处理模式下`ParticleTrajectories`导出有已知稳定性风险，见`COMSOL_调试方法论.md`**；普通Slice/Surface图没有这个问题。 |
| `.label('自定义字符串')` | 几乎所有Java API对象（geometry feature、selection、material、physics接口及子特征、mesh、study、solver、result dataset、plot group）都支持，跟tag完全独立，且会持久化进.mph文件。**应该在写`create(tag,type)`之后顺手加一行，成本几乎为零**——否则COMSOL Desktop的Model Builder树里全是"Cylinder 1"这类无信息量的默认名。 |

### 7.10 数值提取函数：mpheval / mphinterp / mphparticle 该怎么选
| 需求 | 用哪个 | 关键点 |
|---|---|---|
| 任意坐标处插值某个场量 | `mphinterp(model, 'expr', 'coord', coords, 'dataset', tag)` | 坐标单位=`geom.lengthUnit`（见§2.7坑A）；粒子study的`dataset`要配合`'t', t值`才能拿到某一时刻切片，`'outersolnum','end'`不代表最后一步（见§2.7坑B）。 |
| 取粒子在某时刻的坐标/其他量 | ~~`mpheval(...,'dataset','dset2','edim',0)`~~不要用（见§2.6） | 正确：`mphparticle(model,'dataset','pdset1')`。 |
| 取粒子末态动能 | 能量守恒法（见§2.5） | 前提：粒子从V≈0处以≈0eV初速释放、纯静电场加速。 |
| ~~`cpt.Ep`/`Ek`/`KE`/`kin_en`/`Ekin`/`speed`/`U`/`qx`/`vx`~~ | 不存在，不要试 | 用能量守恒法代替。 |
| 对`Particle`类型数据集用`mpheval`并传`'edim'`参数 | 不要用，会卡死 | 用`mphparticle`，不要传`edim`。 |
| 碰撞计数变量(`cpt.coll1.elastic1.Nc`等) | `mphparticle(model,'dataset','pdset1','expr',{'cpt.coll1.elastic1.Nc'})` | `mphinterp`完全不支持粒子数据集；`mpheval`报"Undefined variable"即使表达式正确。返回结构体多出`d1`字段（`[nTimes x nParticles]`）。`Nc`在粒子被吸收后保持不变（冻结值），不是持续累加到`t_end`。 |
| `mphparticle`的`'expr'`选项是否能减少传输数据量 | **不能**，实测即使只请求`{'qz'}`，`pd.p`依然是`[ntime x nP x 3]` | 真正有效的内存控制手段只有减少N或减少存储的时间步数。 |

### 7.11 GPU 求解器 (cuDSS)
见本文件§4。

### 7.12 已确认无效/错误的调用（黑名单，不要重试）
- `model.multiphysics.create('epf1','ElectricForce', ...)` → "Unknown multiphysics coupling"（正确见§7.7）。
- `geom1.getNEdge(tag)` → 方法不存在（正确见§7.2 `mphgeominfo`）。
- `geom1.feature.create('fil1','Fillet')` / `'Chamfer'` → 许可证限制（正确见§7.2 Cone−Cylinder手工倒角）。
- `cpt.Ep`/`Ek`/`KE`/`kin_en`/`Ekin`/`speed`/`U`、`comp1.qx`/`cpt.qx`/`cpt.vx` → "Undefined variable"（正确见§7.10能量守恒法）。
- `mpheval(...,'dataset','dset2','edim',0)`取粒子坐标 → 不报错但语义错误，返回FEM网格顶点数据（正确见§7.10 `mphparticle`）。
- `mpheval(...,'dataset','pdset1','edim',0)` → 卡死（正确见§7.10 `mphparticle`，不要传`edim`）。
- `model.sol('sol2').feature('v1').set('notsolnum', 'sol1')` → 报错（正确属性名见§7.8 `notsol`）。
- `v1.set('notstudy'/'notsollist'/'notsolstudy'/'notsolstudystep', ...)` → "Unknown property"（正确见§7.8 `notsol`+`notsolmethod`）。
- `'outersolnum','end'`用于取时间相关/粒子数据集的"最后一步" → 实际取回所有时间步×所有粒子（正确见§7.10显式传`'t',tend`）。
- `comsolmphserver.exe ... -3drend sw -graphics`（长期运行的共享服务端上使用） → 有实测记录会在后续操作异步崩溃，不推荐。
- `mesh1 = comp1.mesh.create('mesh1'); mesh1.feature('size').set('hauto',N); mesh1.run;`（不显式加`FreeTet`） → 在简单几何上能用，换到更复杂几何上会静默生成空网格（正确见§7.6 `FreeTet`+`mphmeshstats`检查）。
- `comp1.physics.create('mf','MagneticFields',...)` → "Unknown physics interface"（正确tag见§7.14 `InductionCurrents`）。
- `std1.create('cga1','CoilGeometryAnalysis')` → "Operation cannot be created in this context"（正确见§7.14 `CoilCurrentCalculation`）。
- `mphinterp(model,'es_rf.Ex',...)` / `'es_dc.normE'`（自定义物理场tag直接当变量名用） → "Undefined variable"（正确见§7.18变量命名空间说明）。
- `comp1.selection.create(tag,'Union')` / `'Difference'` + `.set('input2',{...})`（组件级别选择组合运算） → 未验证可靠，正确做法见§7.19（`Adjacent`取全部实体ID + MATLAB `setdiff` + `Explicit`选择类型）。
- `p.set('h','10[mm]')`（用`h`作为自定义模型参数名） → "Duplicate parameter/variable name"（`h`是COMSOL保留全局变量名，换成`h_cyl`等）。
- `inl1.set('v0','5[m/s]')`（`Inlet`的`v0`给标量表达式） → "A vector of length 3 expected"（正确见§7.19 `{'0','0','v'}`）。
- 回旋运动类CPT测试，`MeshBased`域内撒点后随手挑一个粒子分析、且圆轨道直径接近或超过域尺寸 → 测得半径可能精确是理论值的整数分之一，是轨道被边界截断，不是物理误差（正确排查见§7.21）。
- `std1.create('sss1','StationarySourceSweep')`用于单线圈 → 求解时报"No sources found."（这是给多线圈互感扫描用的，见§7.14）。
- `cpt.create('lf1','LorentzForce',...)` → 不存在，正确名字是`'MagneticForce'`（见§7.15）。
- `rel1.set('InitialPosition', 'Manual')` 或 `cpt.create('rel1','Release',0)`（点级别） → 前者"Invalid parameter value"（合法值只有MeshBased/Density/RandomPosition），后者"Cannot create feature in the specified element dimension"（`Release`只能在edim=3创建，见§7.15）。
- `ppi1.set('InteractionType'/'ForceType'/'Interaction', ...)` → "Unknown parameter"，正确属性名是`InteractionForce`（见§7.15）。
- `MagneticForce`/`ElectricForce`等力特征忘记`.selection` → 不报错，静默让力处处为零，容易被误判成"物理是对的"（见§7.15/§8.5）。
- 同一component里创建第二个同类型物理场时用自定义tag引用变量（如`'es_rf.Ex'`） → "Undefined variable"，COMSOL变量命名空间不跟着自定义tag走，按类型自动编号`es`/`es2`（见§7.18）。

### 7.13 服务端启动命令
```powershell
& "D:\COMSOL 6.4\COMSOL64\Multiphysics\bin\win64\comsolmphserver.exe" -port 2036 -multi on -silent
```
默认`-3drend ogl`（不加软件渲染参数）是目前证据下更稳的选择。

### 7.14 磁场物理场 (Magnetic Fields) 与 Coil 特征
| 调用 | 说明 |
|---|---|
| `comp1.physics.create('mf','InductionCurrents','geom1')` | "Magnetic Fields"物理场接口的内部tag是`InductionCurrents`，不是`MagneticFields`。属于AC/DC Module，即使`model_inspect`的`modules`列表没显式列出"AC/DC"也可能可用——不要仅凭modules列表断定不可用，直接试一次更可靠。默认自带`fsp1`/`mi1`/`init1`。 |
| `mf.create('coil1','Coil', 3)` + `.selection.named(域选择)` | 在任意三维实体域上定义"这是一个载流导体"。`CoilType`默认`'Numeric'`（合法值：`"Numeric"/"Circular"/"Linear"/"UserDefined"`），任意真实3D形状用Numeric。`CoilExcitation`合法值`"Voltage"/"Current"/"CircuitVoltage"/"CircuitCurrent"`。`N`(匝数倍率)如果线圈真实绕线已经在几何里画出来，设成`'1'`，不要用默认的`'10'`（默认给"匀质化"简化线圈用）。 |
| `coil1.feature('ccc1').feature('ct1').selection.set(边界编号)` | Numeric类型的Coil会自动带`cg1`/`ccc1`(内含`ct1`)/`cre1`。`ct1`必须显式指定一个边界选择，否则报"No selection specified for the Input subfeature"。 |
| Coil所在域必须有材料的`electricconductivity`(sigma) | 否则报"Undefined material property 'sigma'"。给线圈材料一个真实电导率，周围"空气"域给0。 |
| **`std1.create('ccc_step1','CoilCurrentCalculation')`必须在`std1.create('stat1','Stationary')`之前加进同一个Study** | 极易漏掉：只有Stationary会报错"Numeric coil ... not solved for. Solve it in a Coil Geometry Analysis step."。study-step类型不是`'CoilGeometryAnalysis'`，也不是`'StationarySourceSweep'`（那个是多线圈互感扫描用），是和`ccc1`同名的`'CoilCurrentCalculation'`。 |
| `mphinterp(model,'mf.Bz','coord',...,'dataset','dset1')` | 取磁通密度分量，和es物理场取`V`/`es.normE`写法一致。 |
| 完整可跑通的参考脚本 | `test_magnetic_coil.m`（螺旋线圈通1A电流，中心B场/无限长螺线管估算比值≈0.85）。 |

### 7.15 CPT 中的磁场力 / 点释放 / 发射方向分布 / 壁面条件 / 粒子间相互作用
| 调用 | 说明 |
|---|---|
| `cpt.create('mf1','MagneticForce', 3)` | 洛伦兹力的磁场部分，**不是**`'LorentzForce'`。`B_src`合法值：`"EarthsMagneticField"`/`"userdef"`/`"fromCommonDef"`（如果模型还有已求解的`mf`物理场，还会出现`"root.comp1.mf.Bx"`）。`userdef`模式用`.set('B', {'0','0','0.01[T]'})`。**⚠️必须显式`.selection.all`（或`.selection.named(...)`）指定作用域**——为空时不报错，只让磁场力处处为零，粒子走直线（速度大小仍守恒，容易被误判成"物理是对的"）。排查方法：先画轨迹图看是不是直线，而不是只看有没有报错。 |
| `cpt.create('rel1','Release', 3)` | 域(3维)级别粒子释放特征，"体内释放"。`InitialPosition`合法值只有`"MeshBased"/"Density"/"RandomPosition"`——**没有手动指定单点坐标的选项**。`v0`支持直接设三分量向量。 |
| `inl1.set('InitialVelocity','ConstantSpeedHemisphere'/'ConstantSpeedCone'/'ConstantSpeedLambertian')` | 固定速度大小、方向按分布随机撒开：半球均匀/限定圆锥角内均匀/圆锥角内按余弦定律加权。配套属性`alphac`(圆锥半角，默认`pi/3`)。 |
| `cpt.feature('wall1').set('WallCondition', ...)` | 合法值：`"Bounce"/"Freeze"/"Stick"/"Disappear"/"Pass"/"DiffuseScattering"/"IsotropicScattering"/"MixedDiffuseSpecular"/"GeneralReflection"`。默认`Freeze`。 |
| `cpt.create('ppi1','ParticleParticleInteraction', 3)` | 粒子间相互作用，属性名是`InteractionForce`（不是`InteractionType`/`ForceType`），合法值`"Coulomb"`(默认!)/`"LinearElastic"`/`"LennardJones"`/`"UserDefined"`。配套属性`ks`/`r0`/`rcoff`/`sigma`/`eps`/`Fu`。 |
| 完整可跑通的参考脚本 | `test_cpt_magnetic_force.m`（均匀Bz场电子回旋，实测半径0.58mm vs理论0.57mm，误差2%）。 |

### 7.16 多极杆 (Quadrupole/Hexapole/Octupole)
| 调用 | 说明 |
|---|---|
| N根圆柱杆沿方位角均匀排布 | MATLAB循环算每根杆的`pos`：`x=R_center*cos(theta_k)`, `y=R_center*sin(theta_k)`，`theta_k=(k-1)*360/N`。经典四极杆理想双曲面近似半径比`r_rod=1.1468*r0`。 |
| 相邻杆交替`+V_rf`/`-V_rf` | 偶数N才能严格交替；配合`Complement`选择拿真空域（不要用外层大圆柱的selresult，见§7.2）。 |
| **物理验证**：中心电位/场应为0，偏轴电位应按`r^(N/2)`幂律增长 | 四极(N=4) `V∝r^2`吻合4位有效数字、六极(N=6) `V∝r^3`、八极(N=8) `V∝r^4`——这是检验多极杆几何+交替电位设置对不对的最快方法。 |
| RF时变场加到CPT：方案A(手写表达式) | 静电场只解一次(单位幅值)，CPT的`ElectricForce`用`E_src='userdef'`+表达式`(V_target/V_rf_solve)*es.Ex*cos(2*pi*f_rf*t)`——同一个静电解，换幅值/频率完全不用重新解静电场。 |
| RF时变场加到CPT：方案B(原生振荡模式) | `ef1.set('TimeDependenceOfField','TimeHarmonic')`+`.set('FrequencySpecification','SpecifyFrequency')`+`.set('omega', f_rf)`+`phi0`。`MagneticForce`也有同样一组属性。（本项目未完整验证，只确认属性存在。） |
| `ElectricForce`还有`SpecifyForceUsing`(合法值`"ElectricField"`(默认)/`"ElectricPotential"`) | 除了给电场表达式，也可以直接给电位表达式让特征内部做`-∇V`。 |
| 离子(区别于电子)粒子属性设置 | `cpt.feature('pp1').set('mp', '100*1.66054e-27[kg]')`+`.set('Z','1')`(默认电子`Z=-1`，别忘了改)。 |
| **马蒂厄方程稳定性判据实测验证** | 四极杆(N=4)，q=0.5(理论稳定)时最大偏移中位数仅0.26*r0；q=1.2(超过稳定边界)时100%超过r0，明显发散。 |
| `Release`用`MeshBased`在整个真空域释放时的采样偏差 | 大量释放点会落在靠近杆表面/外边界的网格节点上，做"近轴动力学"这类测试必须在后处理时按初始半径过滤释放点。 |
| 完整可跑通的参考脚本 | `test_multipole_geometry.m`+`test_multipole_es.m`+`test_quadrupole_stability.m`。 |

### 7.17 爱因茨尔透镜 (Einzel Lens)
| 调用/发现 | 说明 |
|---|---|
| 几何 | 3片同轴圆盘(接地-透镜-接地)，每片用"实心圆柱-同轴小圆柱"布尔差挖出中心通孔。 |
| **聚焦强弱只取决于`KE_beam/|V_lens|`这个无量纲比值** | 静电透镜的基本标度律，绝对值不同但比值相同会给出完全相同的聚焦效果。 |
| 反射风险 | `|V_lens|<KE_beam/e`，否则粒子会在到达透镜中心前被反射回去。 |
| 完整可跑通的参考脚本 | `test_einzel_lens.m` + `test_einzel_cpt.m`。 |

### 7.18 线性离子阱 (Linear Ion Trap, LIT)
| 调用/发现 | 说明 |
|---|---|
| 几何 | 四极RF杆(径向约束)+两片端盖孔径电极(轴向约束，挖孔圆盘手法)，共享同一个真空域。 |
| **同一component里两个同类型物理场的坑：自定义tag不是变量命名空间** | 建了`es_rf`/`es_dc`两个`Electrostatics`后，`mphinterp`/CPT表达式里写`'es_rf.Ex'`全部报"Undefined variable"。**COMSOL变量命名空间按物理场类型+创建顺序自动分配默认前缀**：第一个`Electrostatics`永远是`es`(依赖变量`V`)，第二个自动变成`es2`(依赖变量`V2`)，不管Java API tag叫什么。自定义tag只在Java API层有效。**排查方法：依次探测`V`/`V2`/`es.Ex`/`es2.Ex`。** |
| RF+DC合成力表达式 | `ef1.set('E', {'(Vrf/100)*cos(2*pi*f*t)*es.Ex+(Vdc/100)*es2.Ex', ...})`。 |
| 完整可跑通的参考脚本 | `test_lit_geometry_es.m` + `test_lit_cpt.m`。 |

### 7.19 飞行时间分析器 (TOF) + 反射器 (Reflectron) 基础版
| 调用/发现 | 说明 |
|---|---|
| 几何 | 源极盘→挖孔引出栅极(接地)→漂移管(真空)→实心反射镜电极，挖孔圆盘手法。 |
| **⚠️漂移管必须有接地导体壁，否则远端电极的场会"漏"穿整个漂移区** | 光是不设边界条件不够，必须有接地导体真正屏蔽远处电极。 |
| **组件级别的Union/Difference选择类型不可靠，改用MATLAB端`setdiff`** | `Adjacent`选择拿到全部边界的实体ID数组，MATLAB `setdiff`算差集，再用`Explicit`选择类型建立最终选择。 |
| **平板电极的离轴离子径向散焦是真实物理，不是bug** | 有限半径平板电极边缘场散焦——真实反射式TOF仪器常用弯曲反射镜面或多层网格梯度而不是单一平板镜就是为了避免这个问题。 |
| `Inlet`的`v0`哪怕想表示"标量速度"也必须给三分量向量 | `inl1.set('v0','0[m/s]')`报错，必须写`{'0','0','v_extra'}`。 |
| 参考脚本 | 该基础版已被oa-TOF环栈反射镜取代，本节记录的物理教训（接地漂移管壁、平板边缘径向散焦）仍然有效。 |

### 7.20 静电扇形场能量分析器 (ESA)
| 调用/发现 | 说明 |
|---|---|
| 几何 | 同轴圆柱电容器：内层接地，外层加正电压，中间环形真空隙供离子飞行。**关键坑：内外电极务必被一个更大的"整体真空圆柱"完全包住**。 |
| **设计电压公式（同轴柱形电容器精确解）** | `E(r)=V0/(r*ln(R2/R1))`（不是平行板近似）。 |
| **FEM与解析式验证：4位有效数字吻合** | 比值全部落在0.9998~1.0002之间。 |
| **能量选择性定量验证** | 设计能量离子稳定运行；偏高30%的离子精确撞在外电极半径处——ESA按能量筛选离子、与质量无关。 |
| `'h'`是保留的COMSOL全局变量名 | 自定义参数避开这个名字。 |
| 完整可跑通的参考脚本 | `test_esa.m`。 |

### 7.21 磁扇形场质谱仪 (Magnetic Sector)
| 调用/发现 | 说明 |
|---|---|
| 原理 | 固定加速动能KE，`r=m*v/(qB)=sqrt(2*m*KE)/(qB)`，`r∝sqrt(mass)`。 |
| **⚠️`Release`(MeshBased)测回旋运动时，必须保证"整个圆轨道直径"远小于域尺寸** | 挑到离边界太近的粒子会被边界截断，测出的"直径"可能精确是理论值的整数分之一——比值恰好是"干净的分数"通常意味着轨迹被截断，不是物理误差。 |
| **定量验证** | `r∝sqrt(mass)`吻合5位有效数字。 |
| 完整可跑通的参考脚本 | `test_magnetic_sector.m`。 |
| **本节及§7.16-7.27所有CPT类测试脚本约定：都必须存轨迹图** | `figure('Visible','off')`+`print(...,'-dpng','-r150')`，比单纯看数字更容易发现问题。 |
| **⚠️外部MATLAB画的PNG轨迹图 ≠ .mph文件里能看到轨迹** | 必须显式调用`model.result.create(...,'PlotGroup3D')`建立COMSOL原生结果节点，再`model.save(...)`，否则COMSOL Desktop打开时Results树里看不到粒子轨迹。 |
| **⚠️原生轨迹图太多太杂看不清：正确修复是限制"释放范围"，不是事后过滤** | `Filter`类型的Plot Group/Trajectory子特征、`Filter`数据集接到`ParticleTrajectories`、`Ball`选择限制释放范围——都不work。**真正有效**：在几何里加一个小圆柱体`relvol`专门作为释放子区域，`Release`特征的`.selection`只指向`geom1_relvol_dom`，CPT物理场仍选整个`sel_vac`。 |

### 7.22 CPT 背景气体碰撞 (`Collisions` 特征，适用于碰撞池/CID建模)
| 调用/发现 | 说明 |
|---|---|
| `cpt.create('coll1','Collisions',3)` | 正确名字就是`'Collisions'`（不是`GasCollisions`/`BackgroundGas`等）。 |
| 关键属性 | `Nd`(背景气体数密度，默认`1E20[1/m^3]`) / `mg`(默认`0.04[kg/mol]`，恰好是氩气摩尔质量) / `T`(默认`293.15[K]`)。 |
| **⚠️关键坑：`Collisions`特征本身只是容器，不加子特征(Attribute)碰撞完全不生效** | `Nd`从1e20试到1e28全部零效果。真正定义"发生哪种碰撞、截面多大"的是挂在它下面的Attribute子特征（`Elastic`/`ResonantChargeExchange`等），不加Attribute等于截面隐式为零。 |
| **正确的最小可用配方** | `elastic1 = coll1.create('elastic1','Elastic'); elastic1.set('CountCollisions', true);`——默认自带常数截面`xsec=3E-19[m^2]`。 |
| `StudyStep`属性需要显式绑定到实际求解的时间相关study | 先建了多个study的模型都应显式设置一遍，避免叠加坑。 |
| **⚠️碰撞计数变量的正确取值方式：只有`mphparticle`的`'expr'`选项能用** | `mphparticle(model,'dataset','pdset1','expr',{'cpt.coll1.elastic1.Nc'})`。 |
| 完整可跑通的参考脚本 | `test_collision_cell.m` / `test_collision_cell_gpu_comparison.m`。 |

### 7.23 Wien 滤波器 (交叉 E×B 速度选择器)
| 调用/发现 | 说明 |
|---|---|
| 物理原理 | `qE=qvB`给出`v=E/B`——只和速度有关，和质量、电荷无关。 |
| 建模方式 | `ef1.set('E_src','userdef')`+`ef1.set('E',{E0,'0','0'})`，`mf1.set('B_src','userdef')`+`mf1.set('B',{'0',B0,'0'})`，叠加在同一个`cpt`下即可。 |
| **⚠️坑：偏转量必须相对释放起始位置算，不能直接看终点绝对坐标** | `MeshBased`释放会带来随机初始小偏移，必须算`x_end-x_start`。 |
| 完整可跑通的参考脚本 | `test_wien_filter.m`。 |

### 7.24 ParticleParticleInteraction 库仑排斥/空间电荷效应
| 调用/发现 | 说明 |
|---|---|
| **真实离子间库仑力在常规质谱仪时间尺度/离子间距下极弱** | 需要用极低动能+极紧密初始离子团才能在合理仿真时长内看到效果。 |
| **验证结果** | 加`ppi1`后径向扩散标准差涨到33倍，最大半径涨到28倍。 |
| 完整可跑通的参考脚本 | `test_space_charge.m`。 |

### 7.25 Resonant Charge Exchange (共振电荷交换) 碰撞类型
| 调用/发现 | 说明 |
|---|---|
| 物理原理 | 离子把电荷"转移"给静止的中性背景气体原子，特征信号是速度几乎瞬间掉到接近零（区别于Elastic的渐进式散射）。 |
| 建模方式 | 和`Elastic`同一套模式：`cex1 = coll1.create('cex1','ResonantChargeExchange')`。 |
| 完整可跑通的参考脚本 | `test_resonant_charge_exchange.m`。 |

### 7.26 FTICR/ICR 离子回旋共振池
| 调用/发现 | 说明 |
|---|---|
| 组件构成 | 均匀轴向磁场(回旋，径向约束)+两端DC捕集电极(轴向约束)。 |
| **⚠️关键坑：两个端盖电极给同一个正电压、没有接地参考，导致轴向电位完全没有梯度** | 拉普拉斯方程只有两个"电位相同"的边界条件时解是平凡常数。**修复**：把圆柱侧壁显式接地。 |
| **验证结果：组合运动出现真实的"磁控漂移"(magnetron drift)现象，不是bug** | 回旋频率与轴向捕集频率量级相当时两种运动强耦合，真实FTICR仪器要求回旋频率远高于轴向捕集频率才能让两者干净分离。 |
| 完整可跑通的参考脚本 | `test_icr_cell.m`。 |

### 7.27 简单质谱仪整机集成
| 调用/发现 | 说明 |
|---|---|
| **总体架构：分阶段建模，而非塞进单一网格** | CPT物理场每个接口只允许一个`ParticleProperties`，电子和离子不能共用一个`cpt`接口——电离阶段和"离子旅程"阶段必须是两个独立模型。 |
| `Ionization` Collision Attribute | `ReleaseSecondaryElectron`默认`true`——每次电离碰撞会真的生成新粒子，容易导致粒子数指数增长、内存爆炸，实际EI场景应设`false`。 |
| `Release`的热发射叫`Maxwellian`(不是`Inlet`用的`Thermal`) | `Maxwellian`模式会把速度分布按`Nvel`(默认200)个离散速度档确定性采样，**每个释放点会被复制成约200份**，容易导致内存爆炸。 |
| 正离子受力方向 | `F=qE=-q∇V`，repeller必须在高电位、引出栅在低电位。 |
| RF离子导管约束高速离子束时 | 关键看"离子穿越时间/RF周期"这个比值是否远大于1。 |
| N极杆近轴回复力标度`r^(N-1)` | 离子非常靠近轴线时，四极杆(线性回复力)反而比高阶极杆更稳健。 |
| 小孔透镜散焦效应 | 引出栅孔径相对下游主体半径比值越小，散焦越严重。 |
| 分辨率计算 | `R=t/(2·FWHM)`，`FWHM=2.3548σ`。 |
| 完整可跑通的参考脚本 | `ms_stage1_ei_source.m`。 |

### 7.29 理想细网格栅网(内部边界)技术 + CPT `Release`分布/随机化 API 速查

> 独立于任何具体项目的通用技术：任何需要"电极但离子必须能穿过"的场景都适用。

| 调用/发现 | 说明 |
|---|---|
| **建造理想细网格栅网：`Union`+`intbnd=true`** | ```matlab\nwp = geom1.feature.create('wp_tag', 'WorkPlane');\nwp.set('quickplane', 'xy'); wp.set('quickz', z_expr);\nwp.geom.feature.create('r1', 'Rectangle');\nwp.geom.feature('r1').set('size', [800 800]);\nwp.geom.feature('r1').set('pos', [-400 -400]);\ngeom1.feature.create('uni_grids', 'Union');\ngeom1.feature('uni_grids').selection('input').set({'vacbox','wp_tag'});\ngeom1.feature('uni_grids').set('intbnd', true);\n```。`Ndomains`应该保持不变。因为离子能从整个面任意穿过，**栅网不再需要开孔**，直接做成和真空域截面等大的整块board即可——这比"实心板挖孔"（会有孔径-透镜散焦效应）根本地好。 |
| **给内部边界加电位：用Box+`'allvertices'`选择** | ```matlab\ncomp1.selection.create('selb_grid', 'Box');\ncomp1.selection('selb_grid').set('xmin',-400); ...set('xmax',400);\ncomp1.selection('selb_grid').set('zmin',[z_expr '-1[mm]']); ...set('zmax',[z_expr '+1[mm]']);\ncomp1.selection('selb_grid').set('condition', 'allvertices');\ncomp1.selection('selb_grid').geom('geom1', 2);\n``` |
| **⚠️陷阱：`Box`/`Cylinder`选择用`'intersects'`条件会误抓不相关边界** | 两个电位条件抢同一个边界ID时COMSOL不报错，只是其中一个静默失效。**表现症状**：`selection.entities()`对"选择集本身"查询正常，但对"已经赋给某个物理特征的selection"查询显示0。**修复**：一律换成`Box`+`'allvertices'`，范围完整指定三个维度。 |
| **⚠️陷阱：两个应该衔接的真空域之间留几何缝隙** | 离子精确停在缝隙边缘，且**不随仿真时长增加而改变**——这正是判定"缝隙/边界问题"而非"仿真时间不够"的信号（纯时间不足会让轨迹再往前挪一点）。**修复**：让两个域的z范围有实打实的重叠。 |
| **CPT `Release`：显式指定释放粒子数** | `InitialPosition='Density'` + `N=<count>`，而非依赖网格节点数(`MeshBased`默认)。 |
| **`InitialKineticEnergy`是模式选择器枚举，不是自由表达式字段** | 合法值`"Expression","ConstantSpeedSpherical","ConstantSpeedHemisphere","ConstantSpeedCone","ConstantSpeedLambertian"`。**`v0`才是真正的自由表达式字段**，需要能量分布随机化时把能量公式换算成速度写进`v0`。 |
| **⚠️`randnormal()`不是COMSOL函数——用`random()`(均匀分布)手动Box-Muller构造高斯分布** | `sqrt(2*abs(E_mean_eV+E_std_eV*sqrt(-2*log(random(1)))*cos(2*pi*random(2)))*1.602176e-19[C]/m_kg)`。**单位陷阱**：基本电荷常数必须显式标`[C]`。`SamplingFromDistribution`需设`'Random'`，否则每个粒子拿到同一个值。 |
| **粒子数量大时的内存教训** | 电场求解耗时与粒子数无关，只跟网格规模有关；CPT求解本身可行到数万粒子，但`mphparticle`取回完整轨迹数据在极大N时会"Out of memory on server"。**教训**：只提取需要的统计量，或放宽CPT输出tlist的时间步密度（脉冲/快速动态段保留精细步长，纯漂移段可以粗化），不要囫囵吞枣地拉全部时间步×全部粒子的数据。 |

---

## 8. 磁场建模全流程实测记录（附：完整调试叙事，支撑上面§7.14/§7.15速查表）

> 这是§7.14/§7.15速查表背后的完整调试过程叙事，是本项目第一次接触Magnetic Fields/
> 洛伦兹力，之前全部只涉及Electrostatics+Charged Particle Tracing。

### 8.1 定位正确的物理场 tag：`InductionCurrents`
直接尝试`comp1.physics.create('mf','MagneticFields','geom1')`报"Unknown physics
interface"。没有现成的"列出所有可用物理场"API，只能挨个猜候选tag名：`MagneticFields`
(✗) / `InductionCurrents`(✓) / `MagneticFieldsNoCurrents`(✗) /
`RotatingMachineryMagnetic`(✓，但不是要的) / `ACDC`(✗)。**教训：COMSOL Java API里物理
场的"内部tag"和GUI里显示的名字经常对不上，纯靠试错定位，直接试一次比纠结许可证文档快。**

### 8.2 用已验证的 Helix 几何直接当线圈导体，走通 `Coil` 特征
`mf.create('coil1','Coil',3)`直接选中电子枪项目里已验证的Helix螺旋线圈实体作为域，
`CoilType`默认就是`'Numeric'`，完全不需要额外建模——本来是为电子枪灯丝设计的几何，
直接拿来当电磁铁线圈测试也一次成功。

### 8.3 三层报错，逐层剥开 Numeric Coil 的真实求解要求
依次遇到、依次解决的三个报错（每一个都会掩盖下一层）：
1. `"No selection specified for the Input subfeature under the Geometry Analysis
   subfeature"` → Coil的`ccc1.ct1`(Input终端)需要显式选一个边界。
2. `"Undefined material property 'sigma' required by Domain Coil 1"` → 线圈域必须有
   电导率材料属性。
3. `"Numeric coil Domain Coil 1 (coil1) not solved for. Solve it in a Coil Geometry
   Analysis step"` → **最隐蔽的一步**：`std1.create('stat1','Stationary')`单独存在
   不够，必须在它*之前*额外`std1.create('ccc_step1','CoilCurrentCalculation')`。
   试过`'CoilGeometryAnalysis'`(报"Operation cannot be created in this context")和
   `'StationarySourceSweep'`(能创建+求解，但报"No sources found."，是给多线圈互感扫描
   用的)，最终靠"study-step类型名字可能和物理场自动生成的子特征同名"这个直觉试出
   `'CoilCurrentCalculation'`。

### 8.4 定量验证：有限长螺线管中心磁场
5匝、线圈半径0.3mm、通电1A，解出中心轴向`Bz=5.33e-3 T`，对比无限长螺线管理想公式
`mu0*N*I/L=6.28e-3 T`，比值0.85——完全符合"有限长度、匝数不多的螺线管，中心场应该略
小于无限长理想值"的物理直觉。

### 8.5 CPT 磁场力：一次"没报错但结果全错"的排查
配好`MagneticForce`后模型顺利求解，`|v|`全程精确守恒（磁场力不做功，看似过关的信号），
但轨迹是一条几乎笔直的线，完全没有回旋。**根因：`MagneticForce`特征创建后忘了调用
`.selection`，默认作用域是空**——这和`Release`/`Inlet`没选择时会在编译期直接报错不
同，力类特征选择为空时**不报错，只是让力处处为零**，粒子保持初速直线运动，由于磁场力
不做功，连"能量守恒"这个常规正确性检查都不会揭穿它。补上`mf1.selection.all`后轨迹立刻
变成漂亮的正圆，回旋半径0.58mm对比理论0.57mm，误差2%。**教训：CPT里所有"力"类特征都
要把"有没有设置selection"当成检查清单的第一项。**
