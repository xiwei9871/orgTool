# Windows Desktop Smart Organizer Design

**Date:** 2026-03-06

**Status:** Approved for MVP implementation

## Goal

Build a Windows desktop application for two related workflows:

1. Safe desktop file organization with preview, explanation, logging, and undo.
2. Invoice intake and management with PDF extraction, duplicate detection, monthly archiving, and Excel ledger export.

The MVP prioritizes safety, previewability, explainability, and recoverability over aggressive automation.

## Scope

### In scope

- Windows only
- Desktop top-level scan only
- Files, shortcuts, and folders
- Preview before any move operation
- Undo last successful desktop organization task
- Invoice processing for PDF files
- Text PDF extraction for invoice parsing
- OCR extension point for image-style PDFs without implementing OCR in MVP
- Duplicate detection by file hash and invoice business rules
- Monthly invoice archive and Excel ledger generation

### Out of scope for MVP

- Recursive organization inside nested folders
- Network APIs or cloud LLM dependency
- Automatic OCR execution
- Full workflow state management for submitted / reimbursed invoices
- Perfect Excel reverse-diff undo

## Architecture

The application uses a single-process desktop architecture:

1. `gui/` handles interaction and rendering.
2. `services/` exposes use-case level APIs to the GUI.
3. `core/` contains shared business logic for scanning, previewing, moving, logging, and undo.
4. `classifiers/` implements layered desktop file classification.
5. `invoice/` contains invoice-specific parsing, deduplication, archiving, and ledger export.
6. `models/` defines typed data contracts.
7. `config/` manages JSON configuration.
8. `utils/` contains technical helpers.

This keeps GUI code thin and allows future additions such as OCR, local models, or custom rules without rewriting the app structure.

## Runtime Storage Strategy

Repository code stays read-only after packaging. Runtime data is written to the user profile:

- Config: `%APPDATA%/DesktopSmartOrganizer/config.json`
- Logs: `%APPDATA%/DesktopSmartOrganizer/logs/`
- Task records: `%APPDATA%/DesktopSmartOrganizer/tasks/`
- Invoice metadata: `%APPDATA%/DesktopSmartOrganizer/invoice_metadata/`

This avoids permission issues when packaged as a single-file executable.

## Shared Data Flow

All destructive workflows follow the same pattern:

1. Scan source
2. Filter unsupported or skipped items
3. Build classification or extraction result
4. Build preview items
5. Show preview to the user
6. Execute safe move operations
7. Write logs and task records
8. Allow undo where supported

## Desktop Organization Design

### Scanning rules

The scanner enumerates top-level desktop entries and skips:

- hidden files
- system files
- `desktop.ini`
- unsupported shell-only objects
- user-whitelisted names
- user-whitelisted extensions

Folders are included in preview but not moved by default.

### Classification strategy

Desktop classification uses three layers.

#### Layer 1: deterministic rules

High-confidence mappings:

- `.lnk` -> `快捷方式`
- `.exe`, `.msi` -> `安装包`
- `.zip`, `.rar`, `.7z` -> `压缩包`
- image extensions -> `图片`
- video extensions -> `视频`
- audio extensions -> `音频`
- folder -> `文件夹`

#### Layer 2: keyword and pattern rules

Filename-based rule detection for document-like files:

- invoice keywords -> mark as invoice candidate
- reimbursement keywords -> `报销`
- contract keywords -> `合同`
- resume keywords -> `简历`
- paper keywords -> `文献`

Invoice candidates are surfaced in desktop preview but are meant to be processed by the invoice module rather than mixed with ordinary document archiving.

#### Layer 3: pluggable semantic classifier

The semantic interface returns:

- suggested category
- confidence
- reason
- optional subcategory

The MVP implementation uses local heuristics only. Low-confidence results go to `未确定`.

### Paper sub-classification

When enabled, papers are categorized into:

- `文献/AI`
- `文献/地球物理`
- `文献/其他文献`

based on filename heuristics.

### Archive layout

Desktop items move under a single archive root on the desktop, for example:

```text
Desktop\桌面整理\
```

Subfolders are created as needed under that root.

## Invoice Module Design

### Business workflow

The invoice module operates on a dedicated invoice root folder with these logical areas:

- pending intake
- monthly archive
- duplicate holding area
- report export
- logs
- metadata

### Input handling

MVP supports PDF invoices only.

- Text PDFs are parsed directly.
- Image-style PDFs are marked as not fully recognized.
- OCR is represented as a provider interface and can be added later.

### Invoice extraction model

Each file produces an `InvoiceRecord` with fields including:

- file name
- path
- hash
- invoice number
- invoice date
- invoice content
- amount
- seller
- source type
- recognition status
- date source

If extraction is incomplete, the record remains usable and is marked accordingly instead of failing the whole task.

### Duplicate detection

Two layers are applied:

1. File-level duplicate by hash
2. Business-level duplicate by invoice fields

Output statuses:

- `新发票`
- `强重复`
- `疑似重复`
- `待确认`

Strong duplicates are not silently archived into monthly folders. Suspected duplicates require user review.

### Archive rules

Invoices are archived by month using this date priority:

1. parsed invoice date from content
2. filename date
3. file modified time

Date source is always recorded.

### Excel ledger strategy

Each month has one workbook:

```text
发票台账_YYYYMM.xlsx
```

The workbook contains a stable tabular structure and summary values for item count and total amount.

For MVP stability, ledger updates are implemented as safe rewrite-or-update logic rather than complex spreadsheet mutation.

## Undo Strategy

### Desktop tasks

Undo is required and fully supported for the last successful desktop move task.

The task record stores:

- task id
- source and target paths
- operation type
- timestamps
- per-item status
- errors

Undo replays moves in reverse order. If the original location is occupied, a conflict-safe restored name is generated.

### Invoice tasks

Invoice undo is designed as optional MVP support.

The first implementation should focus on:

- reversing file moves where possible
- rebuilding ledger outputs if necessary

This is safer than trying to reverse spreadsheet cell-level mutations.

## Logging and Records

The system writes:

- application runtime logs
- desktop task logs
- invoice task logs
- undo logs
- error logs
- JSON task records
- invoice deduplication metadata

Logs must support diagnosis, auditability, and undo recovery.

## GUI Design

The GUI follows the approved structure:

- one main window
- one settings dialog
- dedicated dialogs for task details and duplicate details

The main window contains two main functional pages:

1. desktop organization page
2. invoice management page

This keeps the MVP compact while leaving room for expansion.

## Risks and Mitigations

### Misclassification risk

Mitigation:

- preview before move
- explicit confidence display
- low-confidence fallback to `未确定`
- invoice candidates kept separate from normal document archiving

### File permission and locking failures

Mitigation:

- skip and log per item
- continue task execution

### Folder move risk

Mitigation:

- disabled by default
- preview allowed
- explicit setting required to enable

### OCR incompleteness

Mitigation:

- treat image PDFs as partially recognized
- preserve file
- expose status in preview
- reserve OCR provider interface

### Duplicate false positives

Mitigation:

- separate strong duplicate and suspected duplicate
- do not auto-process suspected duplicate as a final action

### Packaged runtime write failures

Mitigation:

- keep runtime state under `%APPDATA%`

