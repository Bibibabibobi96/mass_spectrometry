# 质谱仿真仓库

本仓库用于质谱仪器及离子/电子光学部件的参数化多物理场建模与验证。项目通过统一机器契约联动
COMSOL、SIMION、MATLAB、Python和SolidWorks，目标是形成跨求解器独立闭合、GUI可检查、CAD同步
且能够可靠重建的正式模型。

仓库同时面向人类研究人员和编码Agent，当前包含oa-TOF、RF四极杆碰撞冷却与传输、电子轰击离子源
和Wehnelt电子枪等项目。各项目以物理问题为中心组织，COMSOL、SIMION、MATLAB、Python和SolidWorks
是平等的实现工具，不以任何软件作为目录主轴。

## 如何使用本仓库

本README是仓库的操作入口、知识路由器和最小执行规则。每次开始任务先读本文件，再进入目标项目；
不要从软件目录或历史日志猜测当前状态。

## 固定阅读顺序

1. 先读本文件，判断任务属于哪个项目、哪类知识和哪种生命周期。
2. 读目标项目的 `projects/<project>/README.md`，确认该项目的入口与知识写入规则。
3. 读该项目的 `docs/PROJECT.md`，确认当前参数、正式/候选边界、已闭合结论和开放任务。
4. 只按实际操作再读 `docs/COMSOL.md`、`docs/SIMION.md` 或 `docs/CAD.md` 中的一份。
5. 只有追溯旧结论时才读 `docs/history/`；历史记录不能覆盖 `PROJECT.md`。
6. 只有项目文档无法回答跨项目问题时，才读仓库根 `docs/` 中对应的通用文档。

当前 oa-TOF 已建立完整入口。其他项目在继续开发时按同一四文档结构逐步收敛，不为追求形式
一次性拆出大量空文档。

## 文档权威与知识路由

本仓库采用单一权威来源（Single Source of Truth, SSOT）。规范只在最高权威文档定义一次；下游
文档只链接该定义，并记录本项目的应用、例外或验证结果，不复制整段通用规则。

仓库使用者同时包括人类与AI。两者共享相同的项目入口、术语、机器契约和验收证据；不会为AI
另建一套内容不同的“简化真值”。`AGENTS.md`只额外规定Agent的执行行为，不取代面向所有使用者
的项目知识文档。

|文档|性质|唯一职责|
|---|---|---|
|仓库[`AGENTS.md`](AGENTS.md)|规范性|Agent执行、权限、删除、测试报告与Git约束；发生执行冲突时优先级最高|
|本README|规范性|仓库架构、阅读顺序、知识路由、参数与产物生命周期、跨项目标准|
|项目`README.md`|规范性入口|项目导航、权威入口、项目特有硬规则；不重述根规则|
|项目`docs/PROJECT.md`|项目权威状态|当前参数、正式/候选边界、跨软件结论、开放任务|
|项目软件文档|实施说明|单一软件的节点、接口、运行与独立验证；不定义跨软件结论|
|根`docs/`|通用参考|至少两个项目验证过的跨项目技术知识|
|项目`docs/history/`|只读证据|失效结论和演进过程；任何“当前”“正式”“下一步”均按归档时点解释|

冲突处理顺序是：执行行为看`AGENTS.md`，仓库结构和知识归属看本README，项目当前事实看
`docs/PROJECT.md`，实现细节看对应软件文档。历史记录和README中的状态速览都不能覆盖
`PROJECT.md`。项目确有例外时，只记录“例外内容、原因、适用范围和失效条件”，不得复制后修改
通用规则形成第二版本。

### 新知识写到哪里

|新信息|权威写入位置|不得写入|
|---|---|---|
|项目统一几何、粒子源、指标定义、正式状态、跨软件结论、下一步|`projects/<project>/docs/PROJECT.md`|单个软件文档或历史日志|
|某项目的 COMSOL 节点、网格、求解、GUI 操作和独立错误|项目 `docs/COMSOL.md`|根通用文档，除非已跨项目验证|
|某项目的 SIMION PA/GEM、Program、Fly2、网格、GUI 和独立错误|项目 `docs/SIMION.md`|COMSOL/CAD 文档|
|某项目的 STEP、SolidWorks 零件/装配、坐标和保存验证|项目 `docs/CAD.md`|SIMION/COMSOL 文档|
|失效但仍需追溯的长过程|项目 `docs/history/`|当前状态入口|
|机器必须共同读取的项目参数|项目 `config/`，优先 JSON|散落在文档中的多份数值|
|跨项目稳定的 COMSOL API|`docs/COMSOL_API.md`|单一项目参数|
|跨项目稳定的 COMSOL 排错策略|`docs/COMSOL_DEBUGGING.md`|只验证过一次的项目个例|
|跨求解器通用的网格、统计、FWHM 与几何闭合方法|`docs/VALIDATION_METHODS.md`|某次运行的具体结果|
|跨项目稳定的 SIMION GUI/PA/GEM/Program 经验|`docs/SIMION_REFERENCE.md`|oa-TOF 专属尺寸|
|COMSOL可复用测试与其已验证范围|`common/comsol/README.md`及测试源码|根API或项目正式结论|
|其他可复用代码事实|源码和最邻近的短 README/注释|长项目历史|

