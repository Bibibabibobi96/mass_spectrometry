# 正交脉冲加速器项目状态

## 项目边界

本项目拥有独立正交脉冲加速器的理论、计算、参数化器件几何和验证。二区与三区通过
`../config/component_contract.json`声明为结构变体，分别保持输入、resolved几何和证据身份。
项目ID为`orthogonal_accelerator`；它不继承oa-TOF整机的Formal资格。

## 当前迁移

用户于2026-09-03批准从oa-TOF及`common/accelerator/`迁入独立领域实现，并同步integration源码依赖。
领域源码、活动消费者和依赖清单已迁移，纯分析及消费者focused回归通过；原生SIMION构建与独立
几何/电压抽查已经执行。完整仓库文档门禁被既有`artifacts/_maintenance`未登记目录阻断，不能据
focused回归报告全仓PASS；原生构建run另有下述容量治理失败，不报告整体迁移验收全通过。

- 原公共二区焦距、环电极和屏蔽几何归本项目，所有消费者切换到同一实现。
- OA中的纯二区计算、三区局部精确时间和导数归本项目；反射器、总飞行路径、源到探测器的联合聚焦
  与整机分辨率分析仍归OA。
- 器件SIMION/COMSOL生成归本项目；OA/MR只保留系统参数投影和装配。整机CAD导出不整体搬走。
- integration依赖清单同步到新源码；已经启动的run-local冻结包、Formal二进制和历史结果不改写。

器件实现包括`simion/rectangular_accelerator.py`（MR矩形环/屏蔽）、
`simion/sectioned_accelerator.py`（两/三区、方/圆截面）、`simion/build_two_zone_pa.lua`及其GEM，
以及`comsol/build_two_zone_geometry.m`和`comsol/build_two_zone_grids.m`。SIMION构建器的26个参数
必须显式传入；不保留OA尺寸或电压默认值。通用数字、盒和圆柱GEM序列化在
`common/simion/gem_primitives.py`，已由本项目和integration共同使用。

`analysis/component_contract.py`统一校验OA/MR的provider身份、API、单位、结构变体及源路径；各消费者
沿既有运行入口冻结声明、提供者合同与源文件身份。integration沿自己的依赖清单冻结精确闭包。
single-flight新增源快照与准备结束复核，但仍不宣称其整个Python执行环境已经脱离工作树。

## 参数与坐标

当前迁移的是可调用机制，不是从任一仪器复制一套通用硬件baseline。项目描述符中的baseline/resolved
仍为空，不能将旧OA电压、MR孔径或某个测试样例当作新项目的正式默认值。
每个接口明确其局部轴向与单位；环位插值可沿递增或递减标量轴，屏蔽腔和求解器布局的方向约束则必须
由各自接口明确。仪器负责刚体映射，位置包含平移、速度只旋转。MR的`z=0`焦面是消费者要求，不是
本项目共用原点。数学焦距、自由飞行观察面与真实机械检测器不是同一个对象。

## 验证与开放项

2026-09-07 MR细网格原生检查发现矩形开框的普通`notin`在`surface=none`下移除了精确孔壁节点。
`rectangular_accelerator.emit_open_rectangular_frame`现改用`notin_inside`保留边界，减槽仍沿轴向
越过两端面，不改变合同孔径与板厚。支持依据为SIMION官方
[GEM Geometry File](https://simion.com/info/gem_geometry_file.html)的“Choosing notin/notin_inside/notin_inside_or_on”
与“Intersecting within and notin_inside”（2026-09-07查阅）；网页当前标题为2026，但所述legacy
GEM语义及`surface=none`行为适用于本次SIMION 2020实测。旧PA不因源码修改继承新几何资格，
原生修复复验由MR项目记录；未改写OA或integration的冻结包。

轻量门禁验证纯理论、几何及依赖边界；不证明原生理想栅穿越、真实场、CAD同步、GUI或Formal资格。
2026-09-03已执行：

- 本项目公开静态门禁：36个Python测试及26项Lua必填参数检查通过。
- OA纵向理论和耦合回归通过；两份真实三区campaign的18项源码authority由既有入口重新生成并通过
  `T0 --validate`，剔除authority元数据前后科学合同相等。历史receipt测试缺少指定产物时明确skip。
- MR run-local依赖冻结3项回归通过，包括共享校验器真实调用、原字节/文本身份和无效API失败关闭。
- integration依赖及仿射分析5模块39项通过；含冻结后离开仓库目录导入的真实测试。frontend47项通过。
- 迁移前后MR split GEM字节相同；integration两/三区乘方/圆四种加速器GEM字节相同。
- 注册表8项目新鲜度及12项注册表测试通过；Ruff和focused门禁路由回归通过。

原生SIMION 2020样例使用冻结的既有OA样例输入，只验证代码迁移，绝非本项目独立baseline：
`runs/20260903_150208__test__simion__accelerator-migration__r02`的GEM、默认Refine和Fast Adjust
约35秒完成，11个PA文件共1,238,055,948字节，理想栅分别仅占节点行260和596。该run整体仍为failed：
临时编排误把capacity dry-run的“计划处置后满足”当作实际容量通过，实际占用593,539,744,405字节
已超过500GiB水位；未执行任何计划删除。不得以成功的求解阶段掩盖此治理失败。

独立只读run `runs/20260903_151050__test__simion__accelerator-readonly__r02`复验28个样点、5个
环孔/间隙及全部9个电极ID对应电压，通过；没有重建或复制PA。两次测试实现错误（误读`refined`
持久性、误用非公开`max_voltage`）对应的失败run也保留，后续PASS不替换它们。
SIMION 2020本机官方`docs/simion.chm`的`lua_simion.pas.html`（2026-09-03查阅）明确说明
`pa.refined`不存入文件、加载时推断，对PA#/PA0不宜用它判断保存解是否完整；求解完成依据实际构建
日志、文件族身份及只读电压核对。上述均没有离子飞行、GUI、CAD或收敛资格含义。

新增或修正的物理推导须独立数值验证；因公式修正发生的几何变化必须显式报告，不以源码迁移掩盖。
迁移审查修正了原MR辅助二区焦距公式少因子2的问题；退化等场与独立时间导数测试通过。
OA原公式没有改变。MR的焦距与放置须重新派生，旧PA/IOB不继承此修正；详情由MR的PROJECT维护。

剩余物理交付包括独立器件baseline、两种结构的完整同源几何与数值合同、CAD交付和商业求解器证据。
既有OA整机证据按原身份保留。MR-TOF当前几何修复和全链飞行仍在MR项目执行，本项目迁移不替代它们。
