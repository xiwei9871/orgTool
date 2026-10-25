# S1 验收报告 — 跨平台改造

- 日期：2026-10-25
- 分支：`feature/s1-cross-platform`
- 基线：`4c1def4`

## 范围

- `platformdirs` 统一用户数据目录（Windows `%APPDATA%`，macOS `~/Library/Application Support`，Linux `~/.config`），`ORGTOOL_RUNTIME_DIR` 覆盖。
- 旧版 `.runtime` / 误用 `~/AppData/Roaming` 目录自动迁移（一次性、幂等、不覆盖用户修改、原目录保留为备份 + `.storage_migration` marker）。
- `utils/shell.py`：Windows `os.startfile`/`explorer /select,`、macOS `open`/`open -R`、Linux `xdg-open`；路径不存在抛 `FileNotFoundError`。
- `utils/desktop.py`：Windows Known Folder → `~/Desktop`/OneDrive；macOS `~/Desktop` → iCloud Drive Desktop；Linux `xdg-user-dir`/`user-dirs.dirs`。
- GUI 后台化：扫描/预览/执行/撤销经 `QThreadPool` + `TaskWorker`（`QueuedConnection` 保证 slot 在 GUI 线程），状态栏取消按钮，逐页按钮防并发，`closeEvent` 取消并等待。
- `scan_pending`：缺失/空白 `root_dir` 明确报 `FileNotFoundError`，不再静默建目录。
- 构建：`scripts/build_windows.ps1`（onefile exe）、`scripts/build_macos.sh`（`.app` + zip，未签名未公证）。
- CI：`.github/workflows/tests.yml`（windows+macOS pytest，QT_QPA_PLATFORM=offscreen）、`.github/workflows/build.yml`（双平台产物上传）。

## 自动化测试结果（macOS 实测）

- 命令：`.venv/bin/python -m pytest -q`
- 结果：**93 passed / 1 skipped / 0 failed**
- skip：`test_runtime_paths_use_appdata_on_windows`（仅 Windows）
- 基线对比：52 passed / 1 failed（macOS）→ 修复该用例（POSIX 上 `D:\??\????` 是合法文件名，改用阻塞文件模拟非法根目录）

## 手工验证（macOS 本机）

- 真实 GUI 启动：`python main.py` 等价流程启动成功，`desktop_root=/Users/xiwei/Desktop`，runtime root=`~/Library/Application Support/DesktopSmartOrganizer`。PASS
- Finder 打开：单元测试验证 `open`/`open -R` 命令分派；真实 Finder 行为在开发机验证通过。
- 中文/空格路径：`桌面 目录/报告 最终版.txt` 等用例通过（`test_scan_desktop_runs_in_background_and_updates_ui`、`test_chinese_and_space_paths_pass_through_unquoted`）。

## Windows 验证状态

- **NOT_RUN（本机无 Windows 环境）**。依赖 GitHub Actions `windows-latest` 跑 pytest（CI 推送后记录结果）；`build_windows.ps1` 语法与逻辑与原版一致，增加 `--clean` 与产物存在性校验。
- 需要 Windows 真机/CI 复核项：Known Folder 桌面解析、`os.startfile`/`explorer /select,`、`.exe` 构建产物实际启动。

## macOS 签名/公证状态

- `.app` 产物**未签名、未公证**。首次运行需用户在“系统设置 → 隐私与安全性”中允许。文档与构建脚本注释均已标明，不宣称无障碍安装。

## 回归状态

- 原 52 个通过用例全部保留并通过；桌面整理/撤销/发票扫描/预览/归档逻辑未改动行为语义，仅增加 `cancel_event` 可选参数（默认 `None`，原调用兼容）。
- `config.json`、`TaskRecord` JSON、`invoice_index.json` 格式未变更。
