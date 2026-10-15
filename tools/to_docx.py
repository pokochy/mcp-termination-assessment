# -*- coding: utf-8 -*-
"""
paper.md -> DOCX (A4, 제목·요약 1단 / 본문 2단, 바탕 10pt, 줄간격 150%)
한글(HWP)에서 열어 학회 양식에 맞춰 다듬을 수 있도록 만든 편집용 원고이다.
"""
import re
from docx import Document
from docx.shared import Pt, Mm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

HAN = "바탕"          # 본문 한글 글꼴(명조 계열)
HAN_B = "맑은 고딕"    # 제목용
LAT = "Times New Roman"

FIG = {"[그림 1]": "../figures/Fig1_overview.png", "[그림 2]": "../figures/Fig2_dual_delegation.png", "[그림 3]": "../figures/Fig3_assessment_flow.png"}
COL_W_MM = 72.5        # 2단일 때 한 단의 폭


def set_font(run, size=10, bold=False, han=HAN):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = LAT
    rPr = run._element.get_or_add_rPr()
    rf = rPr.find(qn('w:rFonts'))
    if rf is None:
        rf = OxmlElement('w:rFonts'); rPr.append(rf)
    rf.set(qn('w:ascii'), LAT)
    rf.set(qn('w:hAnsi'), LAT)
    rf.set(qn('w:eastAsia'), han)


def para(doc, text, size=10, bold=False, align=None, indent=True, han=HAN, space_after=4, lh=1.5):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(size * lh)
    pf.space_after = Pt(space_after)
    pf.space_before = Pt(0)
    if align is not None:
        p.alignment = align
    else:
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if indent:
        pf.first_line_indent = Pt(10)
    set_font(p.add_run(text), size, bold, han)
    return p


def two_columns(section):
    sectPr = section._sectPr
    cols = sectPr.xpath('./w:cols')
    c = cols[0] if cols else OxmlElement('w:cols')
    c.set(qn('w:num'), '2')
    c.set(qn('w:space'), '340')      # 약 6mm
    c.set(qn('w:equalWidth'), '1')
    if not cols:
        sectPr.append(c)


def add_table(doc, rows):
    ncol = len(rows[0])
    t = doc.add_table(rows=len(rows), cols=ncol)
    t.style = 'Table Grid'
    t.autofit = False
    tblPr = t._tbl.tblPr
    # 단 폭을 넘지 않도록 표 폭을 고정한다(자동 맞춤은 단 경계를 무시한다)
    layout = OxmlElement('w:tblLayout'); layout.set(qn('w:type'), 'fixed'); tblPr.append(layout)
    tw = OxmlElement('w:tblW'); tw.set(qn('w:w'), str(int(COL_W_MM * 56.7))); tw.set(qn('w:type'), 'dxa')
    tblPr.append(tw)
    mar = OxmlElement('w:tblCellMar')
    for side, w in (('top', 10), ('bottom', 10), ('left', 60), ('right', 60)):
        e = OxmlElement(f'w:{side}'); e.set(qn('w:w'), str(w)); e.set(qn('w:type'), 'dxa'); mar.append(e)
    tblPr.append(mar)
    # 열별 최대 글자수에 비례해 폭을 나누되 각 열에 최소 22%를 보장한다
    span = [max(len(r[ci]) for r in rows) for ci in range(ncol)]
    ratio = [max(s / sum(span), 0.22) for s in span]
    ratio = [r / sum(ratio) for r in ratio]
    widths = [Mm(COL_W_MM * r) for r in ratio]
    for ri, row in enumerate(rows):
        trPr = t.rows[ri]._tr.get_or_add_trPr()
        trPr.append(OxmlElement('w:cantSplit'))   # 한 행이 단 경계에서 나뉘지 않게 한다
        for ci, cell in enumerate(row):
            c = t.cell(ri, ci)
            c.width = widths[ci]
            c.text = ""
            p = c.paragraphs[0]
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
            p.paragraph_format.line_spacing = Pt(11.5)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.space_before = Pt(0)
            if ri < len(rows) - 1:
                p.paragraph_format.keep_with_next = True   # 표가 단 경계에서 쪼개지지 않게 한다
            set_font(p.add_run(cell), 9, ri == 0, HAN_B if ri == 0 else HAN)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def parse(md):
    out, i = [], 0
    lines = md.split("\n")
    while i < len(lines):
        if lines[i].startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            out.append(("table", rows))
            continue
        out.append(("line", lines[i]))
        i += 1
    return out


