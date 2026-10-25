# S2 真实网易邮箱同步审计报告

- 审计对象：`feature/s2-netease-mail` 合并入 `main`（`bc9eb19`）后的首次真实 163 同步
- 账户：`chenduanxiwei@163.com`（account_id `b4f519d67237`，label `xiwei163`）
- 审计时间：2026-10-25
- 审计方式：只读 SQLite/磁盘/IMAP 探测 + 修复后受控重跑；凭证始终留在系统钥匙串，未进入任何产物

## 一、结论速览

| 指标 | 数字 |
|---|---|
| IMAP 全账户可见邮件 | 83（11 个文件夹，含 13 封 Notes） |
| INBOX 服务器可见（EXISTS） | 66 |
| INBOX 未读（STATUS UNSEEN） | 66 |
| IMAP 全账户未读合计 | 70 |
| 网页版显示未读 | 104（用户报告） |
| 首轮实际扫描邮件 | 66（INBOX，增量模式） |
| 发现 PDF 附件候选 | 48 |
| 首轮成功下载（修复前） | 5（文件内容实为 base64 文本，属假成功） |
| 首轮失败（修复前） | 43，全部 `INVALID_PDF` |
| 修复后重试下载 | **48/48 成功，0 失败** |
| 落盘有效 PDF（pypdf 可开） | 48/48 |
| 进入发票待处理目录 | 48（含 48 个 `.source.json` 来源文件） |
| 幂等重跑 | 扫描 0 / 下载 0 / 重复 0 / 失败 0 |

## 二、任务一：邮件数量核查

### 66 是什么

66 = INBOX 的 `EXISTS`（服务器可见邮件总数），与本轮增量扫描处理的邮件数一致：该账户 `last_seen_uid` 初始为 0，`UID SEARCH 1320870629:*` 之前的全量 66 封全部处理。UID 范围 `1320870563–1320870628` 连续，`UIDVALIDITY=1`。

### 66 vs 网页版 104 未读

- 网页版 104 是**全账户未读口径**。
- IMAP `STATUS` 实测全账户未读 = 70：INBOX 66 + 垃圾邮件 3 + 广告邮件 1。
- 其余约 34 封位于未通过 IMAP `LIST` 暴露的网页端聚合（如订阅聚合、网页内建视图），**客户端按 IMAP 语义无法触及，不属于漏抓**。
- 未读数 ≠ 待下载附件数：本账户只配置了 INBOX 同步，66 封中 48 封携带符合过滤条件的 PDF。

### 顺带发现并已修复的查询怪癖

NetEase 对 `UID <大于最大UID>:*` 仍会返回顶端邮件，导致该旧 UID 被重复扫描一次。已在 `_incremental_folder` 增加 `uids > last_seen_uid` 防御过滤。

## 三、任务二：附件状态核查（修复前）

数据库 `attachments` 表（48 条）：`done=5, failed=43`。

### 48 个候选从哪来

66 封扫描 → `extract_attachments` + 过滤器（`.pdf` 扩展名 / `application/pdf`）→ 48 个候选，每封一个，数字吻合。

### 为什么只"成功"5 个、43 个 INVALID_PDF

**根因 A（主因）：传输编码未解码。**
`UID FETCH BODY[n]` 返回的部件体仍是服务端存储的 **base64 传输编码**（`JVBERi0xLjQK...` = base64 的 `%PDF-1.4`）。旧代码直接对原始字节做 PDF 头尾校验 → 43 条 `INVALID_PDF`。

**根因 B：BODYSTRUCTURE literal 未解析。**
NetEase 把非 ASCII 参数值（中文文件名）以 `{n}\r\n<内容>` literal 下发；imaplib 拼接后形态为 `{266}<内容>`（CRLF 被协议层吃掉）。旧 sexp 解析器把 `{266}` 当普通 atom、内容并入同一 atom → 文件名变成 `{266}招商银行掌上生活-信用...` 且无 `.pdf` 后缀。

**为什么 5 条"成功"：** 这 5 条的重试恰逢 `looks_like_pdf_bytes` 对 base64 文本尾部 `%%EOF` 的弱校验在部分载荷上恰好通过/或短路径判定差异——实际落盘的 5 个文件内容是 ASCII base64 文本、文件名含 `{266}`、无 `.pdf`，**均为假成功**。

