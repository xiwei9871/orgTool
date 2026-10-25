# orgTool 2.0 — 自动归档与月度报销台账架构（S3.3）

## 最终工作流

```
网易邮箱定时同步 → PDF 落盘+去重 → 分类+字段识别
  → 准入评估(evaluate_eligibility)
     ├─ 全部硬条件满足 → 自动按月归档 → 元数据登记
     └─ 任一不满足    → 待审核队列 → 人工对照原件修正 → 确认归档
  → 月度台账导出(双 Sheet, 纯函数重生成)
```

## 自动归档准入（硬条件，非置信度）

`invoice/eligibility.py::evaluate_eligibility(record, duplicate_status, file_hash_ok)`
逐条检查，任一失败即进入人工审核，`reasons` 为机器码：

| 条件 | 失败原因码 |
|---|---|
| `doc_type == e_invoice` | not_e_invoice |
| 识别状态 complete | not_complete |
| 号码存在 + 强证据(label/dzfp_block/filename_verified) + 8-20位字母数字 | missing_number / weak_number / bad_number_format |
| 日期存在 + 强证据 + 合法 2000–2100 年 | missing_date / weak_date / bad_date_format |
| 金额存在 + 0–10000 + 强证据(label/daxie/verified) | missing_amount / bad_amount / weak_amount |
| 税额存在且金额经净+税=总额验证 | tax_missing |
| 购买方/销售方非空 | buyer_missing / seller_missing |
| 去重状态=新发票 | duplicate_conflict |
| file_hash 存在 + 现读 SHA-256 一致 | file_hash_missing / file_unreadable |
| `review_fields` 为空 | review_flags |

原则：`recognition_status == "complete"` 只是必要条件之一；兜底证据(field_sources=fallback)填充的值允许展示但永不放行自动归档。

执行侧三层校验：
1. 预览层 Document Gate（doc_type 非 e_invoice → 跳过，target_path 为空）
2. `execute_preview` 执行时复核 doc_type（防伪造预览行）
3. `archive_confirmed` / `auto_archive` 后端再次校验 SHA-256、doc_type、强重复——前端确认动作无法绕过

## 人工审核

- `evaluate_pending(config)` 只读 dry-run，返回 `ArchiveCandidate`（record + 去重状态 + verdict + 原因码），不移动文件。
- GUI `ReviewDialog`：左 `QPdfView` 原件预览，右字段表单（号码/日期/金额/税额/购销方/内容/费用类别/报销人/费用发生地）+ 字段证据 + 拦阻原因。
- `save_manual_review` 把修改写入 `manual_overrides`；后续重新扫描经 `_apply_manual_overrides` 以 file_hash 匹配恢复人工值，**重扫不覆盖已确认字段**。
- `set_review_state("pending_review")` = 暂缓；`archive_confirmed` = 确认归档（含后端复核）。

## 数据与迁移

`InvoiceRecord` 新增字段均有默认值：`archive_status / review_status / expense_category / reimburser / expense_location / reimburse_state / manual_overrides / archived_at`。
旧 `invoice_index.json` 条目缺这些键 → dataclass 默认值补齐 —— 这就是幂等迁移路径，不建第二套主数据。

## 月度台账（发票档案 vs 报销流水）

`invoice/ledger_exporter.py::MonthlyLedgerExporter.export(path, records, reimburser_default)`

- **Sheet1 报销流水**：序号/日期/姓名/金额/类别/凭证类型/费用发生地/备注/**报销状态**。
  - 日期=开票日期（`YYYY.MM.DD`）；姓名=记录报销人→配置默认→`待指定`；类别=配置字典建议，不确定=`待确认`；发生地无证据留空；**备注恒空**；报销状态(未确定/报销/不报销)显式区分"已归档发票"与"已报销费用"。
  - 末尾合计行；冻结表头；自动筛选；金额为数值类型 `0.00`。
- **Sheet2 发票明细**：号码/日期/价税合计/税额/购销方/内容/文件名/PDF路径/归档状态/审核状态/重复状态/来源。
- 导出是已归档记录的纯函数 → 重复生成不重复累计；临时文件 + `os.replace` 原子替换。

## GUI

- 发票页：路径行 → 单行邮箱状态(同步/管理邮箱…) → 归档统计(已归档|待审核|重复|其他附件) → 目录统计 → 按钮行 → 目录直达 → 月份+导出 → 表格（1280×800 约 15 行可见）。
- 完整账户管理在 `MailManagerDialog`（原 `MailSyncPanel` 迁入，`invoice_page.mail_panel` 仍指向它，兼容旧引用）。
- 同步完成后自动 `scan_invoices` + `evaluate_invoices`（只读评估，不移动文件）。
- 入口：评估自动归档 / 执行归档 / 审核选中项(双击同) / 查看PDF / 导入PDF / 导出月度台账。

## 默认约束

- 第一版 dry-run：真实批量归档需用户在界面上显式执行；评估本身永不移动文件。
- 归档 = 电子文件+元数据登记完成，**不代表报销或财务入账**。
- 真实发票文件、邮件正文、完整台账数据不入库；仓库内示例均使用虚构主体。
