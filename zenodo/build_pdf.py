"""
Build SANKET_disclosure.pdf from SANKET_disclosure.md.

Uses macOS's bundled "Arial Unicode" font so Bangla characters,
em-dashes, Greek letters, arrows, and emoji all render natively.

Run:
    /Users/.../BanglaSign/python/.venv/bin/python build_pdf.py
"""
from __future__ import annotations
import re
from pathlib import Path
from fpdf import FPDF

HERE   = Path(__file__).resolve().parent
IN_MD  = HERE / "SANKET_disclosure.md"
OUT_PDF = HERE / "SANKET_disclosure.pdf"

# macOS ships Arial Unicode in /System/Library/Fonts/Supplemental.
# Fallback to Arial.ttf (basic BMP) if Unicode isn't present.
FONT_PATHS = [
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
]
FONT_FILE = next((p for p in FONT_PATHS if p.exists()), None)
if FONT_FILE is None:
    raise SystemExit("No usable TrueType font found on this system.")


class PDF(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("U", "", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 6, "SANKET — Technical Disclosure", 0, 0, "L")
        self.cell(0, 6, "Hassan Hemal", 0, 1, "R")
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.get_y() + 1,
                  self.w - self.r_margin, self.get_y() + 1)
        self.ln(3)

    def footer(self):
        self.set_y(-14)
        self.set_font("U", "", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 6,
                  f"SANKET defensive publication  ·  Hassan Hemal  ·  "
                  f"page {self.page_no()} / {{nb}}",
                  0, 0, "C")


def strip_inline(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1 (\2)", s)
    s = s.replace("&middot;", "·").replace("&copy;", "©")
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return s


def render(pdf: PDF, md_path: Path):
    lines = md_path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        pdf.set_x(pdf.l_margin)  # always reset cursor to left margin

        # Fenced code block
        if line.startswith("```"):
            i += 1
            pdf.set_font("U", "", 8)
            pdf.set_text_color(50, 50, 50)
            pdf.set_fill_color(246, 248, 250)
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            for b in buf:
                pdf.set_x(pdf.l_margin)
                pdf.cell(0, 4, "  " + b[:130], 0, 1, "L", fill=True)
            pdf.ln(2)
            pdf.set_text_color(0, 0, 0)
            i += 1
            continue

        # Blank line
        if not line.strip():
            pdf.ln(2)
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^-{3,}$", line):
            pdf.ln(1)
            pdf.set_draw_color(180, 180, 180)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(3)
            i += 1
            continue

        # Headings
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            text = strip_inline(m.group(2))
            if level == 1:
                pdf.set_font("U", "", 18)
                pdf.ln(1)
                pdf.multi_cell(0, 9, text)
                pdf.set_draw_color(50, 50, 50)
                y = pdf.get_y()
                pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
                pdf.ln(3)
            elif level == 2:
                pdf.ln(3)
                pdf.set_font("U", "", 13)
                pdf.multi_cell(0, 7, text)
                pdf.set_draw_color(200, 200, 200)
                y = pdf.get_y()
                pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
                pdf.ln(2)
            elif level == 3:
                pdf.ln(2)
                pdf.set_font("U", "", 11)
                pdf.multi_cell(0, 6, text)
                pdf.ln(1)
            else:
                pdf.set_font("U", "", 10)
                pdf.multi_cell(0, 5, text)
            i += 1
            continue

        # Blockquote
        if line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            pdf.set_font("U", "", 10)
            pdf.set_fill_color(245, 245, 245)
            pdf.set_text_color(60, 60, 60)
            for b in buf:
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(0, 5, "  " + strip_inline(b), fill=True)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(1)
            continue

        # Bullet list
        if re.match(r"^[-*]\s+", line):
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i]):
                item = strip_inline(re.sub(r"^[-*]\s+", "", lines[i]))
                pdf.set_x(pdf.l_margin)
                pdf.set_font("U", "", 10)
                pdf.multi_cell(0, 5, "  •  " + item)
                i += 1
            continue

        # Numbered list
        if re.match(r"^\d+\.\s+", line):
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i]):
                num_match = re.match(r"^(\d+)\.\s+(.*)$", lines[i])
                num = num_match.group(1)
                text = strip_inline(num_match.group(2))
                pdf.set_x(pdf.l_margin)
                pdf.set_font("U", "", 10)
                pdf.multi_cell(0, 5, f"  {num}.  " + text)
                i += 1
            continue

        # Markdown table
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+", lines[i + 1]):
            rows = []
            while i < len(lines) and "|" in lines[i]:
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if cells and re.match(r"^:?-+:?$", cells[0] or "-"):
                    i += 1
                    continue
                rows.append(cells)
                i += 1
            if rows:
                col_count = max(len(r) for r in rows)
                avail_w = pdf.w - pdf.l_margin - pdf.r_margin
                col_w = avail_w / col_count
                pdf.set_font("U", "", 9)
                pdf.set_fill_color(230, 230, 230)
                head = rows[0]
                for c in head:
                    pdf.cell(col_w, 6, strip_inline(c)[:70], 1, 0, "L", fill=True)
                pdf.ln(6)
                pdf.set_font("U", "", 9)
                for r in rows[1:]:
                    cells = r + [""] * (col_count - len(r))
                    row_lines = 1
                    for c in cells:
                        txt = strip_inline(c)
                        lines_needed = max(1, int((len(txt) * 1.8) / col_w) + 1)
                        row_lines = max(row_lines, lines_needed)
                    h = row_lines * 4.5
                    y_start = pdf.get_y()
                    for ci, c in enumerate(cells):
                        x = pdf.l_margin + ci * col_w
                        pdf.set_xy(x, y_start)
                        pdf.rect(x, y_start, col_w, h, "D")
                        pdf.multi_cell(col_w, 4.5, strip_inline(c), 0, "L")
                    pdf.set_y(y_start + h)
                pdf.ln(2)
            continue

        # Regular paragraph
        buf = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{1,4}\s|>|[-*]\s|\d+\.\s|```|-{3,}$|\|)", lines[i]):
            buf.append(lines[i].strip())
            i += 1
        pdf.set_x(pdf.l_margin)
        pdf.set_font("U", "", 10)
        pdf.multi_cell(0, 5, strip_inline(" ".join(buf)))
        pdf.ln(1)


def main():
    pdf = PDF(orientation="P", unit="mm", format="A4")
    pdf.add_font("U", "", str(FONT_FILE))        # Unicode font
    pdf.set_margins(20, 20, 20)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    render(pdf, IN_MD)
    pdf.output(str(OUT_PDF))
    size_kb = OUT_PDF.stat().st_size / 1024
    print(f"[OK] wrote {OUT_PDF.relative_to(HERE.parent)}  ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
