"""Paper sub-classification helpers."""

from __future__ import annotations

from classifiers.base import ClassificationResult

AI_KEYWORDS = (
    "transformer",
    "deep learning",
    "machine learning",
    "llm",
    "neural",
    "vision",
    "agent",
)

GEOPHYSICS_KEYWORDS = (
    "geophysics",
    "seismic",
    "radar",
    "gpr",
    "inversion",
    "tremor",
    "dispersion",
    "subsurface",
)


def apply_paper_subcategory(result: ClassificationResult, filename: str) -> ClassificationResult:
    """Attach a paper subcategory based on filename heuristics."""
    normalized = filename.casefold()

    if any(keyword in normalized for keyword in AI_KEYWORDS):
        result.subcategory = "AI"
        result.confidence = max(result.confidence, 0.85)
        result.reason = f"{result.reason}; paper subcategory: AI"
        return result

    if any(keyword in normalized for keyword in GEOPHYSICS_KEYWORDS):
        result.subcategory = "地球物理"
        result.confidence = max(result.confidence, 0.85)
        result.reason = f"{result.reason}; paper subcategory: geophysics"
        return result

    result.subcategory = "其他文献"
    result.reason = f"{result.reason}; paper subcategory: other"
    return result
