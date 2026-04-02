"""Heuristic semantic classification placeholder."""

from __future__ import annotations

from classifiers.base import BaseClassifier, ClassificationResult
from models.desktop import DesktopItem


class HeuristicSemanticClassifier(BaseClassifier):
    """A pluggable local semantic classifier used as the MVP fallback."""

    def classify(self, item: DesktopItem) -> ClassificationResult | None:
        filename = item.name.casefold()
        paper_semantic_keywords = (
            "transformer",
            "llm",
            "neural",
            "vision",
            "agent",
            "geophysics",
            "seismic",
            "radar",
            "gpr",
            "inversion",
            "tremor",
            "dispersion",
            "subsurface",
        )

        if any(keyword in filename for keyword in paper_semantic_keywords):
            return ClassificationResult(
                category="文献",
                confidence=0.78,
                reason="semantic heuristic: academic topic keywords",
            )

        if "notes" in filename or "meeting" in filename:
            return ClassificationResult(
                category="未确定",
                confidence=0.35,
                reason="semantic heuristic: generic notes-like filename",
            )

        return ClassificationResult(
            category="未确定",
            confidence=0.2,
            reason="semantic heuristic: insufficient evidence",
        )