def main():
    md = open("paper.md", encoding="utf-8").read()
    doc = Document()

    s = doc.sections[0]
    s.page_width, s.page_height = Mm(210), Mm(297)
    s.left_margin = s.right_margin = Mm(25)
    s.top_margin = Mm(22)
    s.bottom_margin = Mm(20)

    body_started = False
    for kind, val in parse(md):
        if kind == "table":
            add_table(doc, val)
            continue
        ln = val.strip()
        if not ln:
            continue
        if not ln.startswith("**[") and not ln.startswith("**주요어"):
            ln = ln.replace("**", "")   # 본문에 남은 마크다운 강조 표시를 지운다

        if ln.startswith("# "):
            para(doc, ln[2:], 15, True, WD_ALIGN_PARAGRAPH.CENTER, False, HAN_B, 6)
        elif ln.startswith("## "):
            if not body_started and ln.startswith("## I."):
                body_started = True
                sec = doc.add_section(WD_SECTION.CONTINUOUS)
                sec.left_margin = sec.right_margin = Mm(25)
                sec.top_margin = Mm(22); sec.bottom_margin = Mm(20)
                two_columns(sec)
            head_txt = ln[3:]
            extra = 14 if head_txt.strip().startswith("요") else 0  # 요약 위 여백 확보
            p = para(doc, head_txt, 11, True, WD_ALIGN_PARAGRAPH.CENTER, False, HAN_B, 5)
            p.paragraph_format.keep_with_next = True   # 장 제목만 단 끝에 남지 않게 한다
            if extra:
                p.paragraph_format.space_before = Pt(extra)
        elif ln.startswith("### "):
            para(doc, ln[4:], 10, True, WD_ALIGN_PARAGRAPH.LEFT, False, HAN_B, 3).paragraph_format.keep_with_next = True
        elif ln.startswith("**[그림"):
            key = re.search(r"\[그림 \d\]", ln).group(0)
            cap = ln.replace("**", "").replace(key, "").strip()
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(2)
            p.add_run().add_picture(FIG[key], width=Mm(COL_W_MM * 0.90 if body_started else 150))
            para(doc, cap, 9, True, WD_ALIGN_PARAGRAPH.CENTER, False, HAN_B, 6)
        elif re.match(r"^(표|Table) \d+\.", ln):
            cap = para(doc, ln, 9, True, WD_ALIGN_PARAGRAPH.LEFT, False, HAN_B, 2)
            cap.paragraph_format.keep_with_next = True
        elif ln.startswith("**주요어"):
            para(doc, ln.replace("**", ""), 10, True, WD_ALIGN_PARAGRAPH.LEFT, False, HAN_B, 8)
        elif re.match(r"^\[\d+\]", ln):
            para(doc, ln, 9.5, False, WD_ALIGN_PARAGRAPH.JUSTIFY, False, HAN, 2, 1.35)
        else:
            if not body_started:
                # 제목면: 긴 줄은 요약 본문, 짧은 줄은 저자/소속
                if len(ln) > 120:
                    para(doc, ln, 10, False, WD_ALIGN_PARAGRAPH.JUSTIFY, True, HAN, 4)
                else:
                    para(doc, ln, 10, False, WD_ALIGN_PARAGRAPH.CENTER, False, HAN, 2)
            else:
                para(doc, ln, 10, False, WD_ALIGN_PARAGRAPH.JUSTIFY, True, HAN, 4)

    out = "논문_편집용.docx"
    doc.save(out)
    print("saved:", out)


if __name__ == "__main__":
    main()
