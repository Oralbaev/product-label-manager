"""
Label PDF generation — fixed size 43 mm × 25 mm.

Every page is exactly:
  width  = 43 * mm  ≈ 121.89 pt
  height = 25 * mm  ≈  70.87 pt

Content:
  Product name  — bold, centered, up to 2 lines, auto-shrinks to fit
  Selling price — bold, centered, integer + ₸

No A4, no Letter, no barcode on the label, no dynamic sizes.
"""

import io
import os
import platform

from django.conf import settings
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

from .models import ProductVariant

# ── Fixed label dimensions ────────────────────────────────────────────────────

LABEL_W_MM: int = 43
LABEL_H_MM: int = 25

LABEL_W_PT: float = LABEL_W_MM * mm   # ≈ 121.89 pt
LABEL_H_PT: float = LABEL_H_MM * mm   # ≈  70.87 pt

# ── Layout constants for 43 × 25 mm ──────────────────────────────────────────

_MARGIN_MM  = 1.2    # left / right / bottom clamp (mm)
_GAP_MM     = 2.0    # vertical gap between name block and price (mm)
_NAME_PT    = 19     # starting font size for product name (reduced if text is long)
_PRICE_PT   = 22     # font size for selling price (bold)
_LINE_RATIO = 1.25   # inter-baseline multiplier when name wraps to 2 lines

# Pre-computed in ReportLab user units (points)
_MARGIN  = _MARGIN_MM * mm
_GAP     = _GAP_MM   * mm
_AVAIL_W = LABEL_W_PT - 2 * _MARGIN   # usable horizontal span ≈ 76.54 pt

# ── Font registration (once per process) ──────────────────────────────────────

_fonts_ready = False


def _find_font_file(filename: str) -> str | None:
    """
    Search order:
      1. <project_root>/fonts/<filename>   ← drop custom fonts here
      2. C:\\Windows\\Fonts\\<filename>    ← Windows system fonts
    """
    project_path = os.path.join(settings.BASE_DIR, 'fonts', filename)
    if os.path.exists(project_path):
        return project_path
    if platform.system() == 'Windows':
        win_fonts = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
        candidate = os.path.join(win_fonts, filename)
        if os.path.exists(candidate):
            return candidate
    return None


def _register_fonts() -> bool:
    """
    Register Unicode TTF fonts supporting Cyrillic, Kazakh letters, and ₸.

    Priority (bold):
      DejaVuSans-Bold.ttf  → segoeuib.ttf  → arialbd.ttf
    """
    global _fonts_ready
    if _fonts_ready:
        return True

    bold_path: str | None = None
    for name in ['DejaVuSans-Bold.ttf', 'segoeuib.ttf', 'arialbd.ttf']:
        p = _find_font_file(name)
        if p:
            bold_path = p
            break

    if bold_path:
        pdfmetrics.registerFont(TTFont('LabelFont-Bold', bold_path))

    _fonts_ready = bool(bold_path)
    return _fonts_ready


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_price(selling_price) -> str:
    """Integer price with space thousands separator and ₸, e.g. '12 500 ₸'."""
    return '{:,}'.format(int(selling_price)).replace(',', ' ') + ' ₸'


def _greedy_wrap(c, text: str, font_name: str, font_size: float,
                 max_width: float) -> list[str]:
    """Word-wrap text into lines that each fit within max_width points."""
    words = text.split()
    if not words:
        return ['']
    lines: list[str] = []
    current = ''
    for word in words:
        candidate = (current + ' ' + word).strip() if current else word
        if c.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or ['']


def _wrap_to_lines(c, text: str, font_name: str, start_size: int,
                   max_width: float, max_lines: int = 2) -> tuple[list[str], int]:
    """
    Return (lines, font_size) at the largest size ≤ start_size where
    text fits into at most max_lines lines within max_width.
    """
    for size in range(start_size, 3, -1):
        lines = _greedy_wrap(c, text, font_name, size, max_width)
        if len(lines) <= max_lines:
            return lines, size
    return [text], 4   # absolute fallback


# ── Public API ────────────────────────────────────────────────────────────────

def generate_label_pdf(variant: ProductVariant, count: int = 1) -> bytes:
    """
    Generate a PDF with `count` identical pages.

    Every page:
      - width  = 43 mm  ≈ 121.89 pt
      - height = 25 mm  ≈  70.87 pt

    Content per page:
      Product name  — bold, centered, auto-wrap to 2 lines
      Selling price — bold, centered, integer + ₸

    No barcode on the label.
    """
    has_fonts = _register_fonts()
    font_bold = 'LabelFont-Bold' if has_fonts else 'Helvetica-Bold'

    name_text  = variant.product.name
    price_text = _format_price(variant.selling_price)

    buf = io.BytesIO()

    # ── Canvas with EXACT 43×25 mm page size ─────────────────────────────────
    c = canvas.Canvas(buf, pagesize=(LABEL_W_PT, LABEL_H_PT))
    c.setPageSize((LABEL_W_PT, LABEL_H_PT))

    for i in range(max(1, count)):
        if i > 0:
            c.showPage()
            c.setPageSize((LABEL_W_PT, LABEL_H_PT))   # reaffirm for every new page

        _draw_one_label(c, name_text, price_text, font_bold)

    c.save()
    buf.seek(0)
    return buf.read()


# ── Drawing ───────────────────────────────────────────────────────────────────

def _draw_one_label(c, name_text: str, price_text: str, font_bold: str) -> None:
    """
    Draw one label on the current canvas page (43 × 25 mm).

    ReportLab coordinate system: y = 0 at the BOTTOM, increases upward.

    Vertical layout (bottom → top):
      [free space  ~40 %]
      [price, bold, _PRICE_PT pt                ]  ← lower half
      [_GAP                                     ]
      [product name, bold, 1–2 lines, _NAME_PT pt]  ← upper half
      [free space  ~60 %]
    """
    cx = LABEL_W_PT / 2   # horizontal centre

    # ── 1. Determine name lines and actual font size ───────────────────────────
    name_lines, name_size = _wrap_to_lines(
        c, name_text, font_bold, _NAME_PT, _AVAIL_W, max_lines=2
    )
    n_lines      = len(name_lines)
    line_spacing = name_size * _LINE_RATIO
    name_block_h = name_size + (n_lines - 1) * line_spacing

    # ── 2. Total content height (name block + gap + price) ────────────────────
    content_h = name_block_h + _GAP + _PRICE_PT

    # ── 3. Vertical placement — 40 % of free space below price ───────────────
    free      = LABEL_H_PT - content_h
    price_y   = max(_MARGIN, free * 0.40)        # baseline of price text
    name_y0   = price_y + _PRICE_PT + _GAP       # baseline of LOWEST name line

    # ── 4. Draw product name (bold, bottom line first → upward) ──────────────
    c.setFont(font_bold, name_size)
    for i, line in enumerate(reversed(name_lines)):
        y = name_y0 + i * line_spacing
        c.drawCentredString(cx, y, line)

    # ── 5. Draw price (bold) ──────────────────────────────────────────────────
    c.setFont(font_bold, _PRICE_PT)
    c.drawCentredString(cx, price_y, price_text)
