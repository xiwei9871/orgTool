# S2 未读邮件专项发票提取审计（S2 封版验收）

- 日期：2026-10-25；账户 `chenduanxiwei@163.com`（本机 Keychain 凭证，未输出授权码）
- **封版结论：验收通过**。只读审计零失败、未读状态零改变；归档管线双层 Document Gate（预览分类 + 执行复核 `326695a`）已生效，非发票无法进入台账。28 张 e_invoice 未执行归档，48 份真实文件未动。
- 范围：**冻结 `UID SEARCH UNSEEN` 返回的 105 个 UID**，逐封只读处理（readonly SELECT + BODY.PEEK，全程无 STORE，不改已读状态）
- 组件：`ImapClient.uid_search(unseen=True)`、`invoice/doc_classifier.py`（新）、`mail/unseen_audit.py`（新）

## 一、任务结果

| 指标 | 数字 |
|---|---|
| IMAP UNSEEN（冻结） | **105** |
| 成功扫描邮件 | 105/105 |
| 含 PDF 附件的邮件 | 27 |
| PDF 附件总数 | 48 |
| 去重跳过（已下载） | **48** |
| 新下载 PDF | 0 |
| 下载失败 | 0 |
| 确认电子发票（e_invoice） | 28 |
| 其他票据（凭证/结账单） | 17（8 travel_voucher + 9 hotel_folio） |
| 需人工审核 | 20（review 目录已含 needs_ocr 1 + unknown 2） |
| 发票下载链接候选 | 31 封（未访问） |

**48 个 PDF 与首轮已下载集完全重合**——此前可见的 66 封正是未读尾部，「收取全部邮件」新暴露的历史邮件均为已读。两层去重（实体记录 + SHA-256）全部命中，无一重复下载。

## 二、PDF 分类结果（新分类器，非旧 parser）

| doc_type | 数量 | 去向 |
|---|---|---|
| e_invoice | 28 | 待处理目录（均已存在，无重复写入） |
| travel_voucher | 8 | `发票管理/待审核附件/`（天府通行程单、滴滴报销单×3、ETC×2、机票出行单×2 中 4 份） |
| hotel_folio | 9 | 待审核附件（结账单 9 份） |
| needs_ocr | 1 | 待审核附件（方.pdf，无文本层） |
| unknown | 2 | 待审核附件 |
| other_pdf | 0 | — |

分类器独立于旧 `invoice.parser`——S3 基线证明旧 parser 把 16/20 非发票误判 complete；本流程不依赖其结论。每个文件带 `.source.json` 可反查 uid+part_number。

## 三、发票链接候选

31 封无附件邮件含 `invoice.stripe.com` 下载链接（ChatGPT 扣款失败重试通知）。仅记录，未访问。明细见 `s2_unread_invoice_summary.json` 与运行日志。

## 四、安全核查

- **已读状态**：处理后重跑 `UID SEARCH UNSEEN` → 105→105，UID 集合逐项比对完全一致（added 0 / removed 0），非仅比总数
- **服务器**：readonly SELECT + `BODY.PEEK`，无 STORE/EXPUNGE，未删改任何邮件
- **本地**：游标 `last_seen_uid=1320870629`（前次新增安全提醒邮件的正常推进，非本审计修改）；attachments 表仍 48 done；无文件覆盖/删除（本轮误产生的 28 个 u 前缀重复文件已清理——见下）
- **备份**：`/tmp/orgtool_unseen_backup/`

## 五、本轮发现并修复的问题

**路由命名 bug（我引入，已修）**：首跑把 raw 存档名 `u<uid>_a0_*` 写入 pending/review，与既有显示名重复 → 待处理目录出现 28 个重复。已改为用附件显示名路由 + 内容哈希早退；清理误产文件后重跑：pending 0 新增、review 20 份正确命名。

## 六、测试

新增 14 个测试（分类器 8 + 审计端到端 6）：UNSEEN 冻结集、只读无 STORE、去重不再下载、e_invoice→pending/其他→review 路由、链接候选记录不访问、UNSEEN 集合复验。全套 **202 passed, 1 skipped**。

## 七、收尾复核（2026-10-25 第二轮）

### 7.1 Document Gate（正式归档准入）

