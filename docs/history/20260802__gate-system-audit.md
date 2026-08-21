# 2026-08-02 门禁系统审计与统一

DOC_STATUS: ARCHIVED_READ_ONLY

## 结论

L1 changed-scope、手动L2 repository integration和项目L3 evidence验证的是不同边界，现有公共、项目和
integration测试没有可直接删除的整套重复。L2较重但只用于门禁、共享机制和跨项目接口变化，不应进入
普通push。主要问题在编排：L1文本字节阶段已声明却未执行、四极杆Freshness同轮重复、L2项目路径手工
维护、并行运行期间无进度，以及远端标准库范围仍安装完整科学Python环境。

## 基线证据

- 本机：Intel i7-8700，6核12线程，约48 GB内存。
- 改造前同一工作树L2：4路209.5秒，8路183.1秒。
- GitHub run `30727043799`：changed-scope job约73秒，其中checkout 8秒、Python setup 5秒、完整依赖
  安装45秒、实际门禁7秒；该提交包含项目注册表变化，因此仍须使用`locked`环境。该数据用于量化安装
  固定成本，不把该run误称为可跳过安装的标准库范围。
- L2主要阶段：common contracts约36–53秒、multipole common约69–80秒、multipole→oaTOF integration
  约120–132秒、oaTOF Static约150–160秒、四极杆Static约154–168秒。它们测试的所有权边界不同。

## 实施决定

- `common/gate_catalog.json`统一L1路径匹配、命令、依赖等级、前置关系和L2归属；L1/L2共用加载与命令
  执行机制，项目和integration门禁集合必须与文件系统发现完全一致。
- L1始终在文档快速返回前执行受管文本字节检查，消除本地遗漏LF/CRLF错误的路径。
- 四极杆Freshness仍在长测试前失败关闭；随后Core/Static显式消费该已通过前置，不再重复六项检查。
  直接调用项目门禁仍执行完整Freshness。
- 本地并发自动上限为8，显式参数仍优先；GitHub双核runner固定2。并行子进程启动/完成即时报告，完整
  日志仍稳定回放。
- GitHub先用真实L1选择逻辑输出`stdlib|locked`计划；仅当所有选中阶段均为`stdlib`时跳过完整依赖
  安装，未知范围失败关闭为`locked`。
- 删除旧`verify_lightweight.ps1`入口，活动冻结输入迁至唯一`verify_changed.ps1`，不保留兼容层。
- 增加Python声明/锁文件一致性合同；直接和可选依赖必须具有唯一且兼容的精确锁定版本。

## 验证与性能

- 门禁聚焦合同：32项通过。
- 新建未安装任何第三方包的Python 3.11 venv后，纯文档L1和门禁基础设施L1均通过，证明`stdlib`
  分类不依赖开发机既有环境；项目注册表因依赖JSON Schema明确归入`locked`。
- Wehnelt Static：47项通过。
- 完整L2：common contracts 177项、multipole 293项、integration 104项、oaTOF 166项、四极杆216项、
  六极杆76项、八极杆28项、Wehnelt 47项、电子轰击源22项及其他公共检查全部通过。
- 最终8路L2墙钟时间185.2秒。相对旧默认4路缩短24.3秒（11.6%）；相对旧8路的约2.1秒差异属于新增
  合同、进度观测和运行波动，没有通过删减验证边界换取速度。
- 纯文档或其他完整`stdlib`范围的远端push不再执行实测约45秒的完整依赖安装；预计可直接消除该固定
  成本。具体总时间需由下一次对应范围的GitHub运行实测，不以含注册表变化的历史run冒充结果。

因此，后续优化应针对oaTOF/四极杆项目测试内部的安全分片或测试实现本身，而不是继续增加L2进程数或
删除跨边界回归。任何内部并行必须先证明测试不共享可变仓库文件、随机临时路径和供应商状态。
