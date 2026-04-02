# Desktop Smart Organizer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Windows-only PySide6 desktop application that safely previews and moves desktop files, manages PDF invoices with duplicate detection and monthly Excel ledgers, and supports reliable logging plus undo for the last desktop organization task.

**Architecture:** Use a layered single-process application. Keep the GUI thin, route all user actions through `services/`, centralize reusable move / logging / task-record behavior in `core/`, and isolate invoice-specific behavior under `invoice/`. Runtime data must live in `%APPDATA%/DesktopSmartOrganizer/`, not beside the executable.

**Tech Stack:** Python 3.11+, PySide6, pathlib, shutil, json, logging, hashlib, openpyxl, pypdf

---

### Task 1: Bootstrap Project Skeleton

**Files:**
- Create: `main.py`
- Create: `app.py`
- Create: `README.md`
- Create: `requirements.txt`
- Create: `config/__init__.py`
- Create: `models/__init__.py`
- Create: `utils/__init__.py`
- Create: `core/__init__.py`
- Create: `classifiers/__init__.py`
- Create: `invoice/__init__.py`
- Create: `services/__init__.py`
- Create: `gui/__init__.py`
- Create: `tests/__init__.py`

**Step 1: Write the failing smoke test**

Create `tests/test_smoke_imports.py` with imports for `app` and a trivial assertion.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_smoke_imports.py -v`
Expected: FAIL because files do not exist yet.

**Step 3: Write minimal implementation**

Add the entry files and package markers so imports succeed.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_smoke_imports.py -v`
Expected: PASS.

**Step 5: Commit**

If a Git repository is initialized, commit with:

```bash
git add .
git commit -m "chore: bootstrap desktop organizer project"
```

### Task 2: Implement Configuration and Runtime Path Management

**Files:**
- Create: `config/defaults.py`
- Create: `config/schema.py`
- Create: `config/manager.py`
- Create: `utils/paths.py`
- Test: `tests/test_config_manager.py`

**Step 1: Write the failing test**

Cover:

- default config generation
- runtime directory creation
- config load when file is missing
- config save and reload

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_manager.py -v`
Expected: FAIL because config classes are missing.

**Step 3: Write minimal implementation**

Implement:

- app runtime root resolver under `%APPDATA%/DesktopSmartOrganizer/`
- typed config dataclasses
- JSON load/save with defaults merge

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_manager.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add config utils tests/test_config_manager.py
git commit -m "feat: add configuration management"
```

### Task 3: Add Logging and Task Record Infrastructure

**Files:**
- Create: `models/task.py`
- Create: `core/task_store.py`
- Create: `services/log_service.py`
- Test: `tests/core/test_task_store.py`

**Step 1: Write the failing test**

Cover:

- task record serialization
- saving task records to JSON
- retrieving the latest task by type

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_task_store.py -v`
Expected: FAIL because task store is missing.

**Step 3: Write minimal implementation**

Implement:

- task record dataclasses
- JSON persistence helpers
- logger bootstrap for app, task, undo, and error logs

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_task_store.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add models/task.py core/task_store.py services/log_service.py tests/core/test_task_store.py
git commit -m "feat: add task storage and logging"
```

### Task 4: Implement File Attribute Filters and Conflict Resolution

**Files:**
- Create: `utils/file_attrs.py`
- Create: `core/filters.py`
- Create: `core/conflict_resolver.py`
- Test: `tests/core/test_conflict_resolver.py`
- Test: `tests/core/test_filters.py`

**Step 1: Write the failing tests**

Cover:

- whitelist checks by name and extension
- `desktop.ini` skip logic
- conflict rename sequence: `name.ext`, `name (1).ext`, `name (2).ext`

**Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_conflict_resolver.py tests/core/test_filters.py -v`
Expected: FAIL because modules are missing.

**Step 3: Write minimal implementation**

Implement helpers for:

- safe skip rules
- Windows file attribute inspection with graceful fallback
- conflict-safe target name generation

**Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_conflict_resolver.py tests/core/test_filters.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add utils/file_attrs.py core/filters.py core/conflict_resolver.py tests/core/test_conflict_resolver.py tests/core/test_filters.py
git commit -m "feat: add filters and conflict resolver"
```

