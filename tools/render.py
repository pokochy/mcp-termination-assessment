# -*- coding: utf-8 -*-
"""
paper.md 를 학회 양식(A4, 2단, 10pt)에 근사하게 조판하여 PDF로 만든다.
분량 확인용 미리보기이며, 최종 제출본은 HWP 양식에서 작성한다.
"""
import re, sys, fitz

W, H = 595, 842
ML, MR, MT, MB = 85, 87, 64, 60
GUT = 13
COLW = (W - ML - MR - GUT) / 2
COLX = [ML, ML + COLW + GUT]

BODY = r"C:\Windows\Fonts\batang.ttc"     # 바탕 (명조 계열)
BOLD = r"C:\Windows\Fonts\malgunbd.ttf"   # 맑은 고딕 Bold

_FB = fitz.Font(fontfile=BODY)
_FH = fitz.Font(fontfile=BOLD)
def tlen(t, fontname, fontsize):
    f = _FH if fontname == "H" else _FB
    return f.text_length(t, fontsize)

FS = 10.0        # 본문 크기
LH = 1.5         # 줄간격 150%
FIG = {"[그림 1]": "../figures/Fig1_overview.png", "[그림 2]": "../figures/Fig2_dual_delegation.png", "[그림 3]": "../figures/Fig3_assessment_flow.png"}


class Doc:
    def __init__(self):
        self.doc = fitz.open()
        self.page = None
        self.col = 0
        self.y = 0
        self.title_mode = True
        self.body_top = MT      # 현재 페이지에서 2단 본문이 시작하는 y
        self._new_page()

    def _new_page(self):
        self.page = self.doc.new_page(width=W, height=H)
        self.col = 0
        self.body_top = MT
        self.y = MT
        self.page.insert_font(fontname="B", fontfile=BODY)
        self.page.insert_font(fontname="H", fontfile=BOLD)

    def _next_col(self):
        if self.col == 0:
            self.col = 1
            self.y = self.body_top
        else:
            self._new_page()

    def space(self, h):
        if self.y + h > H - MB:
            self._next_col()
        else:
            self.y += h

    def _width(self):
        return W - ML - MR if self.title_mode else COLW

    def _x(self):
        return ML if self.title_mode else COLX[self.col]

    def text(self, s, size=FS, font="B", align=0, indent=True, gap=0, lh=LH):
        if not s.strip():
            return
        s = s.replace("**", "")
        lead = size * lh
        pad = "  " if (indent and align == 0) else ""
        words = list(s)
        line, lines = pad, []
        for ch in words:
            w = tlen(line + ch, font, size)
            if w > self._width() - 2:
                lines.append(line)
                line = ch
            else:
                line += ch
        if line:
            lines.append(line)
        for ln in lines:
            if not self.title_mode and self.y + lead > H - MB:
                self._next_col()
            x = self._x()
            if align == 1:
                tw = tlen(ln, font, size)
                x = self._x() + (self._width() - tw) / 2
            self.page.insert_text((x, self.y + size), ln, fontname=font, fontsize=size)
            self.y += lead
        self.y += gap

    def image(self, path):
        pix = fitz.open(path)[0].rect
        ar = pix.height / pix.width
        w = self._width() * (0.90 if not self.title_mode else 1.0)
        h = w * ar
        if self.y + h > H - MB:
            self._next_col()
        if self.y + h > H - MB:      # 단 하나에 안 들어가면 축소
            h = H - MB - self.y
            w = h / ar
        r = fitz.Rect(self._x(), self.y, self._x() + w, self.y + h)
        self.page.insert_image(r, filename=path)
        self.y += h + 4

    def table(self, rows):
        size = 9.0
        lead = size * 1.35
        ncol = len(rows[0])
        cw = [self._width() / ncol] * ncol
        if ncol == 3:
            cw = [self._width() * 0.30, self._width() * 0.40, self._width() * 0.30]
        elif ncol == 2:
            cw = [self._width() * 0.30, self._width() * 0.70]
        need = lead * (len(rows) + 1)
        if self.y + need > H - MB:
            self._next_col()
        y0 = self.y
        for ri, row in enumerate(rows):
            fnt = "H" if ri == 0 else "B"
            # 셀 줄바꿈
            wrapped = []
            for ci, cell in enumerate(row):
                ln, out = "", []
                for ch in cell:
                    if tlen(ln + ch, fnt, size) > cw[ci] - 6:
                        out.append(ln); ln = ch
                    else:
                        ln += ch
                out.append(ln)
                wrapped.append(out)
            hmax = max(len(x) for x in wrapped)
            if self.y + lead * hmax > H - MB:
                self.page.draw_line(fitz.Point(self._x(), y0), fitz.Point(self._x() + self._width(), y0), width=0.6)
                self._next_col(); y0 = self.y
            for li in range(hmax):
                x = self._x()
                for ci in range(ncol):
                    t = wrapped[ci][li] if li < len(wrapped[ci]) else ""
                    self.page.insert_text((x + 3, self.y + size), t, fontname=fnt, fontsize=size)
                    x += cw[ci]
                self.y += lead
            if ri == 0:
                self.page.draw_line(fitz.Point(self._x(), self.y), fitz.Point(self._x() + self._width(), self.y), width=0.6)
        self.page.draw_line(fitz.Point(self._x(), y0), fitz.Point(self._x() + self._width(), y0), width=0.9)
        self.page.draw_line(fitz.Point(self._x(), self.y), fitz.Point(self._x() + self._width(), self.y), width=0.9)
        self.y += 6


