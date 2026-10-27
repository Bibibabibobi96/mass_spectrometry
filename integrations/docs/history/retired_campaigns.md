# 退役 campaign 索引

DOC_STATUS: ARCHIVED_READ_ONLY

本目录保存已退役、替换或仅供审计的 campaign 原始记录及其 SHA-256 清单。它们不能由活动执行入口发现或
运行；当前可执行范围由生命周期注册表和项目合同明确限定。

## 内容与校验入口

- [诊断 campaign 归档索引](retired_campaigns/diagnostics_archive_index.json)：每个 diagnostics campaign 的归档路径、原始 SHA-256 与原因。
- [inactive authorized campaign 索引](retired_campaigns/inactive_authorized_campaign_archive_index.json)：已退出活动生命周期注册表的授权 campaign。
- [诊断合同 SHA-256 清单](retired_campaigns/SHA256SUMS.txt)。
- [根目录旧 campaign 索引](retired_campaigns/root_campaigns/INDEX.md)：该表逐项记录原路径、SHA-256 与归档路径。

这些文件是历史文档恢复的原始合同来源，不是当前 authoring 输入。对于本次恢复的 gap、field 和 residual
记录，优先按上述索引取得原始 JSON，再以 artifacts 的 `run_config.json`、`summary.json` 与
`run_manifest.json` 复核运行事实。
