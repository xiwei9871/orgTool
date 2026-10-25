# S2+S3.1a 合并后集成验收（脱敏版）

- 日期：2026-10-25；基线：`origin/main` = `8123e3c`（PR #6 + PR #7 已合并）
- 性质：合并后回归验证；只读真实文件检查，未移动/归档任何真实发票。

## 一、分支与代码状态

- main `8123e3c` 含：S2 未读审计（`a447152`）、预览层 Document Gate（`c00b9fc`）、S3.1+S3.1a 字段识别（`efe399f`+`462a8eb`）。
- **缺口发现并补齐**：`326695a`（execute_preview 执行层 doc_type 复核）当时未被合入——已 cherry-pick 至 `fix/s2-execute-gate`（新 commit `b1a62ea` 待合并）。当前 main 上执行层只检查 `is_skipped`；合并该 PR 后双层闸门齐备。

## 二、自动化测试

- 本机 main：`209 passed, 1 skipped`（win32 专用跳过）
- 本分支（+执行层闸门）：`210 passed, 1 skipped`

## 三、48 份真实 PDF 只读复验（合并后代码）

| 检查项 | 结果 |
|---|---|
| 待处理目录扫描 | 48 |
| e_invoice 放行 | **28**（全部 `is_skipped=False`） |
| 非发票拦截 | **20**（travel_voucher 8、hotel_folio 9、needs_ocr 1、unknown 2） |
| 被拦项 target_path | 全部为空 |
| 放行项 review_fields | 全部为空（附加字段均有证据） |

## 四、28 张发票字段级准确率（对票面原文核实）

| 字段 | 正确率 | 主要证据源 |
|---|---|---|
| 发票号码 | 28/28 | dzfp_block / filename_verified / label |
| 开票日期 | 28/28 | dzfp_block / label / label_window |
| 价税合计 | 28/28 | **verified 28/28**（净+税=总额交叉验证全命中） |
| 购买方 | 28/28 | order_pair |
| 销售方 | 28/28 | order_pair |
| 税额 | 28/28 | 合计/相邻对 |
| 发票内容 | 28/28 | `*类别*项目`（3 张出行票项名尾字截断） |

`complete` 与 `review_fields` 关系：complete 仅由核心三字段强证据驱动；本批 28 张附加字段齐全故 review_fields 全空。合成回归已覆盖"字段缺失→complete 仍可但 review_fields 标记"及"标签误作公司名→双字段留空+标记"。

## 五、GUI 预览列 / Excel 导出兼容性

- 预览表 11 列：新增「购买方」「税额」列于状态与备注之间（合成项验证 `record=None` 时安全降级为空串）。
- 台账 Excel 14 列：「税额」「购买方」追加至尾部（列 13/14），原 12 列顺序不变——旧报表消费方不受影响。
- 未执行真实归档，未生成正式台账。

## 六、CI / 平台状态

| 项目 | 状态 |
|---|---|
| pytest (macos-latest) | ✅ success @8123e3c |
| pytest (windows-latest) | ❌ **failure @Run tests**（`e70ae67` 同样失败 → 合并前已存在，非本次引入；日志需仓库权限拉取） |
| build (macOS .app) | ✅ success @462a8eb；8123e3c 运行中 |
| macOS 本机 GUI | 启动正常（本轮验收后保持运行） |
| Windows 实机 | 未验证 |

## 七、未执行项

- 28 张真实发票未归档、未生成 Excel 台账、文件零移动。
- Windows CI 失败根因待查（需要 gh auth 或仓库日志权限）。
