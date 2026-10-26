"""Default configuration values for the application."""

from __future__ import annotations


DEFAULT_APP_NAME = "DesktopSmartOrganizer"

DEFAULT_GENERAL_CONFIG = {
    "archive_root_name": "桌面整理",
    "desktop_path": "",
    "process_shortcuts": True,
    "process_folders": False,
    "move_folders": False,
    "whitelist_names": [],
    "whitelist_extensions": [],
    "low_confidence_threshold": 0.6,
    "enable_paper_subcategory": True,
    "skip_hidden_files": True,
    "skip_system_files": True,
}

DEFAULT_DESKTOP_CONFIG = {
    "categories": {
        "shortcut": "快捷方式",
        "installer": "安装包",
        "archive": "压缩包",
        "image": "图片",
        "video": "视频",
        "audio": "音频",
        "paper": "文献",
        "contract": "合同",
        "reimbursement": "报销",
        "resume": "简历",
        "folder": "文件夹",
        "uncertain": "未确定",
        "invoice_candidate": "发票候选",
    }
}

DEFAULT_INVOICE_CONFIG = {
    "root_dir": "",
    "pending_dir_name": "发票归档_待处理",
    "non_invoice_dir_name": "非发票附件",
    "source_dir_name": "附件来源",
    "monthly_dir_name": "按月份归档",
    "duplicate_dir_name": "重复发票",
    "report_dir_name": "导出报表",
    "log_dir_name": "处理日志",
    "metadata_dir_name": "metadata",
    "move_strong_duplicates": False,
    "mark_suspected_duplicates": True,
    "hash_algorithm": "sha256",
    "excel_name_pattern": "发票台账_{yyyymm}.xlsx",
    "month_folder_pattern": "发票{yyyymm}",
}
