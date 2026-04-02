"""Tests for layered desktop file classification."""

from __future__ import annotations

from classifiers.desktop_classifier import DesktopClassifier
from models.desktop import DesktopItem


def test_classifier_uses_deterministic_rules_for_shortcuts() -> None:
    """Shortcuts should resolve through deterministic rules."""
    item = DesktopItem(
        name="ChatGPT.lnk",
        path="C:/Users/test/Desktop/ChatGPT.lnk",
        extension=".lnk",
        item_type="shortcut",
    )

    result = DesktopClassifier().classify(item, low_confidence_threshold=0.6)

    assert result.category == "快捷方式"
    assert result.confidence == 1.0
    assert "deterministic" in result.reason


def test_classifier_marks_invoice_candidates_from_filename_keywords() -> None:
    """Invoice-like files should be routed as invoice candidates."""
    item = DesktopItem(
        name="电子发票_京东_202603.pdf",
        path="C:/Users/test/Desktop/电子发票_京东_202603.pdf",
        extension=".pdf",
        item_type="file",
    )

    result = DesktopClassifier().classify(item, low_confidence_threshold=0.6)

    assert result.category == "发票候选"
    assert result.confidence >= 0.9
    assert "invoice" in result.reason


def test_classifier_falls_back_to_uncertain_on_low_confidence() -> None:
    """Unknown documents should fall back to uncertain when confidence is low."""
    item = DesktopItem(
        name="meeting_notes_final.pdf",
        path="C:/Users/test/Desktop/meeting_notes_final.pdf",
        extension=".pdf",
        item_type="file",
    )

    result = DesktopClassifier().classify(item, low_confidence_threshold=0.6)

    assert result.category == "未确定"
    assert result.confidence < 0.6