### Task 5: Build Desktop Scan Models and Scanner

**Files:**
- Create: `models/common.py`
- Create: `models/desktop.py`
- Create: `core/scanner.py`
- Test: `tests/core/test_scanner.py`

**Step 1: Write the failing test**

Cover:

- top-level desktop enumeration
- skip hidden/system/whitelist items
- include files, folders, and shortcuts
- do not recurse into subfolders

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_scanner.py -v`
Expected: FAIL because scanner is missing.

**Step 3: Write minimal implementation**

Implement:

- shared item metadata model
- desktop item model
- scanner service that returns structured scan results

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_scanner.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add models/common.py models/desktop.py core/scanner.py tests/core/test_scanner.py
git commit -m "feat: add desktop scanner"
```

### Task 6: Implement Layered Desktop Classification

**Files:**
- Create: `classifiers/base.py`
- Create: `classifiers/deterministic.py`
- Create: `classifiers/keyword_rules.py`
- Create: `classifiers/semantic.py`
- Create: `classifiers/paper_classifier.py`
- Create: `classifiers/desktop_classifier.py`
- Test: `tests/classifiers/test_desktop_classifier.py`
- Test: `tests/classifiers/test_paper_classifier.py`

**Step 1: Write the failing tests**

Cover:

- deterministic categories
- invoice candidate detection
- paper category detection
- AI vs geophysics paper subcategory
- low-confidence fallback to `未确定`

**Step 2: Run tests to verify they fail**

Run: `pytest tests/classifiers/test_desktop_classifier.py tests/classifiers/test_paper_classifier.py -v`
Expected: FAIL because classifiers are missing.

**Step 3: Write minimal implementation**

Implement the layered classifier pipeline with a pluggable semantic classifier contract.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/classifiers/test_desktop_classifier.py tests/classifiers/test_paper_classifier.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add classifiers tests/classifiers
git commit -m "feat: add layered desktop classification"
```

### Task 7: Build Desktop Preview and Move Execution

**Files:**
- Create: `core/preview_builder.py`
- Create: `core/move_executor.py`
- Create: `services/desktop_service.py`
- Test: `tests/core/test_preview_builder.py`
- Test: `tests/core/test_move_executor.py`
- Test: `tests/services/test_desktop_service.py`

**Step 1: Write the failing tests**

Cover:

- preview item fields
- archive path construction
- skip handling for low-confidence or disabled folder moves
- actual move execution with JSON task record output

**Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_preview_builder.py tests/core/test_move_executor.py tests/services/test_desktop_service.py -v`
Expected: FAIL because preview and move services are missing.

**Step 3: Write minimal implementation**

Implement:

- preview item model population
- safe move executor using conflict resolver
- service API for scan, preview, and execute

**Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_preview_builder.py tests/core/test_move_executor.py tests/services/test_desktop_service.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add core/preview_builder.py core/move_executor.py services/desktop_service.py tests/core/test_preview_builder.py tests/core/test_move_executor.py tests/services/test_desktop_service.py
git commit -m "feat: add desktop preview and execution workflow"
```

### Task 8: Implement Desktop Undo

**Files:**
- Create: `core/undo_manager.py`
- Test: `tests/core/test_undo_manager.py`

**Step 1: Write the failing test**

Cover:

- latest successful desktop task lookup
- reverse-order restore
- conflict-safe restore name handling
- partial failure logging without full abort

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_undo_manager.py -v`
Expected: FAIL because undo manager is missing.

**Step 3: Write minimal implementation**

