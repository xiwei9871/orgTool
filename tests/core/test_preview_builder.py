"""Tests for desktop preview construction."""

from __future__ import annotations

from pathlib import Path

from classifiers.desktop_classifier import DesktopClassifier
from core.preview_builder import PreviewBuilder
from models.desktop import DesktopItem


def test_preview_builder_creates_target_path_for_paper_subcategory(
    tmp_path: Path,
) -> None:
    """Paper items should map into the archive root with subcategory folders."""
    item = DesktopItem(
        name="transformer_agent_paper.pdf",
        path=str(tmp_path / "transformer_agent_paper.pdf"),
        extension=".pdf",
        item_type="file",
    )

    preview = PreviewBuilder().build(
        item=item,
        classification=DesktopClassifier().classify(
            item,
            low_confidence_threshold=0.6,
            enable_paper_subcategory=True,
        ),
        desktop_root=tmp_path,
        archive_root_name="桌面整理",
        move_folders=False,
    )

    assert preview.suggested_category == "文献"
    assert preview.target_path == str(
        tmp_path / "桌面整理" / "文献" / "AI" / "transformer_agent_paper.pdf"
    )
    assert preview.is_skipped is False


def test_preview_builder_skips_folder_moves_when_disabled(tmp_path: Path) -> None:
    """Folders should be previewed but skipped when folder moves are disabled."""
    folder_path = tmp_path / "项目资料"
    folder_path.mkdir()
    item = DesktopItem(
        name="项目资料",
        path=str(folder_path),
        extension="",
        item_type="folder",
    )

    preview = PreviewBuilder().build(
        item=item,
        classification=DesktopClassifier().classify(item, low_confidence_threshold=0.6),
        desktop_root=tmp_path,
        archive_root_name="桌面整理",
        move_folders=False,
    )

    assert preview.is_skipped is True
    assert preview.skip_reason == "folder_move_disabled"
