"""Keyword-based classification rules for document-like files."""

from __future__ import annotations

from classifiers.base import BaseClassifier, ClassificationResult
from models.desktop import DesktopItem


KEYWORD_RULES: list[tuple[str, tuple[str, ...], float, str]] = [
    ("发票候选", ("发票", "invoice", "电子发票"), 0.95, "invoice keyword"),
    ("报销", ("报销", "reimbursement"), 0.92, "reimbursement keyword"),
    ("合同", ("合同", "协议"), 0.92, "contract keyword"),
    ("简历", ("resume", "cv", "简历"), 0.92, "resume keyword"),
    ("文献", ("paper", "journal", "arxiv", "doi", "abstract", "supplementary"), 0.88, "paper keyword"),
]


class KeywordRuleClassifier(BaseClassifier):
    """Classify file names using explicit keyword matching."""

    def classify(self, item: DesktopItem) -> ClassificationResult | None:
        filename = item.name.casefold()

        for category, keywords, confidence, label in KEYWORD_RULES:
            if any(keyword.casefold() in filename for keyword in keywords):
                return ClassificationResult(
                    category=category,
                    confidence=confidence,
                    reason=f"keyword: {label}",
                )

        return None
