# orgTool 2.0 — 网易邮箱附件同步架构

> 范围：S2（网易邮箱接入、历史补抓、增量同步）。S1 跨平台改造见
> `docs/acceptance/s1_cross_platform.md`。

## 1. 模块分层

```
gui/pages/mail_panel.py        邮箱同步面板（账户表 + 实时统计 + 控制按钮）
gui/dialogs/mail_account_dialog.py  账户添加/编辑（预设、授权码、文件夹选择、连接测试）
gui/dialogs/backfill_dialog.py      历史补抓范围选择（文件夹 + 日期范围）
gui/main_window.py             事件绑定、状态轮询（1s）、到期轮询（60s）、完成触发发票扫描

services/mail_service.py       账户 CRUD / 凭证 / 连接探测 / 单 worker 任务队列
                               / 到期调度 / 暂停-恢复-取消 / 状态快照

mail/imap_client.py            imaplib 封装：SSL、LOGIN(授权码)、IMAP ID、
                               LIST(UTF-7)、SELECT(EXAMINE)、UID SEARCH、
                               BODYSTRUCTURE、BODY[part] literal 提取
mail/utf7.py                   IMAP 修改版 UTF-7 编解码（中文文件夹名）
mail/attachment.py             BODYSTRUCTURE 树遍历、RFC2231/encoded-word 文件名、
                               PDF 字节校验（%PDF- 头 + %%EOF 尾）
mail/filenames.py              文件名消毒 + safe_join 路径穿越防护
mail/filters.py                发件人/主题/扩展名/附件名/大小组合过滤
mail/importer.py               原子写入、目录布局、SHA-256、来源 sidecar、邮箱脱敏
mail/credentials.py            CredentialStore 抽象 + keyring 实现（macOS Keychain /
                               Windows Credential Manager）+ InMemory（测试用）
mail/store.py                  SQLite 同步状态（folders / attachments / sync_tasks）
mail/sync_engine.py            历史分批补抓、增量 UID 同步、断点恢复、pending 排空、
                               指数退避重连、UIDVALIDITY 变更处理、幂等去重
mail/errors.py                 结构化错误码 + MailSyncError
mail/models.py                 账户/过滤/任务/快照数据契约 + 服务器预设表

tests/mail/fake_imap_server.py 真实 TCP fake IMAP 服务器（可控故障注入）
```

## 2. 关键设计决策

### 2.1 认证：授权码 + 系统凭证管理

- 用户只输入**客户端授权码**，UI 文案明确"不是邮箱登录密码"。
- 授权码经 `keyring` 写入 macOS Keychain / Windows Credential Manager，
  `config.json`、日志、SQLite、sidecar 中不出现授权码；`MailAccountConfig`
  数据契约里没有 secret 字段。
- `keyring` 不可用时报 `CREDENTIAL_STORE_UNAVAILABLE`，不写明文回退文件。

### 2.2 网易 IMAP ID 兼容

- `ImapClient.send_id()` 在登录后、`SELECT` 前发送 RFC 2971 `ID` 声明，
  内容为真实客户端名 `orgTool/2.0`，不伪造其他官方客户端。
- `send_id` 只记录结果（`id_supported`）；若 `SELECT` 仍被拒绝且 ID 未通过，
  错误码映射为 `IMAP_ID_UNSUPPORTED`，与 `MAILBOX_SELECT_FAILED` 区分。
- 文件夹名在线路上用修改版 UTF-7（`mail/utf7.py`），中文文件夹往返正确。

### 2.3 一致性模型（SQLite）

- `folders` 表：`account_id + name` 唯一；记录 `uidvalidity`、`last_seen_uid`。
- `attachments` 表：实体去重键
  `(account_id, folder_id, uidvalidity, uid, attachment_index)`，
  `ON CONFLICT DO NOTHING` → 同一邮件附件重复同步不产生重复行。
- `sync_tasks` 表：每个文件夹的补抓/增量任务，含 `cursor_uid`、
  since/until、计数器、状态；中断的 `running/paused` 任务在下次运行被续办。
- 崩溃恢复：运行开始 `reset_downloading()` 把 `downloading` 归位 `pending`；
  `_drain_pending()` 在每个文件夹同步前排空 pending 记录——记录本身携带
  uid + part_number，无需重扫头部即可续传，覆盖"附件已写盘但数据库未提交"
  以外的所有中断场景（写盘用 `.part` + `os.replace` 原子完成，半成品不会
  出现在正式路径）。
- UIDVALIDITY 变更：folder 记录的 uidvalidity 与服务器不一致时，本地游标
  归零重扫；旧 UIDVALIDITY 的实体记录保留，相同内容靠 SHA-256 去重。

### 2.4 两层去重

1. **实体去重**：`(account, folder, uidvalidity, uid, attachment_index)` 唯一键；
   已 `done` 且文件仍在 → 跳过。
2. **内容去重**：SHA-256 相同且文件存在 → 标记 `skipped_duplicate`，
   不写新文件。同名不同内容走 `resolve_conflict_path` 得到不冲突的新文件名。

