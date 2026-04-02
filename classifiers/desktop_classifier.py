"""Layered desktop classification pipeline."""

from __future__ import annotations

from classifiers.base import ClassificationResult
from classifiers.deterministic import DeterministicClassifier
from classifiers.keyword_rules import KeywordRuleClassifier
from classifiers.paper_classifier import apply_paper_subcategory
from classifiers.semantic import HeuristicSemanticClassifier
from models.desktop import DesktopItem


class DesktopClassifier:
    """Classify desktop items using deterministic, keyword, and semantic layers."""

    def __init__(self) -> None:
        self._deterministic = DeterministicClassifier()
        self._keywords = KeywordRuleClassifier()
        self._semantic = HeuristicSemanticClassifier()

    def classify(
        self,
        item: DesktopItem,
        low_confidence_threshold: float,
        enable_paper_subcategory: bool = True,
    ) -> ClassificationResult:
        """Classify a desktop item with layered fallback behavior."""
        for classifier in (self._deterministic, self._keywords, self._semantic):
            result = classifier.classify(item)
            if result is None:
                continue
            return self._finalize(
                result,
                item=item,
                low_confidence_threshold=low_confidence_threshold,
                enable_paper_subcategory=enable_paper_subcategory,
            )

        return ClassificationResult(
            category="未确定",
            confidence=0.0,
            reason="no classifier matched",
        )

    def _finalize(
        self,
        result: ClassificationResult,
        item: DesktopItem,
        low_confidence_threshold: float,
        enable_paper_subcategory: bool,
    ) -> ClassificationResult:
        """Apply post-processing such as low-confidence fallback."""
        if result.category == "文献" and enable_paper_subcategory:
            result = apply_paper_subcategory(result, item.name)

        if result.confidence < low_confidence_threshold:
            return ClassificationResult(
                category="未确定",
                confidence=result.confidence,
                reason=f"{result.reason}; below threshold",
            )

        return result