- **问题**：`发票归档_待处理/` 48 份 PDF 中只有 28 份是 e_invoice；旧 `scan→preview→execute` 管线不判型，非发票会被旧 parser 判 complete 后入台账+Excel。
- **修复**：`InvoiceService.build_preview` 入口加入文档分类闸门（`invoice/doc_classifier.classify_pdf_text`），`doc_type != e_invoice` → `is_skipped=True`、`skip_reason="non_invoice:<type>"`、`target_path=""`，预览表"备注"列显示文档类型。`InvoiceRecord` 新增 `doc_type` 字段。execute 阶段原样跳过，不产生 move/Excel。
- **回归测试**：`test_document_gate_blocks_non_invoice_from_archive`——结账单文本被闸门拦截、不移动、归档目录不创建。
- **迁移预览（未执行，不动真实文件）**：
  1. pending 中 20 份非发票 PDF（9 结账单、8 行程凭证、方.pdf、2 unknown）已在 `待审核附件/` 有同名同内容副本；
  2. 建议用户确认后把这 20 份从 pending 移入 `待审核附件/`（保留 `.source.json` 一并移动），pending 收敛为纯 e_invoice；
  3. 闸门生效后即使这 20 份留在 pending，也无法进入"预览执行归档"的移动步骤——仅显示为 `non_invoice:*` 跳过项；
  4. 本审计未移动/删除/覆盖任何真实文件。

### 7.2 链接候选只读复核

31 封 `invoice_link_candidate` 全部复核（仅本地清单数据，未访问任何链接）：

| 类别 | 数量 | 判定依据 |
|---|---|---|
| 付款失败提醒 | **31** | 主题全部为 `ChatGPT - [ACTION REQUIRED] Your credit card payment was unsuccessful` |
| 真实可下载发票通知 | 0 | 无"receipt/your invoice is ready"类主题 |
| 无法判断 | 0 | 主题明确 |

- 29 个去重 URL：**15 个 `invoice.stripe.com` 直连**（Stripe 账单门户，页面状态为待付款）+ **14 个 `mandrillapp.com` 跳转包装**（MailChimp 邮件追踪，指向同一批 Stripe 链接）。
- 结论：全部为"付款未完成"提醒邮件；链接本身是 Stripe 官方域名，但指向的是**需要支付的账单页**，不是已结清发票。按要求未点击、未登录、未下载。如需处理应由用户在浏览器中自行登录 Stripe 核对。

### 7.3 Document Gate 最终验收（2026-10-25 第三轮，commit `c00b9fc`+）

真实待处理目录预览（48 份，只读，未移动任何文件）：

| 分类 | 数量 | 结果 |
|---|---|---|
| `e_invoice` 放行 | 28 | 正常进入预览（含 dzfp×10、编号票×9、滴滴×3、飞猪报销凭证×5、幔壳×1） |
| `non_invoice` 拦截 | 20 | 全部 `is_skipped` + `target_path=""`；travel_voucher 8、hotel_folio 9、needs_ocr 1、unknown 2 |

关键证据：被拦截的 20 份中 **14 份旧 parser 判定为 `complete`**（ETC×2、天府通、滴滴报销单×3、结账单×8），若无闸门它们会被旧管线当作"识别完整的发票"移入月度归档并写入 Excel 台账——Document Gate 拦截生效。

执行时校验：`execute_preview` 原来仅信任预览行的 `is_skipped` 标记；已补齐后端复核——若 `record.doc_type != e_invoice`，即便 `is_skipped=False`（陈旧/伪造预览行）也按 `non_invoice:<type>` 跳过，不产生 move/台账/Excel。回归测试 `test_execute_preview_rechecks_document_gate` 用伪造预览行验证 moved=0、文件原地保留、归档目录不创建。

全套测试 **204 passed, 1 skipped**。

## 八、封版状态

- 分支 `feature/s2-unread-invoice-audit` 已与 main 同步（main 已含 PR #6 合并 `a447152+c00b9fc`；分支多出执行时复核 `326695a`）。
- 28 张 e_invoice **未执行归档**，48 份真实文件未移动/删除/覆盖，未生成财务台账。
- 开放项：S3.1 字段识别优化（8 张金额错误、seller/buyer、税额、内容字段、置信度分级）——在独立分支进行。