### 2.5 落盘布局

```
<invoice_root>/                       # 既有发票根目录
  邮件原始附件/<账户标签>/<YYYYMM>/u<uid>_a<i>_<原文件名>.pdf   # 不可覆盖原件
  发票归档_待处理/<原文件名>.pdf + <原文件名>.pdf.source.json      # 进入既有扫描流程
```

- 原件写 `邮件原始附件`，uid+附件序号前缀避免同名覆盖。
- 待处理目录只做"受控导入"：复制 + sidecar，不移动原件；同名文件校验
  SHA-256，内容相同跳过、不同则冲突改名。
- `.source.json` 记录 account_label、脱敏邮箱、文件夹、uid、message-id、
  主题、发件人、收件时间、附件名、SHA-256、下载时间。
- 发票归档时 sidecar 随文件移动；`InvoiceService._attach_mail_source` 读取
  sidecar 并写入 `InvoiceRecord.source_type/notes` 完成来源追踪。
- 非 PDF 附件默认不入待处理（过滤器 `attachment_extensions` 默认 [".pdf"]）；
  扩展名+content-type 判定候选、字节头尾校验判定内容。

### 2.6 调度和并发

- `MailService` 内部 `ThreadPoolExecutor(max_workers=1)`：任务串行执行；
  同账户重复提交返回 `SYNC_CONFLICT`。
- `MainWindow` 内 60s `QTimer` 调 `sync_due_accounts()`：按账户
  `sync_interval_minutes`（默认 15 分钟）与 `last_sync_at` 判定到期。
- 1s `QTimer` 刷新面板：同步快照 + SQLite 计数；账户表按指纹增量刷新，
  不打断用户选择。
- 同步结束且 `downloaded > 0` 时自动触发既有 `scan_invoices()`，
  完成"邮箱→待处理→扫描"闭环。
- 暂停 = `pause_event` 阻塞在 checkpoint 之间；取消 = `cancel_event` +
  `OperationCancelled`；关闭窗口时 `mail_service.shutdown(timeout=3)`。

### 2.7 错误与重试

- 传输类异常（timeout/abort/SSL/conn reset）统一映射 `NETWORK_TIMEOUT`，
  仅该码进入指数退避（1s→2s→…→60s，最多 5 次），重连后自动重选文件夹。
- 认证失败 `AUTH_FAILED`、缺授权码 `AUTH_CODE_REQUIRED`、
  ID 拒绝 `IMAP_ID_UNSUPPORTED`、目录失败 `MAILBOX_SELECT_FAILED`、
  历史可见范围可疑 `SERVER_HISTORY_LIMIT`（EXISTS>0 但 SEARCH 为空时提示，
  不误判）、附件异常 `ATTACHMENT_DECODE_FAILED`、写盘 `FILE_WRITE_FAILED`、
  PDF 校验 `INVALID_PDF`、冲突 `SYNC_CONFLICT`。
- 失败附件计 attempts；`failed/server_unavailable` 且 attempts<3 的记录
  在下次增量同步时自动重试。

## 3. 数据流

```
用户点击"历史补抓" → 后台 list_folders() → BackfillDialog(服务器真实文件夹)
  → MailService.start_backfill → _SyncJob → MailSyncEngine.run
      for folder: SELECT → UIDVALIDITY 检查 → 恢复/新建任务 → 排空 pending
        → UID SEARCH(分批) → 每封: HEADER → 过滤器 → BODYSTRUCTURE
          → 每候选: upsert 实体去重 → BODY[part] 下载 → PDF 校验 → SHA-256 去重
            → 原子写原件 → mark done → 复制到待处理 + sidecar
  → 面板显示计数 → 完成后 scan_invoices()

增量同步: UID SEARCH(uid > last_seen_uid) + 失败记录重试 → last_seen_uid 前进
```

## 4. 测试策略

- `tests/mail/fake_imap_server.py`：真实 socket 上跑精简 IMAP4rev1，
  imaplib 全链路走真实协议解析；故障注入：require_id / fail_id /
  fail_login / fail_select / history_limit / abort_fetch（断连）/
  reject_fetch（NO）/ mark_uids_gone。
- 端到端：engine × fake server × 真实 SQLite × 真实文件系统，
  覆盖补抓、幂等重跑、哈希去重、中断恢复、UIDVALIDITY 变更、
  网络断连重试、失败重下、过滤器、暂停、账户隔离。
- MailService：fake engine 注入验证调度、冲突、取消、due 逻辑；
  fake server 验证 test_connection 分级探测。
- GUI：offscreen Qt 下验证面板刷新、选择保持、对话框校验、完成触发扫描。

## 5. 已知边界

- TLS 握手本身未在 fake server 覆盖（真实验收走 993/SSL）。
- 企业邮箱预设 `imaphz.qiye.163.com` 未真实验证。
- 单附件内容上限 200MB（`MAX_MESSAGE_BYTES`）。
- 暂停是协作式：当前附件下载完成后生效。
- 自动同步仅在应用运行期间执行（明确设计决定，UI 已注明）。
