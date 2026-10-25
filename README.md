# Desktop Smart Organizer

桌面智能整理工具，面向桌面文件整理和发票归档两个高频场景，支持 Windows 与 macOS。

## 功能概览

- 桌面扫描、预览、执行整理，并支持最近一次撤销
- 基于规则和启发式分类桌面文件
- 发票待处理目录扫描、文本提取、解析、去重和归档
- 按月份归档发票，并导出 Excel 台账
- 网易邮箱（163/126/企业）IMAP 附件同步：授权码认证、历史补抓、增量轮询、断点恢复、幂等去重
- PySide6 图形界面，包含“桌面整理”和“发票管理”两个页面
- 扫描、预览、归档、邮箱同步均在后台执行，界面可取消、关闭时安全停止

## 运行环境

- Windows 10+ / macOS 13+
- Python 3.11+

## 安装依赖

```powershell
python -m pip install -r requirements.txt
```

## 启动应用

```powershell
python main.py
```

## 运行测试

```powershell
pytest -q
```

当前测试基线为 180 个测试通过 / 1 个跳过（仅 Windows 用例）。

## 网易邮箱同步

支持把网易邮箱里的 PDF 附件自动下载到 `发票归档_待处理`：

- 认证使用**客户端授权码**（不是登录密码），存入系统凭证管理器
- 163 / 126 / 企业邮箱预设，可自定义服务器
- 历史邮件补抓（分批、断点恢复）、新邮件定时轮询（默认 15 分钟，仅应用运行期间）
- 重复同步不产生重复文件；下载来源信息保留在 `.source.json`

详见 `docs/user_guide_netease_mail.md` 与 `docs/architecture/orgtool_v2_mail_sync.md`。

## 打包

Windows（生成 `dist\DesktopSmartOrganizer.exe`，未签名）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

macOS（生成 `dist/DesktopSmartOrganizer.app` 与 `dist/DesktopSmartOrganizer-macos.zip`，未签名未公证）：

```bash
bash ./scripts/build_macos.sh
```

未签名产物首次运行需要在系统安全设置中允许（macOS: 系统设置 → 隐私与安全性；Windows: SmartScreen 提示）。

## 运行时目录

应用优先将配置、日志、任务记录写入平台用户目录：

```text
Windows: %APPDATA%\DesktopSmartOrganizer\
macOS:   ~/Library/Application Support/DesktopSmartOrganizer/
Linux:   ~/.config/DesktopSmartOrganizer/
```

可用环境变量 `ORGTOOL_RUNTIME_DIR` 覆盖（测试/便携模式）。如果平台目录不可写，回退到 `<cwd>/.runtime/DesktopSmartOrganizer/`。

首次升级时，旧版 `.runtime` 目录（POSIX 上还包括误用的 `~/AppData/Roaming/` 目录）中的配置与任务记录会自动迁移到平台目录，原目录保留作为备份。

## 发票目录建议

建议将发票根目录放在桌面，例如：

```text
Desktop\发票管理\
```

目录下至少包含以下子目录：

```text
邮件原始附件\
发票归档_待处理\
按月份归档\
重复发票\
导出报表\
```

## 项目结构

```text
.
├─ app.py / main.py           # 应用入口
├─ gui/                       # PySide6 界面
├─ services/                  # 业务编排层
├─ mail/                      # 邮箱 IMAP/同步状态/落盘
├─ core/                      # 桌面整理核心逻辑
├─ invoice/                   # 发票处理核心逻辑
├─ classifiers/               # 分类器
├─ config/                    # 配置模型与默认值
├─ models/                    # 数据模型
├─ utils/                     # 通用工具
├─ tests/                     # 自动化测试
└─ scripts/                   # 构建脚本
```

## 当前限制

- 桌面整理目前只处理桌面顶层内容
- 文件夹默认只做预览，不直接移动
- 发票处理当前优先支持 PDF
- OCR 相关流程保留扩展接口，但默认仍以可解析 PDF 为主
