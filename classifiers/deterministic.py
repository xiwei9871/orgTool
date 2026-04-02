"""High-confidence deterministic desktop file rules."""

from __future__ import annotations

from classifiers.base import BaseClassifier, ClassificationResult
from models.desktop import DesktopItem


DETERMINISTIC_EXTENSION_RULES = {
    ".lnk": "快捷方式",
    ".exe": "安装包",
    ".msi": "安装包",
    ".zip": "压缩包",
    ".rar": "压缩包",
    ".7z": "压缩包",
    ".jpg": "图片",
    ".jpeg": "图片",
    ".png": "图片",
    ".bmp": "图片",
    ".webp": "图片",
    ".mp4": "视频",
    ".mov": "视频",
    ".avi": "视频",
    ".mp3": "音频",
    ".wav": "音频",
}


class DeterministicClassifier(BaseClassifier):
    """Resolve categories with high-confidence static rules."""

    def classify(self, item: DesktopItem) -> ClassificationResult | None:
        if item.item_type == "folder":
            return ClassificationResult("文件夹", 1.0, "deterministic: folder")

        category = DETERMINISTIC_EXTENSION_RULES.get(item.extension)
        if category is None:
            return None

        return ClassificationResult(
            category=category,
            confidence=1.0,
            reason=f"deterministic: extension {item.extension}",
        )