Implement undo for the latest desktop organization task only.

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_undo_manager.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add core/undo_manager.py tests/core/test_undo_manager.py
git commit -m "feat: add desktop undo workflow"
```

### Task 9: Implement Invoice Models, Hashing, and PDF Text Extraction

**Files:**
- Create: `models/invoice.py`
- Create: `utils/file_hash.py`
- Create: `invoice/scanner.py`
- Create: `invoice/pdf_text_extractor.py`
- Create: `invoice/ocr_provider.py`
- Test: `tests/invoice/test_pdf_text_extractor.py`
- Test: `tests/invoice/test_scanner.py`

**Step 1: Write the failing tests**

Cover:

- invoice PDF enumeration from pending directory
- hash generation
- text extraction success and graceful failure
- OCR placeholder behavior for unsupported recognition

**Step 2: Run tests to verify they fail**

Run: `pytest tests/invoice/test_pdf_text_extractor.py tests/invoice/test_scanner.py -v`
Expected: FAIL because invoice modules are missing.

**Step 3: Write minimal implementation**

Implement:

- invoice models
- file hashing helper
- invoice pending scanner
- PDF text extraction using `pypdf`
- OCR provider interface stub

**Step 4: Run tests to verify they pass**

Run: `pytest tests/invoice/test_pdf_text_extractor.py tests/invoice/test_scanner.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add models/invoice.py utils/file_hash.py invoice/scanner.py invoice/pdf_text_extractor.py invoice/ocr_provider.py tests/invoice/test_pdf_text_extractor.py tests/invoice/test_scanner.py
git commit -m "feat: add invoice scanning and pdf extraction"
```

### Task 10: Implement Invoice Parsing and Deduplication

**Files:**
- Create: `invoice/parser.py`
- Create: `invoice/deduplicator.py`
- Create: `invoice/metadata_store.py`
- Test: `tests/invoice/test_parser.py`
- Test: `tests/invoice/test_deduplicator.py`

**Step 1: Write the failing tests**

Cover:

- invoice number extraction
- date extraction priority
- amount extraction
- duplicate status by hash
- duplicate status by invoice number and amount
- incomplete-info fallback to `待确认`

**Step 2: Run tests to verify they fail**

Run: `pytest tests/invoice/test_parser.py tests/invoice/test_deduplicator.py -v`
Expected: FAIL because parser and deduplicator are missing.

**Step 3: Write minimal implementation**

Implement:

- regex-based text parser for MVP invoice fields
- deduplication against persisted metadata index
- result statuses and evidence details

**Step 4: Run tests to verify they pass**

Run: `pytest tests/invoice/test_parser.py tests/invoice/test_deduplicator.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add invoice/parser.py invoice/deduplicator.py invoice/metadata_store.py tests/invoice/test_parser.py tests/invoice/test_deduplicator.py
git commit -m "feat: add invoice parsing and deduplication"
```

### Task 11: Implement Invoice Archive Planning and Excel Export

**Files:**
- Create: `invoice/archive_planner.py`
- Create: `invoice/excel_exporter.py`
- Test: `tests/invoice/test_archive_planner.py`
- Test: `tests/invoice/test_excel_exporter.py`

**Step 1: Write the failing tests**

Cover:

- month target folder naming
- duplicate routing behavior
- report filename generation
- workbook creation with required columns
- total count and amount summary

**Step 2: Run tests to verify they fail**

Run: `pytest tests/invoice/test_archive_planner.py tests/invoice/test_excel_exporter.py -v`
Expected: FAIL because archive planner and exporter are missing.

**Step 3: Write minimal implementation**

Implement:

- invoice target planning
- safe monthly archive paths
- Excel ledger write/update using `openpyxl`

**Step 4: Run tests to verify they pass**

Run: `pytest tests/invoice/test_archive_planner.py tests/invoice/test_excel_exporter.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add invoice/archive_planner.py invoice/excel_exporter.py tests/invoice/test_archive_planner.py tests/invoice/test_excel_exporter.py
git commit -m "feat: add invoice archive planning and excel export"
```

### Task 12: Build Invoice Service Workflow

**Files:**
- Create: `invoice/invoice_service_helpers.py`
- Create: `services/invoice_service.py`
- Test: `tests/services/test_invoice_service.py`

**Step 1: Write the failing test**

Cover:

- scan pending invoices
- build invoice preview rows
- execute archive task
- update metadata and reports
- handle duplicate and partial-recognition states safely

**Step 2: Run test to verify it fails**

Run: `pytest tests/services/test_invoice_service.py -v`
Expected: FAIL because invoice service is missing.

**Step 3: Write minimal implementation**

Implement the invoice end-to-end service orchestration.

**Step 4: Run test to verify it passes**

Run: `pytest tests/services/test_invoice_service.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add invoice/invoice_service_helpers.py services/invoice_service.py tests/services/test_invoice_service.py
git commit -m "feat: add invoice workflow service"
```

### Task 13: Build GUI Foundation and Shared Worker

**Files:**
- Create: `gui/workers/task_worker.py`
- Create: `gui/widgets/status_bar.py`
- Create: `gui/widgets/path_selector.py`
- Create: `gui/widgets/summary_cards.py`
- Create: `gui/models/preview_table_model.py`
- Create: `gui/models/invoice_table_model.py`
- Test: `tests/gui/test_table_models.py`

**Step 1: Write the failing test**

Cover:

- table model column counts
- data mapping for preview rows
- data mapping for invoice rows

**Step 2: Run test to verify it fails**

Run: `pytest tests/gui/test_table_models.py -v`
Expected: FAIL because GUI models are missing.

**Step 3: Write minimal implementation**

Implement shared Qt models and the generic background worker.

**Step 4: Run test to verify it passes**

Run: `pytest tests/gui/test_table_models.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add gui/workers/task_worker.py gui/widgets gui/models tests/gui/test_table_models.py
git commit -m "feat: add gui table models and worker"
```

### Task 14: Build Desktop and Invoice GUI Pages

**Files:**
- Create: `gui/pages/desktop_page.py`
- Create: `gui/pages/invoice_page.py`
- Create: `gui/dialogs/settings_dialog.py`
- Create: `gui/dialogs/task_detail_dialog.py`
- Create: `gui/dialogs/duplicate_dialog.py`
- Create: `gui/main_window.py`
- Modify: `app.py`
- Modify: `main.py`

**Step 1: Write the failing UI smoke test**

Create `tests/gui/test_main_window.py` to instantiate the application and main window.

**Step 2: Run test to verify it fails**

Run: `pytest tests/gui/test_main_window.py -v`
Expected: FAIL because window classes are missing.

**Step 3: Write minimal implementation**

Implement:

- main window with two functional pages
- toolbar or button areas for required actions
- settings dialog
- table-backed result areas

**Step 4: Run test to verify it passes**

Run: `pytest tests/gui/test_main_window.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add gui app.py main.py tests/gui/test_main_window.py
git commit -m "feat: add main gui workflow"
```

### Task 15: Verification, Packaging Notes, and User Documentation

**Files:**
- Modify: `README.md`
- Modify: `requirements.txt`
- Create: `logs/README.md`
- Create: `runtime_sample/appdata_layout.txt`

**Step 1: Run focused test suite**

Run:

```bash
pytest tests/core tests/classifiers tests/invoice tests/services tests/gui -v
```

Expected: PASS.

**Step 2: Run packaging smoke validation**

Run:

```bash
pyinstaller --noconfirm --onefile --windowed main.py
```

Expected: build completes and produces a Windows executable.

**Step 3: Write docs**

Document:

- setup
- config location
- desktop workflow
- invoice workflow
- packaging
- known MVP limits

**Step 4: Commit**

```bash
git add README.md requirements.txt logs/README.md runtime_sample/appdata_layout.txt
git commit -m "docs: finalize usage and packaging notes"
```

## Notes

- Because the current workspace is not a Git repository, commit steps cannot be executed until `git init` is done or the project is moved into a repository.
- MVP invoice support should treat image-only PDFs as partially recognized and preserve them for manual review.
- Folder movement remains disabled by default for safety.