def parse(md):
    blocks, i = [], 0
    lines = md.split("\n")
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            blocks.append(("table", rows))
            continue
        blocks.append(("line", ln))
        i += 1
    return blocks


def main():
    md = open("paper.md", encoding="utf-8").read()
    d = Doc()
    body_started = False
    for kind, val in parse(md):
        if kind == "table":
            d.table(val)
            continue
        ln = val.strip()
        if not ln:
            continue
        if ln.startswith("# "):
            d.text(ln[2:], size=15, font="H", align=1, indent=False, gap=4)
        elif ln.startswith("## "):
            # 제목·저자·요약·주요어는 전체 폭, 본문(I. 서론)부터 2단
            if not body_started and ln.startswith("## I."):
                body_started = True
                d.title_mode = False
                d.col = 0
                d.y += 6
                d.body_top = d.y      # 1페이지 두 단 모두 제목 영역 아래에서 시작
            head_txt = ln[3:]
            if head_txt.strip().startswith("요") and d.title_mode:
                d.y += 10   # 요약 위 여백 확보
            d.text(head_txt, size=11, font="H", align=1, indent=False, gap=3)
        elif ln.startswith("### "):
            d.text(ln[4:], size=10, font="H", indent=False, gap=2)
        elif ln.startswith("**[그림"):
            key = re.search(r"\[그림 \d\]", ln).group(0)
            cap = ln.replace("**", "").replace(key, "").strip()
            d.image(FIG[key])
            d.text(cap or key, size=9, font="H", align=1, indent=False, gap=5)
        elif re.match(r"^(표|Table) \d+\.", ln):
            d.text(ln, size=9, font="H", indent=False, gap=1)
        elif ln.startswith("**주요어"):
            d.text(ln, size=10, font="H", indent=False, gap=4)
        elif re.match(r"^\[\d+\]", ln):
            d.text(ln, size=9.5, indent=False, gap=2, lh=1.35)
        else:
            if d.title_mode:
                # 저자/소속 줄은 가운데, 요약 본문은 좌우 정렬 단락
                if len(ln) > 120:
                    d.text(ln, size=10, gap=3)
                else:
                    d.text(ln, size=10, align=1, indent=False, gap=1)
            else:
                d.text(ln, gap=3)
    out = "preview.pdf"
    try:
        d.doc.subset_fonts()          # CJK 폰트 서브셋으로 용량을 줄인다
    except Exception:
        pass
    d.doc.save(out, garbage=4, deflate=True, clean=True)
    print(f"pages: {d.doc.page_count}  -> {out}")


if __name__ == "__main__":
    main()
