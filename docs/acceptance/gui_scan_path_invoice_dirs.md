# GUI 调整验收：可编辑扫描路径 + 发票目录直达

- 日期：2026-10-25；分支 `fix/s2-execute-gate`（基于含 S2+S3.1a 的 main@8123e3c）

## 变更

- **桌面整理**：扫描路径改为可编辑（`EditablePathRow`：文本框 + 浏览…），点「扫描桌面」即按所填路径扫描并持久化到 `general.desktop_path`；留空/非法路径走原有不存在警告。分类/预览/执行/撤销逻辑未动。
- **发票管理**：`InvoiceConfig.root_dir` 不变（`~/Desktop/发票管理`，与真实目录一致，未迁移）；新增目录直达按钮：打开待处理/待审核/归档目录（加上原有根目录/月份/报表/日志）；新增**目录统计行**：待处理 | 待审核 | 已归档 | 报表 | 邮件原始附件 各目录文件数（不含 .source.json sidecar），扫描/同步完成后自动刷新。

## 本机实测（macOS GUI 真实会话）

- 目录统计行显示：待处理 48 | 待审核 20 | 已归档 0 | 报表 0 | 邮件原始附件 48
- 全部直达按钮可打开 Finder 对应目录。

## 测试

- 新增：`test_desktop_scan_uses_editable_path_and_persists`（输入子目录→扫描生效且写入配置）、`test_invoice_dir_stats_and_folder_buttons`（计数文案 + 三个按钮的目标路径）。
- 顺手修复既有 flaky：`test_undo_desktop_runs_in_background` 此前在泵提前退出后让延迟 apply() 弹出真实 QMessageBox 阻塞后续测试事件循环——等待条件改为完整链路结束。
- 全套 **212 passed, 1 skipped**。

## 未做

- 未执行真实归档、未动 mail_sync.db、未迁移任何已有文件。
