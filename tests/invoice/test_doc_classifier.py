"""Document classifier tests — grounded in the S3 baseline findings."""

from __future__ import annotations

from invoice.doc_classifier import (
    DOC_E_INVOICE,
    DOC_HOTEL_FOLIO,
    DOC_NEEDS_OCR,
    DOC_OTHER,
    DOC_TRAVEL_VOUCHER,
    classify_pdf_text,
    find_invoice_links,
)


def test_e_invoice_with_invoice_number():
    text = "电子发票（普通发票） 发票号码： 开票日期： 26352000002308138771 价税合计"
    assert classify_pdf_text(text) == DOC_E_INVOICE


def test_voucher_without_number_stays_voucher():
    text = "滴滴出行-行程单 DIDI TRAVEL - TRIP TABLE 共1笔行程， 合计44.50元" * 3
    assert classify_pdf_text(text) == DOC_TRAVEL_VOUCHER


def test_voucher_with_real_invoice_number_is_invoice():
    # 飞猪报销凭证携带真实发票号码 → 仍是发票，不因"凭证"字样降级
    text = "机票款凭证 报销凭证 电子发票（普通发票） 发票号码：26317000001234567890 价税合计"
    assert classify_pdf_text(text) == DOC_E_INVOICE


def test_hotel_folio():
    text = "北京首都机场新国展美仑酒店 结账单 入住日期：2026-09-14 离店日期：2026-09-16 消费合计 763.30" * 2
    assert classify_pdf_text(text) == DOC_HOTEL_FOLIO


def test_other_pdf():
    text = "Fundamentals of Rock Mechanics chapter 3 " * 10
    assert classify_pdf_text(text) == DOC_OTHER


def test_image_only_pdf_needs_ocr():
    assert classify_pdf_text("") == DOC_NEEDS_OCR
    assert classify_pdf_text("短文本") == DOC_NEEDS_OCR


def test_find_invoice_links():
    body = "您的电子发票已开具，请下载 https://fp.example.com/dzfp/download?id=12345 谢谢"
    assert find_invoice_links(body) == [
        "https://fp.example.com/dzfp/download?id=12345"
    ]


def test_find_invoice_links_ignores_plain_links():
    assert find_invoice_links("看这里 https://example.com/about-us") == []


def test_find_invoice_links_dedup():
    body = "a https://x.com/fapiao b https://x.com/fapiao c"
    assert len(find_invoice_links(body)) == 1