### 发票待处理为什么是 0

5 个假成功文件名无 `.pdf` 后缀且内容是 base64 → 待处理导入拿到的既不是合法 PDF 也没有可扫描的 `.pdf` 名，发票扫描自然为 0。

### 剩余附件的去向

48 = 5 done + 43 failed，无"未处理/被过滤"遗留；全部可追溯。

## 四、修复内容

| 修复 | 文件 |
|---|---|
| sexp 解析器消费 `{n}` literal（按字节长度截取 UTF-8 字符，兼容 imaplib 已吃掉 CRLF 的拼接形态） | `mail/imap_client.py` |
| `folder_status()`：可靠 `MESSAGES/UNSEEN`（原 SELECT 的 UNSEEN 是序号非计数） | `mail/imap_client.py` |
| `decode_transfer_body()`：按 BODYSTRUCTURE 声明编码解码 base64/quoted-printable，失败回退原字节 | `mail/attachment.py` |
| 下载后按编码解码→校验→PDF 补 `.pdf` 后缀（raw 与待处理两处） | `mail/sync_engine.py` |
| 失败重试改为**单一聚合任务**+重取 BODYSTRUCTURE 刷新损坏的 part 名/编码/part_number | `mail/sync_engine.py` |
| UID 超出 last_seen 的防御过滤；retry 进度不污染 snapshot.processed | `mail/sync_engine.py` |
| `MailService._repair_invalid_downloads`：done 记录中本地文件为 base64/无效 PDF 者标记失败待重下，原文件不删 | `services/mail_service.py` |
| `store.done_records` / `update_attachment_meta` | `mail/store.py` |
| GUI：本轮/累计/服务器 三行口径分离 + 「重试失败」按钮；下载完成后自动刷新发票扫描（已有逻辑保留） | `gui/pages/mail_panel.py`, `gui/main_window.py` |
| fake IMAP：base64 附件体、literal 文件名、STATUS 命令、unseen 计数 | `tests/mail/fake_imap_server.py` |

### 新增回归测试（8 个）

- literal 文件名 BODYSTRUCTURE 解析（客户端 + 引擎端到端）
- base64 附件体端到端落盘为真实 PDF 字节
- `folder_status` 计数、snapshot 服务器计数
- 损坏 done 记录→服务修复→重试重下→正确文件名+真实字节+原件保留
- `_repair_invalid_downloads` 只动损坏记录（4 种样本）

全套：**188 passed, 1 skipped**。

## 五、修复后受控验证（真实账户）

- 只跑 1 次 `incremental`：服务层先把 5 条假 done 标为失败，随后 `_retry_failed` 对 48 条统一重试
- 每条重试重取 BODYSTRUCTURE → 真实文件名（含 `dzfp_..._四川幔壳科技有限公司_...` 等）→ 下载→base64 解码→PDF 校验→原子写入
- 结果：**48/48 done，0 失败**；raw 目录 + 待处理目录各 48 个 `.pdf`，48 个 sidecar
- 48/48 经 pypdf 实际打开验证
- 立即重跑第 2 次：扫描 0 / 下载 0 / 失败 0 — 完全幂等，无重复、无覆盖
- 原 5 个损坏 base64 文件保留在 raw 目录（未删除），done 记录指向新写出的正确文件
- 服务器侧全程只读（readonly SELECT + BODY.PEEK），无任何邮件状态变更

## 六、残留事项 / 建议

1. 旧 raw 目录中 5 个 `{266}...` base64 垃圾文件未删除（安全起见保留），可由用户手动清理。
2. 其他文件夹（垃圾/广告/订阅）未纳入同步范围——如有发票入垃圾邮件可勾选文件夹后历史补抓。
3. literal 内容若非 UTF-8（如 GBK 直接下发）会以替换字符呈现——目前未观察到，NetEase 均以 UTF-8 literal 下发。

## 七、数据产物

- `docs/acceptance/s2_live_mail_counts.json` — 全部计数结构化数据
- 备份：`/tmp/orgtool_audit_backups/`（修复前 DB+WAL+config 快照）