判断规则只有两步：先问“换一个项目是否仍成立”，再问“这是调用事实、排错方法，还是当前
项目结论”。没有通过第二个不同项目验证的经验先留在项目文档，不能提前提升为通用规则。

项目内采用星形引用：项目 README 是入口，指向 PROJECT/COMSOL/SIMION/CAD；三份软件文档
只返回 PROJECT，不互相横向引用。跨软件结论必须先统一输入并验证，再提升到 PROJECT。这样
人和 AI 都只需要记住一个入口，不维护文档网状图。

## 总体目录

```text
simulation_repo/
├─ README.md                 # 本文件：仓库操作规则与知识路由
├─ docs/                     # 跨项目知识，直接放置，不设 software/ 重复层
│  ├─ COMSOL_API.md
│  ├─ COMSOL_DEBUGGING.md
│  ├─ VALIDATION_METHODS.md
│  └─ SIMION_REFERENCE.md
├─ projects/                 # 平级项目；不再按软件或器件类别嵌套
│  ├─ oa_tof/
│  ├─ electron_impact_ion_source/
│  ├─ rf_quadrupole_collision_cooling/
│  └─ wehnelt_electron_gun/
├─ common/
│  ├─ comsol/                # LiveLink启动器、可复用COMSOL测试及就近README
│  ├─ paths/                 # 工作区与 artifacts 路径解析
│  └─ solidworks/            # STEP→SolidWorks 可复用桥接
├─ official_docs/            # 官方离线原始资料及索引
```

项目测试留在各项目内；只有出现真正跨项目的仓库级门禁时才创建根 `tests/`，不预建空目录。

源码目标目录深度不超过 5 级（文件可处于第 6 段）。新目录只有在承载明确职责时才创建；不建立
`components/`、`project/components/`、`docs/software/` 或只有一个子目录的重复分类层。

## 项目与软件平权

每个 `projects/<project>/` 是一个可独立理解、验证和交付的研究项目。项目可以同时包含
`comsol/`、`simion/`、`cad/`、`analysis/`、`config/` 和 `tests/`，但不要求空目录占位。
目录按知识对象和生命周期划分，不按“主软件/辅助软件”划分。选择结果以物理问题和统一契约
为准，不以某个求解器先完成为准。

当前项目：

- `projects/oa_tof`：正交加速双级反射 oa-TOF。
- `projects/electron_impact_ion_source`：电子轰击离子源。
- `projects/rf_quadrupole_collision_cooling`：多级杆碰撞冷却与传输。
- `projects/wehnelt_electron_gun`：螺旋灯丝 Wehnelt 电子枪。

## 参数权威与单向派生

所有项目必须遵循同一条不可逆的数据流：

`物理输入参数 + 公式 + 明确精度规则 → 项目config中的baseline工程参数 → COMSOL / SIMION / CAD`

- `baseline`不是任一软件当前文件的抄录，而是物理输入经公式计算后的唯一工程参数契约。
- 公式、输入量、单位和工程舍入位数必须机器可读并接受门禁；不得只把最终尺寸散写在代码或文档中。
- COMSOL、SIMION、CAD及SolidWorks只能读取、生成或验证baseline，不得因网格、格式化、GUI显示、
  旧模型或某个求解器的现有数值而反向改写baseline。
- 扫描参数也必须先形成候选契约，再联动生成各实现；禁止分别手改多个软件后凭肉眼判断一致。
- 序列化精度不得低于baseline精度。`%g`、Excel显示位数或GUI四舍五入不能充当工程参数定义。
- 若实现与baseline冲突，实现一律判为失效候选；在重新生成、跨软件门禁和正式CAD同步全部通过前，
  不得转正。AI和人均无权为了迁就某一现有文件而擅自改变派生结果。

