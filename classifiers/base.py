"""Base models for desktop classification."""

from __future__ import annotations

from dataclasses import dataclass

from models.desktop import DesktopItem


@dataclass(slots=True)
class ClassificationResult:
    """A single classification decision."""

    category: str
    confidence: float
    reason: str
    subcategory: str = ""


class BaseClassifier:
    """Classifier interface."""

    def classify(self, item: DesktopItem) -> ClassificationResult | None:
        """Return a classification result or ``None`` if not applicable."""
        raise NotImplementedError
