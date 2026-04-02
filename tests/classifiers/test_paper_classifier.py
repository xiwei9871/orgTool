"""Tests for paper sub-classification."""

from __future__ import annotations

from classifiers.desktop_classifier import DesktopClassifier
from models.desktop import DesktopItem


def test_paper_classifier_routes_ai_papers() -> None:
    """AI-related paper names should route to the AI paper category."""
    item = DesktopItem(
        name="transformer_agent_paper.pdf",
        path="C:/Users/test/Desktop/transformer_agent_paper.pdf",
        extension=".pdf",
        item_type="file",
    )

    result = DesktopClassifier().classify(
        item,
        low_confidence_threshold=0.6,
        enable_paper_subcategory=True,
    )

    assert result.category == "文献"
    assert result.subcategory == "AI"
    assert result.confidence >= 0.8


def test_paper_classifier_routes_geophysics_papers() -> None:
    """Geophysics paper names should route to the geophysics paper category."""
    item = DesktopItem(
        name="seismic_inversion_study.pdf",
        path="C:/Users/test/Desktop/seismic_inversion_study.pdf",
        extension=".pdf",
        item_type="file",
    )

    result = DesktopClassifier().classify(
        item,
        low_confidence_threshold=0.6,
        enable_paper_subcategory=True,
    )

    assert result.category == "文献"
    assert result.subcategory == "地球物理"
    assert result.confidence >= 0.8