### 跨项目几何参数化标准

- 人工只维护`baseline`物理设计；项目解析器单向生成`resolved`，各软件不得重复推导或反写。
- 数值模式与物理设计分层；一次运行使用显式`run_config`，用`common/contracts/write_run_manifest.py`
  生成含输入/输出哈希和产物状态的manifest，并用`verify_run_manifest.py`重新计算全部记录后才能引用。
- 开发入口读取统一契约；SIMION等正式交付包可由该契约生成自包含文件，并接受过期门禁。
- 正式入口不得以缺失配置时回退到旧物理硬数字；候选覆盖不得反写baseline。
- 每项目提供`Static/Candidate/Formal`三级总门禁；正式几何仍须完成COMSOL GUI与SolidWorks同步。

## 语言职责

- MATLAB R2025b只负责COMSOL模型树、求解、GUI结果节点、MPH和正式STEP导出。
- GEM/Lua/Fly2只负责SIMION几何、PA/IOB、粒子和运行时行为。
- Python 3.11负责求解器无关的数据规范、峰形/FWHM/统计、跨软件比较和正式分析图。
- PowerShell只负责Windows环境检查、进程调用和PASS/FAIL门禁，不实现物理公式。
- JSON/CSV是跨语言机器契约；Excel只允许人工导入和检查，不能作为唯一真值。

分析算法不得在MATLAB、Python、Lua和Excel中平行发展多份。某项目建立Python参考实现后，
软件内MATLAB图表只作为GUI展示和对等检查；正式跨软件指标以项目`config/`中的版本化分析契约
和Python参考实现为准。公共Python代码仍须经过第二个项目实际复用后才能上移`common/`。

## 产物边界

Git 只管理可复现、可审阅的轻量源码与文档。MPH、PA/PA#、IOB、SolidWorks 文件、运行日志、
粒子表和图像放在仓库同级 `artifacts/projects/<project>/`，不进入 Git。推荐结构：

```text
artifacts/projects/<project>/
├─ models/<software>/{formal,candidates,archive}
├─ cad/{formal,archive}
├─ runs/<purpose>/<date>/
├─ results/<software>/
└─ scratch/<software>/
```

`formal` 只放已通过项目门禁的正式资产，`candidates` 放待闭合模型，`archive` 只做必要追溯。
脚本必须通过项目路径解析器定位这里，禁止硬编码用户名或重建旧 `artifacts/components/`。
SIMION IOB 可能嵌入 PA 的绝对路径，移动工作区后必须重新打开/保存或重建 IOB，并验证四个 PA
实例；文件存在不等于迁移成功。SolidWorks 装配移动后必须检查外部引用。

## 脚本生命周期

|命名|生命周期|规则|
|---|---|---|
|`scan_*` / `tmp_*`|一次性探索|结论写入项目文档后删除脚本及其临时模型、图片和日志|
|`test_*`|长期验证|保留可重复判据；项目测试放项目 `tests/`，通用测试放 `common/`|
|`ms_*` / `phase*`|正式生产|长期维护；被新正式入口取代后才能删除|
|`verify_*`|门禁|必须给出明确 PASS/FAIL，不能只输出人工猜测所需数据|

新脚本创建前先确定生命周期。一次性脚本不能因“以后也许有用”进入长期目录；探索结论、失败
原因和适用范围应写入正确文档。具体删除权限与确认要求只由`AGENTS.md`定义，本README不维护
第二套清理授权。

## GUI 对等与几何联动

- COMSOL：影响物理或数值结果的几何、选择、材料、物理场、粒子释放、网格、Study、Solver、
  数据集和派生值必须持久化为 Model Builder 中可见、可编辑、可保存的节点。必须重新打开 MPH，
  验证 GUI Compute 使用预期设置；只验证脚本 `runAll` 不足。
- SIMION：正式 IOB 的 PA 实例、坐标、电压、粒子定义和 Program 必须能在 GUI 中检查。关键
  物理不能只藏在命令行参数或外部后处理里；数值检测面也必须有 GUI 可见实体。
- 几何联动：迁移器件、间隙、电极厚度、孔径、屏蔽件和检测面尽量由统一参数派生。跨求解器
  测试必须证明坐标、有效面、粒子表和统计定义一致。
- SolidWorks：正式机械几何一旦确认，必须在同一任务更新正式 COMSOL MPH 和 SolidWorks
  零件/装配体，并验证数量、版本、变换、保存错误/警告和参数一致性；未同步不得称为正式完成。

