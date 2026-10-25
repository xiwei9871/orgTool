# orgTool V2 基线审计报告

- 审计日期：2026-10-25
- 基线 commit：`4c1def4` `chore: prepare desktop smart organizer project`（main 唯一提交）
- 审计环境：macOS (Darwin 25.6.0)，Python 3.14.7，PySide6 6.x

## 1. 实测基线结果

`pytest -q` 在 macOS 上实测结果（非 README 声称值）：

- **52 passed / 1 failed**（README 声称 53 全通过，应为 Windows 上的结果）
- 失败用例：`tests/gui/test_main_window.py::test_main_window_scan_invoices_handles_invalid_root_gracefully`
  - 原因：测试使用 Windows 专属非法路径 `D:\??\????`（`\` 与 `?` 在 POSIX 为合法文件名字符），`mkdir` 在 macOS 上成功创建目录，因此没有进入预期的 OSError 分支。

## 2. 已确认的跨平台问题

| 文件 | 问题 |
| --- | --- |
| `utils/paths.py` | `RuntimePaths.from_env` 只读 `APPDATA`。macOS 无该环境变量，落到 `~/AppData/Roaming/<app>`（把 Windows 目录名搬到 macOS），再落到 `cwd/.runtime`。无 `platformdirs`，无 macOS `~/Library/Application Support`。 |
| `utils/shell.py` | 非 Windows 一律 `xdg-open`。macOS 无 `xdg-open`，"打开日志/报表目录"直接抛 `FileNotFoundError` 崩溃。不支持 reveal 文件；不校验路径存在。 |
| `utils/windows.py` | `resolve_desktop_directory` 实际靠 `ctypes.windll` AttributeError 静默兜底才在 macOS 得到 `~/Desktop`。职责错位（跨平台逻辑放在 windows 模块），未处理 iCloud Drive 桌面。 |
| `gui/main_window.py` | 扫描/预览/执行/撤销全部在主线程同步执行，大目录扫描冻结 UI。`gui/workers/task_worker.py` 已存在但完全未被使用。无取消机制，`closeEvent` 未等待后台任务。 |
| `services/invoice_service.py` | `scan_pending` 对不存在的 `root_dir` 直接 `mkdir` 静默创建（用户配置错误时无提示地建目录）；空 `root_dir` 会扫描当前工作目录。 |
| `gui/main_window.py` | `open_invoice_root` 方法存在但没有按钮绑定（死代码）。 |
| `config/manager.py` | `_merge_dataclass` 不支持 `list[dataclass]` 字段（S2 邮箱账户列表需要）。 |
| `scripts/build_windows.ps1` | 仅 Windows 构建，无 `--clean`，无版本标识。 |
| 缺失 | 无 `scripts/build_macos.sh`；无 `.github/workflows/`；`DesktopSmartOrganizer.spec` 只有 EXE 段、无 macOS BUNDLE 段；requirements 无 `platformdirs`/`keyring`。 |

## 3. 现有可复用资产

- `TaskWorker(QRunnable)` + `WorkerSignals`（`gui/workers/task_worker.py`）可直接用于后台任务。
- `TaskStore`/`TaskRecord` JSON 任务记录 + `UndoManager` 撤销链完整。
- `InvoiceMetadataStore` JSON 元数据（本轮保持兼容，不迁移到 SQLite）。
- `ConfigManager._merge_dataclass` 对嵌套 dataclass 宽容合并，旧版 JSON 字段缺失自动取默认值。
- `resolve_conflict_path` 目标路径冲突自动改名，可复用于邮件附件落盘。
- `compute_file_hash`（sha256）可复用于附件内容去重。

## 4. S1 改造涉及文件

- `utils/paths.py`：platformdirs 跨平台目录 + `ORGTOOL_RUNTIME_DIR` 覆盖 + 旧配置迁移。
- 新增 `utils/desktop.py`：跨平台桌面解析（Windows Known Folder / macOS ~/Desktop + iCloud / XDG）。
- `utils/windows.py`：保留 Known Folder ctypes 实现供 `utils/desktop.py` 调用。
- `utils/shell.py`：Windows Explorer / macOS Finder(`open -R`) / xdg-open 分派 + 路径校验。
- `core/`、`services/`：为扫描、预览、执行、撤销增加 `cancel_event` 协作式取消。
- `gui/main_window.py`：全部耗时操作转入 QThreadPool Worker；状态栏取消按钮；`closeEvent` 停止并等待任务。
- `services/invoice_service.py`：root_dir 校验改为明确报错而非静默创建。
- `tests/`：修复 POSIX 误判用例；新增路径迁移、shell、桌面解析、取消、后台任务用例。
- `scripts/build_macos.sh`（新增）、`scripts/build_windows.ps1`（更新）。
- `.github/workflows/tests.yml`、`build.yml`（新增）。
- `requirements.txt`：+ `platformdirs`。

## 5. 回归风险点

- `RuntimePaths` 是 dataclass，测试用 kwargs 构造——新增字段必须带默认值或改为派生 property。
- `TaskRecord` JSON 格式是撤销链的持久契约，字段不可变更。
- `invoice_index.json` 元数据格式本轮不可变更。
- `config.json` 旧格式必须原样可读；迁移只发生在目标配置不存在时，且不得覆盖用户修改。
- `test_runtime_paths_*` 两个用例以 `APPDATA` 为准，macOS 上需改造为平台条件断言或使用 `ORGTOOL_RUNTIME_DIR` 覆盖。
- GUI 后台化后，`MainWindow` 的扫描结果状态需要保证 finished 回调按序应用。
