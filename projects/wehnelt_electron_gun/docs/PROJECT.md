# Wehnelt电子枪当前项目状态

本文件是项目当前状态的唯一权威。选型依据和旧实验时间线只查
[`history/PROJECT_HISTORY.md`](history/PROJECT_HISTORY.md)，不得用其中的历史“当前”
覆盖本文件。

## 当前基线

当前物理基线为5匝横置螺旋钨丝、2700 K热发射的Wehnelt电子枪。当前维护源码链为
`phase1_geometry_coil_transverse.m`、`phase2_electrostatics_coil_transverse.m`和
`phase4_thermal_emission_coil_transverse.m`；实心阴极和轴向线圈源码只属于`legacy/`。

机器权威已建立为`config/baseline.json + config/numerical_modes.json → analysis/resolve_contract.py
→ config/resolved_model.json`。线圈、钨丝、节距、电位和孔径等既有数值均保持不变；完整精度和
派生轴向坐标只认机器合同，本文不再复制第二份参数表。三阶段MATLAB只消费resolved并把值绑定为
GUI可见参数，不再自行维护物理默认值或派生坐标。横置方案服务于EI离子源的电子利用率，不声明
成像级轴对称束斑。

## 资产与验证状态

当前没有通过现行门禁的formal资产。旧模型和结果冻结在
`archive/20260719_212436__migration-snapshot__repo__pre-v2-layout/legacy-layout/`。R2025b曾重算静电中间模型并
确认横置Helix、静电Study和原生场结果节点；最终CPT模型尚未在R2025b下重开和GUI Compute复算。
因此历史34.18%数值仍是待复验结果，不能作为当前已闭合性能门禁或现行usable-final-state指标。

## 已知程序问题

- 三阶段源码已移除COMSOL安装路径和`mphstart`，只能由仓库统一R2025b连接入口运行。运行
  `20260722_120100__test__comsol__three-stage-build-only`已在真实MATLAB R2025b/COMSOL 6.4连接中依次
  完成横置灯丝几何、网格、静电和CPT Study/Solver树构建并保存隔离MPH，未运行静电或粒子求解器；
  三件套manifest复核PASS。该结果不复验历史34.18%数值，也不改变当前资产资格。
- 已建立物理baseline、数值模式、来源身份和resolved过期门禁。跟踪resolved选择
  `build_only_smoke`和低N固定fixture，只验证合同读取、三阶段模型树构建与GUI参数绑定，明确没有
  Candidate或Formal证据资格。
- baseline现已成为电子species、质量、电荷、发射分布、材料身份和终态语义的唯一物理权威；phase4
  显式绑定CPT电子属性和`Freeze`壁面条件。钨目前只表示灯丝材料身份，不表示已经建立Richardson发射率
  或真实束流模型；粒子仍是未加权测试粒子，因此不支持`beam_current`声明。COMSOL默认随机采样种子尚未
  冻结，单次粒子实现不可复现；非有限末态只报告为未分类终态，不再推断为灯丝/Wehnelt自吸收。电子质量
  与元电荷取自`common/contracts/particle_physics.py`冻结的NIST 2022 CODATA常数。
- `run_build_only_smoke.ps1`是当前唯一注册的商业构建入口；它冻结合同与三阶段源码、串行调用统一
  R2025b/COMSOL入口并对`interrupted`、`failed`或`success`形成统一summary与manifest。run建立后
  立即预置可复核的`interrupted`状态；后续递归冻结实际输入/输出，持久化商业wrapper控制台与退出
  上下文。执行profile、resolver、Static gate以及实际调用的公共COMSOL/manifest入口也进入冻结清单。
  该入口不运行静电或粒子求解器。
- runner现已实际执行冻结副本中的resolver和Static gate，严格解析唯一`KEY=VALUE`报告并拒绝未知、重复、
  冲突或前后缀伪PASS；三个MPH还必须存在且非空。初始化和终态写入采用可恢复的已验证prestate，避免
  manifest写入失败留下伪终态。以上治理已通过非商业故障与冻结快照测试；商业运行证据的限定见下文。
- 修复前的`20260723_172817__test__comsol__wehnelt-build-only-smoke`把外部超时记为`failed`，
  `20260723_173100__test__comsol__wehnelt-build-only-smoke`则在输入冻结失败后留下空inputs manifest。
  它们只保留为历史不合格诊断，不用于证明当前生命周期或哈希治理；既有run内容不得追写或改写。
- 受治理运行`20260723_173500__test__comsol__wehnelt-build-only-smoke`已用冻结输入在真实MATLAB
  R2025b/COMSOL 6.4中完成三阶段构建：几何、网格和CPT树通过，GUI参数绑定通过，静电与粒子求解器
  均未运行；success manifest及其12项输入、5项输出哈希复核PASS。该run仍不具备Candidate或Formal资格。
- 现行受治理运行`20260724_135148__test__comsol__wehnelt-build-only-smoke`已在提交`b6a05f4`的干净源码上
  用冻结仓库快照完成真实MATLAB R2025b/COMSOL 6.4三阶段构建。几何、网格、静电模型树、CPT树、
  NIST电子常数绑定、`Freeze`壁面条件和GUI参数绑定均通过；静电与粒子求解器均未运行。success manifest、
  6项输出和三个非空MPH已复核，商业wrapper明确记录attempted/completed，因此模型构建和MATLAB API
  绑定证据有效。但冻结Static gate在`inputs/`内生成了15个未列入manifest的Python/Ruff缓存文件；声明的
  51项输入哈希均正确，目录全量封存语义却未闭合。现行runner已禁用这些缓存，并在商业调用前和success
  前强制实际输入集合等于声明集合；仍需一次新商业run关闭该provenance缺口。该run不具备Candidate或
  Formal资格，既有目录不得追写或清理。
- `functional_reference`定义现行网格与时间设置及N>=100执行下限，但尚未注册为执行profile，也未
  运行真实求解器；其机器资格明确为非Candidate、非Formal，不能把历史34.18%数值恢复为当前结论。
- 旧MPH早于现行run config/summary/manifest合同；资产身份与结果尚未形成完整哈希链，不能称为当前
  Formal资产。
- 横置Wehnelt参数扫描尚未建立；旧phase5实际属于轴向灯丝，只能支持非单调性的历史假设。

## 下一步

1. 为`functional_reference`建立受治理的N=100运行器，先冻结可复现母样本、逐粒子身份、终态和完备
   损失分类；只有建立真实收集面/穿越事件后才定义收集效率，再决定是否允许进入Candidate评审。
2. 补齐run config、summary、manifest、资产SHA和正式结果图；最终CPT模型还必须重开并完成GUI
   Compute对等复算。
3. 只有下游设计需要时才建立横置谱系参数扫描或与EI源的接口合同；不得复用轴向phase5的具体最优值。

## 产物边界

项目产物根为`artifacts/projects/wehnelt_electron_gun/`。archive中旧目录名出现`formal`只表示归档前
曾承担的资产职责，不等于现行门禁已通过；旧谱系保留在archive，临时验证进入runs或scratch，不写入Git。
