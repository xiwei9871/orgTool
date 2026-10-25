"""Configurable expense-category suggestions (S3.3).

Suggestions are keyword hints only — an unsure result returns
``待确认`` and must be confirmed by the user.  The mapping can be
overridden via config without touching code.
"""

from __future__ import annotations

DEFAULT_CATEGORY_RULES: dict[str, list[str]] = {
    "办公用品": ["办公", "文具", "耗材", "打印", "复印", "纸张", "墨盒"],
    "差旅费": ["运输服务", "客运", "火车票", "机票", "航空", "铁路", "打车", "网约车", "出行"],
    "住宿费": ["住宿", "酒店", "宾馆", "旅店"],
    "业务招待费": ["餐饮", "餐费", "食品", "酒", "茶"],
    "通讯费": ["电信", "联通", "移动", "话费", "宽带", "网络服务"],
    "市内交通费": ["停车", "充电", "加油", "通行费", "地铁", "公交", "ETC"],
    "快递费": ["快递", "物流", "货运", "邮寄"],
    "图书资料费": ["图书", "教材", "出版"],
}

PENDING_CATEGORY = "待确认"


def suggest_category(
    record,
    rules: dict[str, list[str]] | None = None,
) -> str:
    """Return a category hint, or ``待确认`` when unsure.

    Never guesses: matches need a keyword hit in invoice content or
    seller name; ambiguous/absent signals stay pending.
    """
    rules = DEFAULT_CATEGORY_RULES if rules is None else rules
    haystack = f"{record.invoice_content or ''}|{record.seller or ''}"
    hits = [cat for cat, kws in rules.items() if any(k in haystack for k in kws)]
    if len(hits) == 1:
        return hits[0]
    return PENDING_CATEGORY
