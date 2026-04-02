# Desktop Smart Organizer

桌面智能整理工具 MVP，面向 Windows 桌面文件整理和发票归档两个高频场景。

## 功能概览

- 桌面扫描、预览、执行整理，并支持最近一次撤销
- 基于规则和启发式分类桌面文件
- 发票待处理目录扫描、文本提取、解析、去重和归档
- 按月份归档发票，并导出 Excel 台账
- PySide6 图形界面，包含“桌面整理”和“发票管理”两个页面

## 运行环境

- Windows
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

当前测试基线为 53 个测试全部通过。

## 打包

使用脚本打包 Windows 可执行文件：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

或直接运行：

```powershell
python -m PyInstaller --noconfirm --onefile --windowed main.py --name DesktopSmartOrganizer
```

默认输出：

```text
dist\DesktopSmartOrganizer.exe
```

## 运行时目录

应用优先将配置、日志、任务记录写入：

```text
%APPDATA%\DesktopSmartOrganizer\
```

如果当前环境无法写入 `%APPDATA%`，会自动回退到：

```text
<project_root>\.runtime\DesktopSmartOrganizer\
```

## 发票目录建议

建议将发票根目录放在桌面，例如：

```text
Desktop\发票管理\
```

目录下至少包含以下子目录：

```text
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

- 仅支持 Windows
- 桌面整理目前只处理桌面顶层内容
- 文件夹默认只做预览，不直接移动
- 发票处理当前优先支持 PDF
- OCR 相关流程保留扩展接口，但默认仍以可解析 PDF 为主
