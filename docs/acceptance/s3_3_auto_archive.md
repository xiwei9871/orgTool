# S3.3 自动归档验收

日期: 2026-10-25 · 分支 `feature/s3-3-auto-archive`（基于 main@8123e3c + 执行层闸门 bbadcff + GUI 1e434da 的 cherry-pick）

## 1. 准入评估 — 真实 48 份 dry-run（零文件移动）

`InvoiceService.evaluate_pending` 对 `~/Desktop/发票管理/发票归档_待处理` 48 份 PDF 实跑：

| 桶 | 数量 | 明细 |
|---|---|---|
| 可自动归档 eligible | **28** | 全部 doc_type=e_invoice，核心字段强证据，金额 verified，购销方齐全，无重复冲突，哈希复核通过 |
| 发票异常（e_invoice 但字段有问题） | **0** | 需人工修正后才可归档 |
| 其他票据 | **17** | hotel_folio 9 · travel_voucher 8 —— 可识别的非发票票据，不占人工审核队列 |
| 待识别 | **3** | unknown 2 · needs_ocr 1 —— 无法确定/需 OCR |

28+0+17+3=48 闭合。dry-run 前后目录文件列表逐项一致——评估为纯读操作。
「其他票据」「待识别」不再计入人工审核队列，审核页只呈现 e_invoice 异常项。

## 2. 硬条件语义验证（合成回归）

`tests/invoice/test_auto_archive.py` 15 例：

- 干净记录 → eligible
- `complete` 但字段全 fallback → 拦截（weak_number+weak_date+weak_amount+tax_missing）——**"complete 不等于准入"**
- doc_type=hotel_folio 且 complete → 拦截
- 强重复/疑似重复/待确认 → 拦截
- review_fields 非空 → 拦截
- 购销方缺失 → 拦截
- 非法号码格式 / 哈希不匹配 → 拦截
- dry-run / evaluate_pending 只读，不移动文件

## 3. 人工审核链

- `save_manual_review` 写 `manual_overrides` → 重新 `evaluate_pending` 后人工值保留（重扫不覆盖已确认字段）✅ 测试覆盖
- `archive_confirmed` 后端复核：重算 SHA-256 不符→拒绝；doc_type≠e_invoice→拒绝；强重复→拒绝。GUI 走后台 worker，不阻塞
- `archive_status` 区分 `auto_archived / manually_archived / deferred`；`review_status` 区分 `pending_review / confirmed`
- GUI ReviewDialog：左 QPdfView 原件 + 右字段编辑 + 证据/原因展示（offscreen 实测构建通过）

## 4. 幂等迁移

InvoiceRecord 新增 8 字段全带默认值；旧 invoice_index.json 无这些键→默认值加载，无需迁移脚本、无第二存储。

## 5. GUI 实测（offscreen 1280×800）

- 全部新控件存在；发票表 viewport 高 441px ≈ 15 行 ≥ 12
- 邮件区压缩为单行（账户·已下载·待重试 + 同步/管理邮箱按钮）；完整面板迁入 `MailManagerDialog`，`invoice_page.mail_panel` 别名兼容
- 统计行：已归档 | 异常待审核 | 重复 | 其他附件（待审核目录计数）
- 月份下拉 = 归档月 ∪ 待处理月；导出走后台 worker

## 6. 测试

**227 passed, 1 skipped**（新增 15 例；修复跨文件测试污染：隐藏窗口不再弹模态 warning + 陈旧队列信号防死锁 + close 后丢弃 worker 信号）

## 7. 未做（按任务书）

- 未对真实 28 份执行自动归档（dry-run only，等你核对后手动执行）
- 未动 mail_sync.db、未迁移真实文件
- 财务审批/支付/会计入账不在范围
- Windows CI 以 GitHub Actions 为准（见 PR 检查结果）

## 8. 待确认业务规则

- 报销人默认 `待指定`（可在设置或审核中填，不会拿购买方企业名顶替）
- 类别字典在 `expense_categories.py`，不确定恒 `待确认`；真实 28 份当前分布：差旅费 10 / 业务招待费 5 / 待确认 13
- 费用发生地无证据留空（不拿开票方注册地址顶替）
