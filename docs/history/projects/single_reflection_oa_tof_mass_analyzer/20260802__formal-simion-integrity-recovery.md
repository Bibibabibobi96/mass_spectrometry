# Formal SIMION完整性恢复（2026-08-02）

DOC_STATUS: ARCHIVED_READ_ONLY

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 发现与影响

对当前Formal release
`20260729_112246__sim__cross__vnext-n1000-r2`执行逐文件SHA-256审计时，发现两个SIMION解数组偏离
`formal/asset_manifest.json`：`accelerator.pa2`实际SHA为
`8B11CB24DAB4C5E8B0C136C7079D30F5E70A072AE65FBA0C0D5252DB48055092`，期望SHA为
`6B93D04BF939A89D98EA94627CB4A827829688D132A15C1D6AC4951DF272B2DE`；`accelerator.pa7`实际SHA为
`84BF4AA82E44B272817BD6C0650A5DC3A67196BCE9FB160A9DB75A446D274CC5`，期望SHA为
`257BC11FB62961BD6A3EB7DFDF4F3105C095A8E2C944223018177997B26CD1FF`。两者字节数均未改变。

来源validation run中的对应输入仍受原run manifest冻结且与Formal manifest期望SHA一致，因此该事件
属于已发布资产的字节漂移，不是新物理设计、数值重算或新release。旧Formal Verify只检查结构及部分
代表资产，没有对全部Formal资产启用哈希，因而未能提前报告两个PA漂移。

## 恢复

现有Formal唯一入口增加`Recover` phase。恢复器重新验证原promotion request、candidate/validation/
evidence三个来源run及当前四份Git内Formal合同，只允许从manifest冻结且SHA与当前release期望值一致的
来源恢复。两个异常文件原字节保存在artifact archive
`20260802_174431__failed-evidence__simion__formal-asset-drift`，随后以同盘临时文件原子替换；未刷新
`asset_manifest.json`、`formal_validation.json`、`formal_assets.json`或`simion_stable_entry.json`。

恢复后对本项目整个Formal执行逐文件哈希，56项SIMION包身份、四实例IOB、trajectory quality、场采样、
几何派生、COMSOL/CAD代表资产、Formal结果清单和reference analysis全部通过。两个PA恢复为原manifest
SHA，因此既有N=1000与GUI/CAD evidence仍绑定相同字节，不需要重跑求解或建立新release。

## 防复发

活动SIMION消费者不再把求解器的IOB或工作目录指向`formal/simion`。公共项目入口先验证Formal SIMION
全部资产，再复制到项目`scratch/<task_id>`中的临时runtime；run保存小型来源receipt，SIMION只读取临时
副本，结束或失败时删除runtime。质量谱Candidate、ideal-field diagnostic、Formal geometry/runtime
验证、稳定入口复核、跨求解器diagnostic及加速器网格相位测试均采用该边界。Formal `Verify`固定使用
项目定向的`--verify-hashes`，不把2 GiB级全哈希加入L1。