## 通用验证口径

质量分辨率统一为 `R=m/FWHM_m`；窄峰时间域等价式是 `R=T/(2*FWHM_t)`。`2.3548×sigma`
只有在峰形近似高斯时才可作为 FWHM 代理。比较 COMSOL 与 SIMION 时至少统一几何、粒子表、
有效检测面、命中定义、FWHM 算法和样本量，并分别检查网格收敛与统计不确定度。详细方法写入
`docs/VALIDATION_METHODS.md`，项目数值写入项目 PROJECT。

## COMSOL R2025b 执行入口

本机 MATLAB R2025b 与 COMSOL 6.4 的长期入口是：

```powershell
.\common\comsol\run_comsol_r2025b.ps1 -TaskScript <任务脚本.m> -ReportPath <报告.txt>
```

入口通过 `common/comsol/livelink_r2025b/comsolstartup.m` 连接官方 LiveLink/Java API。首次使用
新的直连脚本先做最小测试。临时连接工具不能替代正式项目脚本和项目专属后处理判据。
连接生命周期只由该入口管理：任务脚本不得再次调用`mphstart`。一次相关任务在同一连接内完成
加载、Compute、保存和轻量节点检查；容易触发大内存传输的粒子结果读取可放入第二个干净任务。
入口只对“尚未创建任务报告”的启动阶段崩溃自动重试一次，已进入业务脚本后失败则不自动重算。

## 工具链正式基线

自2026-07-15起，所有项目的新建、修改、验证和交付均只使用**MATLAB R2025b**与
**SolidWorks 2022**。MATLAB/COMSOL任务必须通过上述R2025b入口运行；凡涉及STEP导入、
零件、装配或CAD保存的任务必须使用`common/solidworks/`中的SolidWorks 2022桥接。不得启动、
调用或为兼容而降级到MATLAB R2022或SolidWorks 2013。历史文档中出现的旧版本仅用于解释当时
结果，不构成可用入口或复现环境。

每次涉及MATLAB或SolidWorks的正式变更前，运行：

```powershell
.\common\verify_toolchain.ps1
```

该门禁验证R2025b可执行文件和SolidWorks 2022 PIA/COM revision；项目默认继承本节，不在每个
README重复声明。它不重写或重存已有的MPH、SLDPRT或SLDASM。若Live COM探测失败，门禁可用
`FILE_VERSION_FALLBACK`确认安装版本与PIA基线，但这不证明CAD可编辑或可保存；任何实际CAD
变更仍必须通过项目SolidWorks导出与装配门禁。

自2026-07-16起，求解器无关分析固定使用**64位Python 3.11**。MATLAB R2025b官方支持
Python 3.9至3.12；本机默认Python 3.14和旧Python 3.8均不得作为本仓库正式运行时。依赖由根目录
`pyproject.toml`声明、`requirements-lock.txt`冻结，并安装在不入Git的`.venv/`。oa-TOF入口见
`projects/oa_tof/analysis/README.md`。

## Git 规则

仓库根是 `simulation_repo/`，远程私有仓库为
`https://github.com/Bibibabibobi96/mass_spectrometry.git`。提交只包含一个可审阅主题；使用明确
路径或 `git add -p`，不习惯性执行 `git add .`。提交前运行：

```powershell
git status --short --branch
git diff --check
git diff --stat
```

确认没有 MPH、PA/IOB、结果、日志或一次性脚本进入暂存区。Agent 在独立主题完成并验证后应
创建本地提交，并自动普通推送到当前分支对应的 `origin` 分支，不必逐次等待确认。不得强制推送、
改写远程历史或覆盖/夹带任务开始前的无关改动；推送失败时保留本地提交并报告原因。

按用户 2026-07-15 的明确决定，自动提交/推送流程不增加敏感信息专项扫描。现有文件类型排除、
暂存范围检查和测试门禁继续执行；用户明确要求暂停提交或推送时，以当次要求为准。

## 任务完成定义

一次变更只有在源码、机器契约、最近的权威文档、路径引用和相称测试一致后才算完成。报告测试
时按“目标与判据—对象与唯一变量—关键结果—结论与范围—产物与文档”交接；常规日志不逐条
粘贴。正式几何还必须满足 COMSOL GUI 和 SolidWorks 同步门禁。

文档变更还应运行`common/verify_documentation.ps1`，检查唯一H1、标题层级、相对链接、历史归档
标记和项目入口完整性。自动门禁只验证可机器判断的结构；技术结论是否放在正确权威层仍需审阅。
