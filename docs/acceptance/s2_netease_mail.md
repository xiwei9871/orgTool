# S2 验收报告 — 网易邮箱附件同步

> 状态：**PENDING_LIVE_VALIDATION**
> 自动化测试全部通过（fake IMAP 全链路），但按验收规则，只有真实网易账户
> 完成完整闭环后才能标记 PASS。

## 1. 范围

- 授权码认证（Keychain / Credential Manager，不存明文）。
- IMAP ID（RFC 2971）、文件夹发现（UTF-7 中文名）、UID SEARCH/FETCH。
- MIME/RFC2231/encoded-word 附件名、inline + attachment PDF、字节校验。
- 历史补抓：分批 UID、任务持久化、断点恢复、取消/暂停。
- 增量同步：到期轮询（默认 15 分钟，应用运行期间）、失败重试、
  账户级防并发。
- 落盘：`邮件原始附件/` 原件 + `发票归档_待处理/` 受控导入 +
  `.source.json` 来源追踪；归档后保留在发票记录。
- 去重：实体键（account/folder/uidvalidity/uid/index）+ SHA-256 内容。

## 2. 自动化验证结果（macOS, Python 3.14.7）

命令：`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q`

| 套件 | 结果 |
| --- | --- |
| 全量 | **180 passed, 1 skipped** |
| mail 相关（tests/mail + mail_service + mail_gui） | 87 passed |
| 回归（S1 + 原有） | 无回退 |

fake IMAP 服务器为真实 TCP socket，imaplib 走真实协议解析；故障注入
覆盖了任务书要求的场景：

| 任务书场景 | 覆盖 |
| --- | --- |
| 正确/错误授权码 | PASS（AUTH_FAILED 区分） |
| 连接成功但 SELECT 失败 | PASS（MAILBOX_SELECT_FAILED） |
| 需要 IMAP ID 的服务器 | PASS（ID 前置发送 + 拒绝映射） |
| 文件夹发现（中文/UTF-7） | PASS |
| 历史分页 / 服务器历史范围限制 | PASS |
| UIDVALIDITY 更新 | PASS（重扫+哈希去重） |
| 中文附件名 / MIME 异常 / 多附件 / 同名不同内容 / 内容相同不同邮件 | PASS |
| 超大文件 | PASS（declared size + MAX_MESSAGE_BYTES 上限） |
| 断网恢复 | PASS（abort→退避→重连→重选文件夹） |
| 增量同步 / 失败重试 / 两次重复同步 | PASS |
| 原子写入 / 路径穿越 / 中文路径 / 中断 | PASS |
| GUI（添加/测试/补抓/暂停恢复/状态/完成后扫描/错误展示） | PASS（offscreen） |

## 3. 真实网易账户闭环（**待执行**）

以下必须在本地真实账户完成（凭证不提交仓库）：

- [ ] 授权码连接 `imap.163.com:993` SSL → LOGIN → ID → LIST → SELECT →
  UID SEARCH → UID FETCH 全通过。
- [ ] 下载 ≥1 个真实 PDF 附件到 `邮件原始附件/` + `发票归档_待处理/`。
- [ ] 重复同步：不产生重复文件（实体 + SHA-256 均跳过）。
- [ ] 中断再恢复：补抓继续、无丢失无重复。
- [ ] 向该邮箱发送新的 PDF 附件邮件 → 轮询自动下载 → 发票页扫描可见。
- [ ] 126 / 企业邮箱预设（如可用）。

**完成方法**：启动应用 → 发票管理 → 邮箱同步 → 添加邮箱 → 本地输入
授权码 → 测试连接 → 历史补抓 → 等待轮询。不要向任何人发送授权码。

## 4. 平台状态

| 平台 | 测试 | 构建 | GUI | 备注 |
| --- | --- | --- | --- | --- |
| macOS (arm64) | 180 passed / 1 skipped | PASS (.app/.zip) | PASS | adhoc 签名，未公证 |
| Windows | PENDING_CI | PENDING_CI | NOT_RUN | 等 CI/手工验证 |

## 5. 已知边界与遗留

- fake server 不覆盖真实 TLS 握手细节（版本协商、证书）。
- 企业邮箱预设未真实验证。
- 自动同步仅在应用运行期间执行（设计决定，UI 已注明）。
- 暂停为协作式（当前附件完成后生效）。
- `SERVER_HISTORY_LIMIT` 目前是提示性标记而非断言（EXISTS>0 且 SEARCH
  为空时）——避免对任意失败做武断推断。
- PR 创建待 `gh` 认证；分支可先行推送。
