# S2 未读邮件专项发票提取审计

- 日期：2026-10-25；账户 `chenduanxiwei@163.com`（本机 Keychain 凭证，未输出授权码）
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
| 需人工审核 | 23（review 20 + unknown 2 + needs_ocr 1） |
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
