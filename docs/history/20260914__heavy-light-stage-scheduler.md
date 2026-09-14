# 2026-09-14 轻重任务阶段调度验收

DOC_STATUS: ARCHIVED_READ_ONLY

本记录冻结本次阶段分类、真实执行和回归验收。当前规则见[操作指南](../OPERATIONS.md#主机资源调度)，
分类机器权威为[资源策略](../../common/host_resource_policy.json)。此前提炼及旧调度验收见
[前一里程碑](20260914__common-reuse-and-host-stage-scheduler.md)，不改写其历史结论。

## 目标与范围

按用户最终决定，未知阶段默认轻任务；PA 构建只在实际 refine 阶段占用重任务名额。
统一入口连接同一主机账本，重任务互斥，轻任务在预算与实时压力允许时可与轻、重任务并行。
准备、GEM 转 PA、缓存物化、纯 IOB 组装与后处理按轻任务执行；已知内部调用 refine 的 Lua
整体在重阶段执行。实际飞行、COMSOL solver 和集中理论计算保留重任务分类。

这是已有统一调度器的阶段接入与验收闭合，不是新建第二个调度服务。Python 工作流通过公共桥接
继承同一许可；原有内部规划器继续管理 worker，45 秒观测、5 秒启动间隔和已有续算语义保留。
并非所有单进程飞行或固定池工作流都被改成动态规划器，也不为改变调度而修改物理或随机行为。

Agent 0 负责隔离预览、联合验证和唯一 Git 写入；Agent 2 负责公共桥接与测试隔离，Agent 3 负责 MR
最小阶段迁移和独立范围复核，Agent 4 负责 RF/OA 入口与回归，Agent 5 负责核心和 integration。
COMSOL/双锥负责人授权将其已闭合的 13 文件与调度入口原子纳入。
MR/OA 未闭合科学改造保留原工作树；integration 派生绑定由隔离预览编译，仅改变 3 个实际依赖 SHA。

## 验收结果

| 层级 | 对象与判据 | 结果 |
|---|---|---|
| L1 | 提交预览及修复后受影响范围 | 公共合同 268 tests（1 skip）、integration 806 tests（9 skip）及各适用阶段通过；最后两文件范围复验通过 |
| L2 | 全仓静态集成，不运行商业求解 | 首轮两个阶段失败；公共合同复验同目录命令 268 tests 通过，RF Static 重验 228 tests 通过，其他阶段首轮通过 |
| 派生身份 | canonical compiler 完整检查 | FAMILY_REPOSITORY_BINDINGS=PASS |
| 真实 QUAD | 既有 A 数值 profile，主工况与零 RF 对照各 N=100 | 两组 ID 1–100 完整；主工况实际并发峰值 2、对照 1；manifest 64 输出通过 |
| 真实双锥 COMSOL | 同一冻结气流输入与完整输出身份 | 295236 行、236104 流体行；质量误差 0.8434%；manifest 9 输出通过 |
| 真实双锥 SIMION | 同源气流场 N=100，终态与分析 | 100 splats，233.41 秒，传输 58/100；manifest 11 输出通过 |

L2 结论是首轮加受影响阶段复验的闭合，不是一次全绿调用。测试修复隔离临时目录中的进程观测，
保留真实 writer 拒绝反例；未删除生产写入保护，未因测试暂停 MR。其他修复包括只读缓存篡改夹具、
UTF-8 非法字节诊断、干净 checkout 不存在空目录，以及精确区分调度 Role 与科学角色参数。

QUAD 实测顺序为 prepare → pa_refine → prepare → flight → postprocess → release。
主工况与对照的 worker 波段分别为 49.943 秒、70.207 秒，受管峰值分别为 1209380864、604958720 字节。
首个正式观测样本 6.819 秒内自然结束，未为凑足 45 秒改变工况；观测窗口与调度规则保留。
实际发生 CPU 压力暂停后继续；未触发内存终止、重新排队或中断恢复，不能宣称这些真实分支已验证。

代表性机器证据：

- [QUAD 运行 manifest](../../../artifacts/projects/rf_quadrupole_ion_optics/runs/20260914_161823__sim__simion__quad-dispatch-acceptance-a-n100/run_manifest.json)
- [双锥气流 manifest](../../../artifacts/projects/dual_cone_tandem_quadrupole_ion_interface/runs/20260914_154800__sim__comsol__dual-cone-gas-flow/run_manifest.json)
- [双锥粒子 manifest](../../../artifacts/projects/dual_cone_tandem_quadrupole_ion_interface/runs/20260914_162400__sim__simion__dual-cone-comsol-field-n100/run_manifest.json)

双锥气流仍是空腔轴对称定性 prototype，不构成收敛、GUI/CAD 或 Formal 资格。
QUAD 传输率 1.0、零 RF 对照 0.22 只用于本次功能验收；没有进行前后吞吐对照或数值优化。
先前失败 run 继续保留，成功记录不覆盖失败证据。

## 效果、代价与未覆盖边界

准备阶段不再整段持有重任务许可，轻任务也不因存在重任务等待者就统一拒绝。
预算与重任务分类集中维护，项目只声明阶段；没有增加旧 mutex 兼容或第二数据库。
本次属于接入升级，代码与脚本数增加，不能计为公共提炼减量；此前提炼 production 净减 54 行是另一提交范围。

默认轻任务的额度是声明值，不是实测峰值或操作系统硬限制。未知任务突发高负载仍可能抢占资源；
实际反复高负载的入口需进入中央重任务名单。阶段边界与父子进程生命周期也增加维护和回归成本。

资源准入不等于缓存数据锁。公共缓存发布、物化与容量删除尚未全部使用同一按 key 生命周期保护，
legacy integration 也有独立发布锁；启动期活动引用登记与删除之间存在未闭合边界。
本次不把破坏性容量 apply 与缓存消费列为已验证安全并行，不扩展为缓存锁重构。

## CLOC 范围与结果

baseline `76fbb9f4fb3d76bf961fdb0696020daa59ea7485` → `WORKTREE`（隔离的待提交预览，
不含其他 Agent 科学改动）。本记录随该预览同主题提交；提交结果 SHA 可由本文件的新增提交定位。
CLOC 2.10，由仓库统一 `common/report_cloc_delta.ps1` 生成；下表每格为 baseline → result（delta）。
Markdown 不计入，history 载荷排除。total code +2244，production +888，tests +1356；
文件 +5，其中正式桥接脚本 +2、测试脚本 +2、campaign JSON +1；unclassified 为 0。

### total

| language | files | blank | comment | code |
|---|---|---|---|---|
| JSON | 481 → 482 (+1) | 0 → 0 (+0) | 0 → 0 (+0) | 47787 → 47906 (+119) |
| Lua | 89 → 89 (+0) | 416 → 416 (+0) | 576 → 576 (+0) | 8130 → 8130 (+0) |
| MATLAB | 110 → 110 (+0) | 964 → 966 (+2) | 2179 → 2181 (+2) | 12891 → 12910 (+19) |
| PowerShell | 134 → 135 (+1) | 976 → 987 (+11) | 935 → 963 (+28) | 34528 → 35148 (+620) |
| Python | 681 → 684 (+3) | 16097 → 16228 (+131) | 6930 → 7450 (+520) | 184439 → 185925 (+1486) |
| SIMION GEM | 11 → 11 (+0) | 35 → 35 (+0) | 83 → 83 (+0) | 256 → 256 (+0) |
| TOML | 1 → 1 (+0) | 4 → 4 (+0) | 0 → 0 (+0) | 24 → 24 (+0) |
| YAML | 2 → 2 (+0) | 4 → 4 (+0) | 1 → 1 (+0) | 114 → 114 (+0) |
| SUM | 1509 → 1514 (+5) | 18496 → 18640 (+144) | 10704 → 11254 (+550) | 288169 → 290413 (+2244) |

### production

| language | files | blank | comment | code |
|---|---|---|---|---|
| JSON | 477 → 478 (+1) | 0 → 0 (+0) | 0 → 0 (+0) | 47677 → 47796 (+119) |
| Lua | 76 → 76 (+0) | 320 → 320 (+0) | 514 → 514 (+0) | 6668 → 6668 (+0) |
| MATLAB | 72 → 72 (+0) | 526 → 528 (+2) | 1661 → 1663 (+2) | 9393 → 9412 (+19) |
| PowerShell | 126 → 127 (+1) | 925 → 935 (+10) | 927 → 953 (+26) | 33555 → 34119 (+564) |
| Python | 370 → 371 (+1) | 10104 → 10134 (+30) | 5267 → 5298 (+31) | 109688 → 109874 (+186) |
| SIMION GEM | 11 → 11 (+0) | 35 → 35 (+0) | 83 → 83 (+0) | 256 → 256 (+0) |
| TOML | 1 → 1 (+0) | 4 → 4 (+0) | 0 → 0 (+0) | 24 → 24 (+0) |
| YAML | 2 → 2 (+0) | 4 → 4 (+0) | 1 → 1 (+0) | 114 → 114 (+0) |
| SUM | 1135 → 1138 (+3) | 11918 → 11960 (+42) | 8453 → 8512 (+59) | 207375 → 208263 (+888) |

### tests

| language | files | blank | comment | code |
|---|---|---|---|---|
| JSON | 4 → 4 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 110 → 110 (+0) |
| Lua | 13 → 13 (+0) | 96 → 96 (+0) | 62 → 62 (+0) | 1462 → 1462 (+0) |
| MATLAB | 38 → 38 (+0) | 438 → 438 (+0) | 518 → 518 (+0) | 3498 → 3498 (+0) |
| PowerShell | 8 → 8 (+0) | 51 → 52 (+1) | 8 → 10 (+2) | 973 → 1029 (+56) |
| Python | 311 → 313 (+2) | 5993 → 6094 (+101) | 1663 → 2152 (+489) | 74751 → 76051 (+1300) |
| SUM | 374 → 376 (+2) | 6578 → 6680 (+102) | 2251 → 2742 (+491) | 80794 → 82150 (+1356) |

### 完整过滤口径

```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;
excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;
excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;
language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;
production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);
tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|*Test.m|*.Tests.*;
unclassified=other_code_below_test_or_tests_path;
worktree_source=git_tracked_plus_nonignored_untracked
```
