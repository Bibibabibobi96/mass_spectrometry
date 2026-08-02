# 2026-08-02 活动run与campaign证据审计

## 范围与判据

本次审计只读取`artifacts/projects/`的8个活动项目根，覆盖全部活动`runs/`和仓库内4张多极杆/oaTOF
campaign声明；archive只由既有迁移manifest与布局门禁复核，不重新解释历史物理结论。判据是：run目录
身份与项目注册一致，三件套存在且可解析，manifest记录的文件、字节数和SHA-256仍可复核，campaign
每行状态由绑定的终态manifest决定。没有启动COMSOL、SIMION、MATLAB或CAD。

## 总体结果

- artifact布局门禁通过：8个项目、256个活动run、14个archive；256个活动run均有可解析三件套。
- 活动终态为192个`success`、34个`failed`、30个`interrupted`；失败和中断保留为证据，不计作布局
  损坏，也不能外推为物理或求解器FAIL。
- 245个活动run的全部记录仍逐字节可复核。其余11个不可变旧run共有21条记录指向后来变化或退役的
  活动仓库/工作区文件；没有回写旧manifest或用当前字节冒充原输入。
- 三张多极杆SIMION campaign逐行复核为`9/9`、`5/5`、`3/3 success`。oaTOF中栅campaign当前两行
  均为`SUCCESS`；两个较早campaign调度run保持`failed`，最终调度run为`success`。

## 11个历史记录异常的处置边界

|类别|run|记录异常|结论边界|
|---|---|---|---|
|已退役迁移输入|`20260729_195243__analysis__cross__rf-oatof-migration-equivalence`、`20260730_113401__analysis__cross__rf-oatof-migration-equivalence`|4条旧oracle/prereg路径已退役|只从Git、history与迁移审计追溯，不再作为活动输入|
|发布器记录了可变活动源码|`20260730_144154__analysis__cross__paired-family__n100`、`20260730_144531__analysis__cross__paired-family__n100`、`20260730_234500__analysis__cross__hybrid-source-revision__n100`、`20260731_030000__analysis__cross__source-triangle__n100`|10条实现、prereg或lock记录的当前字节不同于发布时字节|结果仅保留历史诊断语义，不得作为新的资格或派生run输入；未来发布须冻结仓库依赖|
|中断run的终态前后不一致|`20260730_135651__sim__cross__rf-oatof-analyzer-transport-gap0__n100`、`20260731_010001__sim__simion__quad-noacc-followup-a-r030-z030-t080`、`20260731_040001__sim__simion__quad-n1000-sampling-i-r020-z020-t080`|3条summary/run_config在中断manifest后被改写|只证明对应尝试被中断；后续具名重试或campaign决定承担当前结论|
|退役工作区或缺失失败输入|`20260727_102100__build__simion__candidate-layout-template-workspace`、`20260729_104000__test__cross__formal-vnext-zero-change-candidate-retry-n100`|4条旧工作区源码或失败阶段provenance已不存在|仅作失败链/历史来源，不构成当前Formal依赖|

上述run的summary与物理输出没有被本次审计修改。当前文档若引用其中数值，只能维持其原有
`FUNCTIONAL_SCREEN_ONLY`、`POSTHOC_DESCRIPTIVE`或`INCONCLUSIVE_DIAGNOSTIC_ONLY`边界；审计不把
来源缺口升级成资格，也不反向否定仍由独立父run或后续重试支持的功能事实。

## campaign与生命周期处置

1. 多极杆状态入口原先同时把命令行路径按仓库根和campaign目录解析，导致README式仓库相对路径被
   重复拼接。入口现先规范化为`common/multipole/campaigns/`内的唯一绝对路径，并增加仓库相对路径
   回归测试。
2. oaTOF三个既有campaign调度run使用run相对schema v1记录。公共verifier现从manifest所在目录解析
   这种历史记录，因此最终成功run及两个失败run均可按原字节复核；这不是重写历史manifest。
3. 后续oaTOF campaign调度不再自行构造manifest，统一调用公共writer，冻结schema v2
   `compact`保留合同，并以`interrupted → success/failed`发布终态。子Candidate仍各自保留独立三件套；
   campaign summary只作索引，不替代子run证据。

## 发布器闭合

integration的paired与source-revision分析发布器原先把活动仓库源码、lock与预登记文件直接列为
manifest输入，正是4个历史分析run随Git演进失去逐字节复核能力的原因。两个发布器现共用唯一冻结机制：
在分析开始前把所有仓库内依赖按原相对路径复制到本次`inputs/repository_snapshot/`，核对源/副本字节数
与SHA-256，再让run config和manifest只记录副本；父run manifest等仓库外不可变输入保持原路径。
因此后续发布不再依赖活动工作树字节，既有终态run仍不改写，也不需要重跑商业求解器。
