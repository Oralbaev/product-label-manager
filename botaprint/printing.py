"""
BotaPrint — Windows GDI direct label printing.

Architecture (per print job):
  1. build_job_devmode()   — build a per-job PyDEVMODE for 43×25 mm.
                             Uses DocumentProperties() (fallback: GetPrinter level 2).
                             Never calls SetPrinter — global settings are UNCHANGED.
  2. _create_printer_dc()  — creates the printer HDC via win32gui.CreateDC("WINSPOOL", …, devmode)
                             so the DC sees 43×25 mm, not the global 76.2×101.6 mm.
  3. render_label_image()  — Pillow RGB raster (product name + price, no barcode).
  4. _compute_dest_rect()  — centers the raster physically on the label page.
  5. ImageWin.Dib.draw()   — blits the raster to the printer DC.

Previous bug:
  _try_set_devmode() modified DEVMODE in memory but then called CreatePrinterDC(name)
  WITHOUT passing that DEVMODE.  The DC was created from the saved global settings
  (76.2×101.6 mm) and dest=(0,0,w,h) placed the label in the top-left corner.
"""

from __future__ import annotations

import logging
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

try:
    from botaprint.paper_sizes import SUPPORTED_LABEL_SIZES, DEFAULT_LABEL_SIZE
except ImportError:
    from paper_sizes import SUPPORTED_LABEL_SIZES, DEFAULT_LABEL_SIZE

# ── Default label dimensions (kept for backward-compat with /debug-printer) ──

LABEL_W_MM: int = 43
LABEL_H_MM: int = 25

# DEVMODE field flags (from winnt.h)
_DM_ORIENTATION  = 0x00000001
_DM_PAPERSIZE    = 0x00000002
_DM_PAPERWIDTH   = 0x00010000
_DM_PAPERLENGTH  = 0x00020000
_DMPAPER_USER    = 256
_DMORIENT_PORTRAIT  = 1
_DMORIENT_LANDSCAPE = 2

# DocumentProperties mode flags
_DM_OUT_BUFFER = 2
_DM_IN_BUFFER  = 8

# ── SetPrinter fallback feature flag ─────────────────────────────────────────
#
# Xprinter XP-365B may ignore per-job DEVMODE for GDI output.
# When enabled, we temporarily apply the selected paper size to the global
# printer settings (SetPrinter), print, then restore the originals in finally.
# Set to False to use only the per-job win32gui.CreateDC path.
ENABLE_TEMP_GLOBAL_PRINTER_SIZE_FALLBACK = True


# ── Resource / font helpers ───────────────────────────────────────────────────


def _resource_path(*parts: str) -> Path:
    """Resolve bundled resource path for both dev mode and PyInstaller .exe."""
    if hasattr(sys, '_MEIPASS'):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    return base.joinpath(*parts)


def _find_bold_font() -> Optional[str]:
    bundled = _resource_path('fonts', 'DejaVuSans-Bold.ttf')
    if bundled.exists():
        return str(bundled)
    for name in ('segoeuib.ttf', 'arialbd.ttf'):
        p = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / name
        if p.exists():
            return str(p)
    return None


def _load_font(pt: int, dpi: int) -> ImageFont.FreeTypeFont:
    px   = max(8, round(pt * dpi / 72))
    path = _find_bold_font()
    if path:
        try:
            return ImageFont.truetype(path, px)
        except Exception as exc:
            logger.warning('Cannot load font %r at %dpx: %s', path, px, exc)
    return ImageFont.load_default()


# ── Price / text helpers ──────────────────────────────────────────────────────


def _format_price(price) -> str:
    return '{:,}'.format(int(Decimal(str(price)))).replace(',', ' ') + ' ₸'


def _px_to_mm(px: int, dpi: int) -> float:
    return round(px * 25.4 / dpi, 2) if dpi else 0.0


def wrap_text(draw: ImageDraw.ImageDraw, text: str,
              font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return ['']
    lines, current = [], ''
    for word in words:
        candidate = (current + ' ' + word).strip() if current else word
        bb = draw.textbbox((0, 0), candidate, font=font)
        if (bb[2] - bb[0]) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or ['']


def fit_text(draw: ImageDraw.ImageDraw, text: str, start_pt: int, dpi: int,
             max_width: int, max_lines: int = 2) -> tuple[list[str], ImageFont.FreeTypeFont]:
    for pt in range(start_pt, 3, -1):
        font  = _load_font(pt, dpi)
        lines = wrap_text(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return lines, font
    return [text], _load_font(4, dpi)


# ── Per-size text-position fine-tuning ────────────────────────────────────────
#
# Physical paper/material sizes live in botaprint/paper_sizes.py and must
# NEVER be edited here. This dict only nudges where the product-name/price
# TEXT is drawn inside an already-correctly-sized label raster — it has no
# effect on paper size, DEVMODE, or the SetPrinter fallback.
#
#   x_mm > 0 → text moves right   x_mm < 0 → text moves left
#   y_mm > 0 → text moves down    y_mm < 0 → text moves up
LABEL_TEXT_OFFSETS_MM: dict[str, dict[str, float]] = {
    "30x20": {"x_mm": -1, "y_mm": -4},
}


def _text_offset_px(paper_size: Optional[str], dpi: int) -> tuple[int, int]:
    """Convert LABEL_TEXT_OFFSETS_MM[paper_size] to a (x_px, y_px) pair."""
    offsets = LABEL_TEXT_OFFSETS_MM.get(paper_size) if paper_size else None
    if not offsets:
        return 0, 0
    offset_x_px = round(offsets.get('x_mm', 0) / 25.4 * dpi)
    offset_y_px = round(offsets.get('y_mm', 0) / 25.4 * dpi)
    return offset_x_px, offset_y_px


# ── Label image rendering ─────────────────────────────────────────────────────


def render_label_image(product_name: str, price, w_px: int, h_px: int,
                       dpi: int = 203, paper_size: Optional[str] = None) -> Image.Image:
    """
    Render a label as an RGB Pillow image.
    All coordinates are relative to the raster itself, not the printer page.

    paper_size selects an optional text-position nudge from
    LABEL_TEXT_OFFSETS_MM (see above) — it does not affect w_px/h_px, which
    are already computed from the physical paper size by the caller.
    """
    img  = Image.new('RGB', (w_px, h_px), 'white')
    draw = ImageDraw.Draw(img)
    offset_x_px, offset_y_px = _text_offset_px(paper_size, dpi)

    price_text = _format_price(price)
    margin_x   = max(3, round(w_px * 0.05))
    margin_y   = max(2, round(h_px * 0.05))
    avail_w    = w_px - 2 * margin_x

    def _h(txt: str, fnt: ImageFont.FreeTypeFont) -> int:
        bb = draw.textbbox((0, 0), txt, font=fnt)
        return max(1, bb[3] - bb[1])

    # Name
    name_lines, name_font = fit_text(draw, product_name, 17, dpi, avail_w, 2)
    name_line_h   = max(_h(ln, name_font) for ln in name_lines)
    name_line_gap = max(2, round(name_line_h * 0.18))
    name_block_h  = name_line_h * len(name_lines) + name_line_gap * (len(name_lines) - 1)

    # Price
    _, price_font = fit_text(draw, price_text, 20, dpi, avail_w, 1)
    price_h       = _h(price_text, price_font)

    gap       = max(3, round(h_px * 0.06))
    content_h = name_block_h + gap + price_h
    free      = h_px - content_h - 2 * margin_y
    top_y     = margin_y + max(0, free // 2)

    # Draw name lines
    y = top_y
    for line in name_lines:
        bb = draw.textbbox((0, 0), line, font=name_font)
        x  = (w_px - (bb[2] - bb[0])) // 2
        name_x, name_y = x + offset_x_px, y + offset_y_px
        draw.text((name_x, name_y), line, font=name_font, fill='black')
        y += name_line_h + name_line_gap

    # Draw price
    y += gap - name_line_gap
    bb = draw.textbbox((0, 0), price_text, font=price_font)
    x  = (w_px - (bb[2] - bb[0])) // 2
    price_x, price_y = x + offset_x_px, y + offset_y_px
    draw.text((price_x, price_y), price_text, font=price_font, fill='black')

    return img


# ── Printer enumeration ───────────────────────────────────────────────────────


def list_printers() -> list[dict]:
    try:
        import win32print
    except ImportError:
        return []
    default = ''
    try:
        default = win32print.GetDefaultPrinter()
    except Exception:
        pass
    try:
        raw = win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS, None, 1)
        return [{'name': p[2], 'is_default': p[2] == default} for p in raw]
    except Exception as exc:
        logger.error('EnumPrinters: %s', exc)
        return []


def get_default_printer() -> str:
    try:
        import win32print
        return win32print.GetDefaultPrinter()
    except Exception:
        return ''


# ── DEVMODE: read global (for verification) ───────────────────────────────────


def read_global_devmode(printer_name: str) -> dict:
    """
    Read the printer's currently saved global DEVMODE WITHOUT modifying it.
    Used to verify that BotaPrint never corrupts global settings.
    """
    try:
        import win32print
        h = win32print.OpenPrinter(printer_name)
        try:
            info = win32print.GetPrinter(h, 2)
            dm   = info.get('pDevMode')
            if dm is None:
                return {}
            return {
                'PaperSize'  : getattr(dm, 'PaperSize',   None),
                'PaperWidth' : getattr(dm, 'PaperWidth',  None),
                'PaperLength': getattr(dm, 'PaperLength', None),
                'Orientation': getattr(dm, 'Orientation', None),
            }
        finally:
            win32print.ClosePrinter(h)
    except Exception as exc:
        logger.error('read_global_devmode(%r): %s', printer_name, exc)
        return {}


def assert_valid_devmode(devmode, name: str = 'devmode') -> None:
    """
    Raise RuntimeError unless devmode is a real PyDEVMODE object.

    win32print.DocumentProperties() can return a plain int (e.g. 1) on
    success when it mutates the supplied output buffer in place. That int
    must never be mistaken for a PyDEVMODE — accessing .PaperSize on it
    raises AttributeError deep inside GDI calls. This guard catches that
    class of bug at the boundary, with a clear error instead.
    """
    if isinstance(devmode, int):
        raise RuntimeError(f'{name} is int={devmode}, expected PyDEVMODE')
    if devmode is None:
        raise RuntimeError(f'{name} is None, expected PyDEVMODE')
    for attr in ('PaperSize', 'PaperWidth', 'PaperLength'):
        if not hasattr(devmode, attr):
            raise RuntimeError(
                f'{name} has no {attr}, type={type(devmode).__name__}'
            )


# ── DEVMODE: build per-job copy ───────────────────────────────────────────────


def build_job_devmode(printer_name: str,
                      width_mm: int = LABEL_W_MM,
                      height_mm: int = LABEL_H_MM):
    """
    Return a PER-JOB PyDEVMODE configured for the given label dimensions.

    Always returns a PyDEVMODE on success.
    Raises RuntimeError (with the real reason) on any failure.
    Never returns None.

    Strategy:
      1. DocumentProperties(DM_OUT_BUFFER) — get a fresh driver DEVMODE copy.
         Falls back to GetPrinter level-2 DEVMODE if that call fails.
      2. Modify fields: PaperSize=USER, PaperWidth, PaperLength, Orientation.
      3. DocumentProperties(DM_IN_BUFFER|DM_OUT_BUFFER) — driver validates.
         pywin32 may return int 1 (devmode modified in-place) or a new PyDEVMODE.
         Both are handled correctly; result is NEVER blindly assigned to devmode
         when it is an integer.
    """
    import win32print   # ImportError propagates to caller — not silenced

    h = win32print.OpenPrinter(printer_name)
    try:
        # ── 1. Obtain a fresh driver DEVMODE ─────────────────────────────────
        devmode        = None
        used_doc_props = False

        try:
            result = win32print.DocumentProperties(
                None, h, printer_name, None, None, _DM_OUT_BUFFER
            )
            logger.info('DocumentProperties(DM_OUT_BUFFER) result: %r  type=%s',
                        result, type(result).__name__)

            if isinstance(result, int):
                # No output buffer was supplied, so there is no existing
                # PyDEVMODE this int could refer to — it can NEVER be used
                # as a devmode. Fall back to GetPrinter level-2.
                logger.warning(
                    'DocumentProperties(DM_OUT_BUFFER) returned int=%d for %r '
                    '(no buffer to mutate in-place) — trying GetPrinter level-2 fallback',
                    result, printer_name,
                )
            elif result is not None and all(
                hasattr(result, attr) for attr in ('PaperSize', 'PaperWidth', 'PaperLength')
            ):
                devmode        = result
                used_doc_props = True
            elif result is None:
                logger.warning('DocumentProperties(DM_OUT_BUFFER) returned None '
                               'for %r — trying GetPrinter level-2 fallback', printer_name)
            else:
                logger.warning(
                    'DocumentProperties(DM_OUT_BUFFER) returned unexpected object %r '
                    '(type=%s) for %r — trying GetPrinter level-2 fallback',
                    result, type(result).__name__, printer_name,
                )
        except Exception as exc:
            logger.warning('DocumentProperties(DM_OUT_BUFFER) raised for %r: %s '
                           '— trying GetPrinter level-2 fallback', printer_name, exc)

        if devmode is None:
            info    = win32print.GetPrinter(h, 2)
            devmode = info.get('pDevMode')
            if devmode is None:
                raise RuntimeError(
                    f'No DEVMODE available for printer {printer_name!r}: '
                    'both DocumentProperties(DM_OUT_BUFFER) and GetPrinter level-2 '
                    'returned no DEVMODE object'
                )
            logger.info('Using DEVMODE from GetPrinter level-2 for %r', printer_name)

        # ── 2. Log values BEFORE modification ────────────────────────────────
        logger.info(
            'Before DocumentProperties:\n'
            '  PaperSize:   %s\n'
            '  PaperWidth:  %s\n'
            '  PaperLength: %s\n'
            '  Orientation: %s',
            getattr(devmode, 'PaperSize',   '?'),
            getattr(devmode, 'PaperWidth',  '?'),
            getattr(devmode, 'PaperLength', '?'),
            getattr(devmode, 'Orientation', '?'),
        )

        # ── 3. Apply the requested paper size ────────────────────────────────
        assert_valid_devmode(devmode, 'devmode (before modification)')
        devmode.PaperSize   = _DMPAPER_USER
        devmode.PaperWidth  = width_mm  * 10
        devmode.PaperLength = height_mm * 10
        devmode.Orientation = _DMORIENT_PORTRAIT
        devmode.Fields      = (getattr(devmode, 'Fields', 0)
                               | _DM_PAPERSIZE | _DM_PAPERWIDTH
                               | _DM_PAPERLENGTH | _DM_ORIENTATION)

        # ── 4. Validate with driver ───────────────────────────────────────────
        if used_doc_props:
            try:
                result = win32print.DocumentProperties(
                    None, h, printer_name, devmode, devmode,
                    _DM_IN_BUFFER | _DM_OUT_BUFFER,
                )
                logger.info('DocumentProperties result: %r  type=%s',
                            result, type(result).__name__)

                if isinstance(result, int):
                    if result <= 0:
                        raise RuntimeError(
                            f'DocumentProperties(DM_IN_BUFFER|DM_OUT_BUFFER) '
                            f'returned failure code {result}'
                        )
                    # Positive int: devmode was modified in-place — keep our reference.
                    # NEVER assign devmode = result here (result is just an int).
                    logger.info('Driver accepted DEVMODE (modified in-place, result=%d)', result)
                elif result is not None and all(
                    hasattr(result, attr) for attr in ('PaperSize', 'PaperWidth', 'PaperLength')
                ):
                    # Some pywin32 builds return a new PyDEVMODE
                    devmode = result
                    logger.info('Driver returned updated PyDEVMODE object')
                elif result is None:
                    raise RuntimeError(
                        'DocumentProperties(DM_IN_BUFFER|DM_OUT_BUFFER) returned None'
                    )
                else:
                    raise RuntimeError(
                        f'DocumentProperties(DM_IN_BUFFER|DM_OUT_BUFFER) returned '
                        f'unexpected object: {result!r}, type={type(result).__name__}'
                    )
            except RuntimeError:
                raise   # re-raise our own errors unchanged
            except Exception as exc:
                # Driver call failed; log and continue with unvalidated devmode
                logger.warning(
                    'DocumentProperties(DM_IN_BUFFER|DM_OUT_BUFFER) raised for %r: %s '
                    '— continuing with unvalidated DEVMODE', printer_name, exc
                )

        # ── 5. Log values AFTER validation ────────────────────────────────────
        actual_w = getattr(devmode, 'PaperWidth',  None)
        actual_l = getattr(devmode, 'PaperLength', None)
        logger.info(
            'After DocumentProperties:\n'
            '  PaperSize:   %s\n'
            '  PaperWidth:  %s\n'
            '  PaperLength: %s\n'
            '  Orientation: %s',
            getattr(devmode, 'PaperSize',   '?'),
            actual_w,
            actual_l,
            getattr(devmode, 'Orientation', '?'),
        )

        accepted = (
            getattr(devmode, 'PaperSize', None) == _DMPAPER_USER
            and actual_w == width_mm  * 10
            and actual_l == height_mm * 10
        )
        logger.info('Accepted by driver: %s', accepted)

        assert_valid_devmode(devmode, 'devmode (return value)')
        return devmode   # always a valid PyDEVMODE here — never None, never int

    finally:
        win32print.ClosePrinter(h)


# ── Create printer DC with per-job DEVMODE ────────────────────────────────────


def _create_printer_dc(printer_name: str, devmode):
    """
    Create a printer device context that reflects the per-job DEVMODE.

    win32gui.CreateDC()'s argument count varies across pywin32 builds:
      - some builds:  CreateDC(Driver, Device, Output, InitData)   (4 args)
      - other builds: CreateDC(Driver, Device, InitData)           (3 args,
        no separate Output parameter — confirmed on pywin32 311).
    Both are tried; whichever matches the installed build succeeds.

    BUG-FIX (historical): the previous call passed devmode as the 3rd
    argument (the port name string), omitting the DEVMODE entirely. pywin32
    raised a TypeError, the except clause fired, and the code fell back
    silently to CreatePrinterDC(printer_name) which ignores our custom
    DEVMODE.

    Falls back to CreatePrinterDC (global settings) if win32gui is unavailable
    or returns a null HDC.
    Returns a (dc, used_custom_devmode) tuple.
    """
    import win32ui

    if devmode is not None and not isinstance(devmode, int):
        try:
            import win32gui
            try:
                hdc = win32gui.CreateDC('WINSPOOL', printer_name, None, devmode)
            except TypeError:
                hdc = win32gui.CreateDC('WINSPOOL', printer_name, devmode)
            if not hdc:
                raise RuntimeError('win32gui.CreateDC returned null HDC')
            dc = win32ui.CreateDCFromHandle(hdc)
            logger.info('GDI printer DC created with custom DEVMODE: True')
            return dc, True
        except Exception as exc:
            logger.warning(
                'win32gui.CreateDC with job DEVMODE failed for %r: %s '
                '— falling back to global-defaults DC',
                printer_name, exc,
            )
    elif isinstance(devmode, int):
        logger.error(
            'devmode is int (%d) — build_job_devmode returned status code instead of '
            'PyDEVMODE; this is a bug. Falling back to global DC.',
            devmode,
        )

    dc = win32ui.CreateDC()
    dc.CreatePrinterDC(printer_name)
    logger.warning(
        'GDI printer DC created with custom DEVMODE: False  '
        '(using global paper size for %r)',
        printer_name,
    )
    return dc, False


# ── Read device capabilities ──────────────────────────────────────────────────


def _read_caps(dc) -> dict:
    """Read all relevant device capabilities from a CDC / HDC-compatible object."""
    import win32con
    caps = {
        'dpi_x'   : dc.GetDeviceCaps(win32con.LOGPIXELSX),
        'dpi_y'   : dc.GetDeviceCaps(win32con.LOGPIXELSY),
        'horzsize': dc.GetDeviceCaps(win32con.HORZSIZE),        # physical width  in mm
        'vertsize': dc.GetDeviceCaps(win32con.VERTSIZE),        # physical height in mm
        'phys_w'  : dc.GetDeviceCaps(win32con.PHYSICALWIDTH),   # px
        'phys_h'  : dc.GetDeviceCaps(win32con.PHYSICALHEIGHT),  # px
        'horzres' : dc.GetDeviceCaps(win32con.HORZRES),         # printable px
        'vertres' : dc.GetDeviceCaps(win32con.VERTRES),         # printable px
        'phys_ox' : dc.GetDeviceCaps(win32con.PHYSICALOFFSETX),
        'phys_oy' : dc.GetDeviceCaps(win32con.PHYSICALOFFSETY),
    }
    logger.info(
        'DC caps — LOGPIXELSX: %d  LOGPIXELSY: %d  '
        'HORZSIZE: %d mm  VERTSIZE: %d mm  '
        'HORZRES: %d px  VERTRES: %d px  '
        'PHYSICALWIDTH: %d px  PHYSICALHEIGHT: %d px  '
        'PHYSICALOFFSETX: %d  PHYSICALOFFSETY: %d',
        caps['dpi_x'],    caps['dpi_y'],
        caps['horzsize'], caps['vertsize'],
        caps['horzres'],  caps['vertres'],
        caps['phys_w'],   caps['phys_h'],
        caps['phys_ox'],  caps['phys_oy'],
    )
    return caps


# ── Compute centered destination rectangle ────────────────────────────────────


def _compute_dest_rect(caps: dict, label_w_px: int, label_h_px: int) -> tuple:
    """
    Center the label raster physically on the DC page.

    In a printer DC:
      - (0,0) is the top-left of the PRINTABLE area.
      - (phys_ox, phys_oy) is where the printable area starts on the physical page.
      - (phys_w, phys_h) is the full physical page size.

    To place the raster at the physical centre of the page:

      dest_x_physical = page_centre_x - label_w_px/2
      dest_y_physical = page_centre_y - label_h_px/2

      dest_x = dest_x_physical - phys_ox   (convert to printable-DC coords)
      dest_y = dest_y_physical - phys_oy
    """
    phys_w  = caps['phys_w']
    phys_h  = caps['phys_h']
    phys_ox = caps['phys_ox']
    phys_oy = caps['phys_oy']

    dest_x_phys = round(phys_w / 2 - label_w_px / 2)
    dest_y_phys = round(phys_h / 2 - label_h_px / 2)

    dest_x = dest_x_phys - phys_ox
    dest_y = dest_y_phys - phys_oy

    logger.info(
        'Centering: page_physical=%dx%d  label=%dx%d  '
        'dest_physical=(%d,%d)  offset=(%d,%d)  dest_dc=(%d,%d)',
        phys_w, phys_h, label_w_px, label_h_px,
        dest_x_phys, dest_y_phys,
        phys_ox, phys_oy,
        dest_x, dest_y,
    )

    return (dest_x, dest_y, dest_x + label_w_px, dest_y + label_h_px)


# ── Debug: collect printer caps via job DEVMODE ───────────────────────────────


def get_printer_caps_with_job_devmode(printer_name: str) -> dict:
    """
    Create a temporary DC using the per-job DEVMODE and return all device caps.
    Used by the /debug-printer endpoint.
    """
    devmode        = build_job_devmode(printer_name)
    dc, _used_custom = _create_printer_dc(printer_name, devmode)
    try:
        caps = _read_caps(dc)
    finally:
        try:
            dc.DeleteDC()
        except Exception:
            pass

    dpi_x   = caps['dpi_x']
    dpi_y   = caps['dpi_y']
    phys_w  = caps['phys_w']
    phys_h  = caps['phys_h']
    horzres = caps['horzres']
    vertres = caps['vertres']
    phys_ox = caps['phys_ox']
    phys_oy = caps['phys_oy']

    job_w  = getattr(devmode, 'PaperWidth',  None) if devmode else None
    job_l  = getattr(devmode, 'PaperLength', None) if devmode else None

    phys_w_mm = _px_to_mm(phys_w, dpi_x)
    phys_h_mm = _px_to_mm(phys_h, dpi_y)

    custom_accepted = (
        devmode is not None
        and abs(phys_w_mm - LABEL_W_MM) < 5
        and abs(phys_h_mm - LABEL_H_MM) < 5
    )

    return {
        'printer_name'      : printer_name,
        'dpi_x'             : dpi_x,
        'dpi_y'             : dpi_y,
        'physical_width_px' : phys_w,
        'physical_height_px': phys_h,
        'physical_width_mm' : phys_w_mm,
        'physical_height_mm': phys_h_mm,
        'printable_width_px': horzres,
        'printable_height_px': vertres,
        'offset_x_px'       : phys_ox,
        'offset_y_px'       : phys_oy,
        'job_paper_width'   : job_w,
        'job_paper_length'  : job_l,
        'custom_size_accepted': custom_accepted,
        'devmode_available' : devmode is not None,
    }


# ── SetPrinter fallback ───────────────────────────────────────────────────────


def print_with_temporary_global_devmode(
    printer_name: str,
    product_name: str,
    price,
    copies: int,
    paper_size: str,
) -> dict:
    """
    Fallback print path for drivers that ignore per-job DEVMODE (e.g. Xprinter XP-365B).

    Flow:
      1. Open printer with PRINTER_ALL_ACCESS.
      2. Read and save the current global DEVMODE (original_devmode).
      3. Build a validated modified DEVMODE for the selected paper size.
      4. SetPrinter — temporarily write the new size to global settings.
      5. CreatePrinterDC — picks up the new global settings.
      6. Render and print all copies.
      7. ALWAYS restore original_devmode in the inner finally.
      8. Close printer handle in the outer finally.

    The two nested try/finally blocks guarantee restoration even if printing
    raises an exception before the restore code is reached.
    """
    try:
        import win32print
        import win32ui
        from PIL import ImageWin
    except ImportError as exc:
        raise RuntimeError('Диспетчер печати Windows недоступен') from exc

    logger.info('=== BotaPrint SetPrinter fallback ===')
    logger.info('Selected size key: %s', paper_size)

    # ── Resolve paper size from centralized config ────────────────────────────
    if paper_size not in SUPPORTED_LABEL_SIZES:
        logger.warning('Unknown paper_size %r in fallback — using %r', paper_size, DEFAULT_LABEL_SIZE)
        paper_size = DEFAULT_LABEL_SIZE
    dims      = SUPPORTED_LABEL_SIZES[paper_size]
    width_mm  = dims['width_mm']
    height_mm = dims['height_mm']

    logger.info('Requested mm: %dx%d', width_mm, height_mm)
    logger.info('Requested PaperWidth/PaperLength: %d/%d (tenths of mm)',
                width_mm * 10, height_mm * 10)

    # ── Open printer with write access ────────────────────────────────────────
    hprinter = win32print.OpenPrinter(
        printer_name,
        {'DesiredAccess': win32print.PRINTER_ALL_ACCESS},
    )
    try:
        info             = win32print.GetPrinter(hprinter, 2)
        original_devmode = info['pDevMode']          # reference to the original PyDEVMODE
        logger.info(
            'Original DEVMODE: PaperSize=%s  PaperWidth=%s  PaperLength=%s',
            getattr(original_devmode, 'PaperSize',   '?'),
            getattr(original_devmode, 'PaperWidth',  '?'),
            getattr(original_devmode, 'PaperLength', '?'),
        )

        try:
            # ── Build validated modified DEVMODE ──────────────────────────────
            # build_job_devmode opens its own handle (read-only) so it is safe
            # to call while hprinter is open with PRINTER_ALL_ACCESS.
            # Any failure raises RuntimeError with the real cause — never None.
            try:
                modified_devmode = build_job_devmode(
                    printer_name, width_mm=width_mm, height_mm=height_mm
                )
            except Exception as exc:
                logger.exception('Failed to build temporary global DEVMODE for %r', printer_name)
                raise RuntimeError(f'Failed to build printer DEVMODE: {exc}') from exc

            logger.info(
                'Modified DEVMODE after DocumentProperties: '
                'PaperSize=%s  PaperWidth=%s  PaperLength=%s',
                getattr(modified_devmode, 'PaperSize',   '?'),
                getattr(modified_devmode, 'PaperWidth',  '?'),
                getattr(modified_devmode, 'PaperLength', '?'),
            )

            # ── Apply to global printer settings ──────────────────────────────
            assert_valid_devmode(modified_devmode, 'modified_devmode')
            info['pDevMode'] = modified_devmode
            win32print.SetPrinter(hprinter, 2, info, 0)
            logger.info('SetPrinter applied successfully')

            global_check = win32print.GetPrinter(hprinter, 2).get('pDevMode')
            logger.info(
                'Global DEVMODE after SetPrinter: PaperSize=%s  PaperWidth=%s  PaperLength=%s',
                getattr(global_check, 'PaperSize',   '?'),
                getattr(global_check, 'PaperWidth',  '?'),
                getattr(global_check, 'PaperLength', '?'),
            )

            # ── Create DC — now uses the updated global settings ──────────────
            printer_dc = win32ui.CreateDC()
            printer_dc.CreatePrinterDC(printer_name)
            logger.info('Printing started')

            try:
                caps      = _read_caps(printer_dc)
                dpi_x     = caps['dpi_x']
                dpi_y     = caps['dpi_y']

                phys_w_mm = _px_to_mm(caps['phys_w'], dpi_x)
                phys_h_mm = _px_to_mm(caps['phys_h'], dpi_y)
                logger.info(
                    'DC after SetPrinter: physical=%.1fx%.1f mm  '
                    'printable=%dx%d px  DPI=%dx%d',
                    phys_w_mm, phys_h_mm,
                    caps['horzres'], caps['vertres'],
                    dpi_x, dpi_y,
                )

                # Image size from selected calibrated dimensions, never from DC caps
                label_w_px = round(width_mm  / 25.4 * dpi_x)
                label_h_px = round(height_mm / 25.4 * dpi_y)
                logger.info('Label raster: %dx%d px  (%dx%d mm)',
                            label_w_px, label_h_px, width_mm, height_mm)

                img       = render_label_image(
                    product_name, price, label_w_px, label_h_px,
                    dpi=min(dpi_x, dpi_y), paper_size=paper_size,
                )
                dest_rect = _compute_dest_rect(caps, label_w_px, label_h_px)
                dib       = ImageWin.Dib(img)

                doc_started = False
                try:
                    printer_dc.StartDoc('BotaPrint Label')
                    doc_started = True
                    for i in range(copies):
                        printer_dc.StartPage()
                        dib.draw(printer_dc.GetSafeHdc(), dest_rect)
                        printer_dc.EndPage()
                        logger.debug('Printed copy %d/%d', i + 1, copies)
                    printer_dc.EndDoc()
                    logger.info('Print job completed: %d cop%s to %r',
                                copies, 'y' if copies == 1 else 'ies', printer_name)
                except Exception as exc:
                    if doc_started:
                        try:
                            printer_dc.AbortDoc()
                        except Exception:
                            pass
                    logger.error('Print job failed for %r: %s', printer_name, exc)
                    raise RuntimeError('Ошибка отправки задания на печать') from exc

            finally:
                try:
                    printer_dc.DeleteDC()
                except Exception:
                    pass

        finally:
            # ── ALWAYS restore original global DEVMODE ────────────────────────
            logger.info('Restoring original DEVMODE')
            try:
                assert_valid_devmode(original_devmode, 'original_devmode')
                info['pDevMode'] = original_devmode
                win32print.SetPrinter(hprinter, 2, info, 0)
                logger.info('Original DEVMODE restored successfully')
            except Exception as exc:
                logger.critical(
                    'FAILED to restore original printer DEVMODE for %r: %s',
                    printer_name, exc,
                )
            logger.info('====================================')

    finally:
        win32print.ClosePrinter(hprinter)

    return {
        'success'         : True,
        'copies'          : copies,
        'printer'         : printer_name,
        'paper_size'      : paper_size,
        'mode'            : 'setprinter_fallback',
        'dpi_x'           : dpi_x,
        'dpi_y'           : dpi_y,
        'label_w_px'      : label_w_px,
        'label_h_px'      : label_h_px,
        'dest_rect'       : list(dest_rect),
        'custom_accepted' : True,    # forced via SetPrinter
        'global_unchanged': False,   # changed then restored
    }


# ── Core print function ───────────────────────────────────────────────────────


def print_label(printer_name: str, product_name: str, price,
                copies: int = 1,
                paper_size: str = DEFAULT_LABEL_SIZE) -> dict:
    """
    Render a label and send it directly to the Windows printer.

    paper_size must be a key from SUPPORTED_LABEL_SIZES (e.g. "43x25").
    Falls back to DEFAULT_LABEL_SIZE if the key is missing or invalid.

    Per-job workflow (global settings UNCHANGED):
      1. build_job_devmode()  — per-job DEVMODE with selected dimensions (no SetPrinter)
      2. _create_printer_dc() — DC via win32gui.CreateDC with that DEVMODE
      3. Read device caps from the job DC
      4. render_label_image() — Pillow raster at selected dimensions
      5. _compute_dest_rect() — physically centred destination
      6. ImageWin.Dib.draw()  — blit to printer DC

    Raises RuntimeError (Russian message) on failure.
    """
    try:
        import win32ui
        import win32con
        from PIL import ImageWin
    except ImportError as exc:
        raise RuntimeError('Диспетчер печати Windows недоступен') from exc

    # ── 0. Resolve paper size ─────────────────────────────────────────────────
    if paper_size not in SUPPORTED_LABEL_SIZES:
        logger.warning('Unknown paper_size %r — falling back to %r', paper_size, DEFAULT_LABEL_SIZE)
        paper_size = DEFAULT_LABEL_SIZE
    dims       = SUPPORTED_LABEL_SIZES[paper_size]
    label_w_mm = dims['width_mm']
    label_h_mm = dims['height_mm']

    logger.info(
        'Selected paper size: %s\n'
        '  Requested width mm:    %d\n'
        '  Requested height mm:   %d\n'
        '  Requested PaperWidth:  %d  (tenths of mm)\n'
        '  Requested PaperLength: %d  (tenths of mm)',
        paper_size, label_w_mm, label_h_mm,
        label_w_mm * 10, label_h_mm * 10,
    )

    # ── 1. Verify printer ─────────────────────────────────────────────────────
    known = {p['name'] for p in list_printers()}
    if printer_name not in known:
        raise RuntimeError('Принтер не найден')

    logger.info('=== BotaPrint job: printer=%r product=%r copies=%d size=%s ===',
                printer_name, product_name, copies, paper_size)

    # ── 1a. Route to SetPrinter fallback if enabled ───────────────────────────
    if ENABLE_TEMP_GLOBAL_PRINTER_SIZE_FALLBACK:
        return print_with_temporary_global_devmode(
            printer_name=printer_name,
            product_name=product_name,
            price=price,
            copies=copies,
            paper_size=paper_size,
        )

    # ── 2. Read global DEVMODE BEFORE printing (for post-check) ──────────────
    global_before = read_global_devmode(printer_name)
    logger.info('Global DEVMODE before: %s', global_before)

    # ── 3. Build per-job DEVMODE ──────────────────────────────────────────────
    devmode = build_job_devmode(printer_name, width_mm=label_w_mm, height_mm=label_h_mm)

    # ── 4. Create printer DC with per-job DEVMODE ─────────────────────────────
    try:
        printer_dc, used_custom_devmode = _create_printer_dc(printer_name, devmode)
    except Exception as exc:
        raise RuntimeError('Не удалось создать контекст печати') from exc

    try:
        # ── 5. Read device caps from the job DC ───────────────────────────────
        caps    = _read_caps(printer_dc)
        dpi_x   = caps['dpi_x']
        dpi_y   = caps['dpi_y']
        phys_w  = caps['phys_w']
        phys_h  = caps['phys_h']
        horzres = caps['horzres']
        vertres = caps['vertres']
        phys_ox = caps['phys_ox']
        phys_oy = caps['phys_oy']

        phys_w_mm = _px_to_mm(phys_w, dpi_x)
        phys_h_mm = _px_to_mm(phys_h, dpi_y)

        logger.info(
            'Job DC caps: DPI=%dx%d  physical=%dx%dpx (%.1fx%.1fmm)  '
            'printable=%dx%dpx  offset=%dx%dpx',
            dpi_x, dpi_y,
            phys_w, phys_h, phys_w_mm, phys_h_mm,
            horzres, vertres,
            phys_ox, phys_oy,
        )

        # Check whether the DC actually reports the requested physical size
        custom_accepted = (
            used_custom_devmode
            and abs(phys_w_mm - label_w_mm) < 5
            and abs(phys_h_mm - label_h_mm) < 5
        )
        if custom_accepted:
            logger.info('DC confirms custom %dx%d mm paper size for this job',
                        label_w_mm, label_h_mm)
        else:
            logger.warning(
                'DC reports %.1fx%.1f mm — requested %dx%d mm  '
                '(used_custom_devmode=%s). '
                'Will render correct-size raster and centre on physical page.',
                phys_w_mm, phys_h_mm, label_w_mm, label_h_mm, used_custom_devmode,
            )

        # ── 6. Label raster dimensions from selected paper size ───────────────
        # Always computed from selected dimensions — never from PHYSICALWIDTH/HEIGHT.
        label_w_px = round(label_w_mm / 25.4 * dpi_x)
        label_h_px = round(label_h_mm / 25.4 * dpi_y)

        logger.info('Label raster: %dx%d px  (%dx%d mm at %dx%d DPI)',
                    label_w_px, label_h_px, label_w_mm, label_h_mm, dpi_x, dpi_y)

        # ── 7. Orientation check ───────────────────────────────────────────────
        # If the driver swapped dimensions (portrait DC but landscape label),
        # rotate the raster 90° rather than fighting the DEVMODE again.
        raster_rotated = False
        if phys_w < phys_h and label_w_px > label_h_px and custom_accepted:
            logger.info(
                'Orientation: DC is portrait (%d<%d) but label is landscape (%d>%d) '
                '— rotating raster 90°',
                phys_w, phys_h, label_w_px, label_h_px,
            )
            label_w_px, label_h_px = label_h_px, label_w_px
            raster_rotated = True

        # ── 8. Render Pillow image ─────────────────────────────────────────────
        try:
            img = render_label_image(
                product_name, price, label_w_px, label_h_px,
                dpi=min(dpi_x, dpi_y), paper_size=paper_size,
            )
            if raster_rotated:
                img = img.rotate(90, expand=True)
        except Exception as exc:
            logger.error('render_label_image failed: %s', exc)
            raise RuntimeError('Не удалось сформировать изображение этикетки') from exc

        # ── 9. Compute centered destination rectangle ──────────────────────────
        dest_rect = _compute_dest_rect(caps, label_w_px, label_h_px)
        logger.info('Destination rect in DC coords: %s', dest_rect)

        # ── 10. Print all copies ───────────────────────────────────────────────
        dib         = ImageWin.Dib(img)
        doc_started = False
        try:
            printer_dc.StartDoc('BotaPrint Label')
            doc_started = True

            for copy_idx in range(copies):
                printer_dc.StartPage()
                dib.draw(printer_dc.GetSafeHdc(), dest_rect)
                printer_dc.EndPage()
                logger.debug('Printed copy %d/%d', copy_idx + 1, copies)

            printer_dc.EndDoc()
            logger.info('Print job completed: %d cop%s to %r',
                        copies, 'y' if copies == 1 else 'ies', printer_name)
        except Exception as exc:
            if doc_started:
                try:
                    printer_dc.AbortDoc()
                except Exception:
                    pass
            logger.error('Print job failed for %r: %s', printer_name, exc)
            raise RuntimeError('Ошибка отправки задания на печать') from exc

    finally:
        try:
            printer_dc.DeleteDC()
        except Exception:
            pass

    # ── 11. Verify global settings unchanged ──────────────────────────────────
    global_after = read_global_devmode(printer_name)
    logger.info('Global DEVMODE after:  %s', global_after)
    if global_before and global_after and global_before != global_after:
        logger.error(
            'GLOBAL DEVMODE CHANGED after BotaPrint job! before=%s after=%s',
            global_before, global_after,
        )
    else:
        logger.info('Global DEVMODE unchanged — OK')

    return {
        'success'         : True,
        'copies'          : copies,
        'printer'         : printer_name,
        'dpi_x'           : dpi_x,
        'dpi_y'           : dpi_y,
        'label_w_px'      : label_w_px,
        'label_h_px'      : label_h_px,
        'dest_rect'       : list(dest_rect),
        'custom_accepted'    : custom_accepted,
        'used_custom_devmode': used_custom_devmode,
        'raster_rotated'     : raster_rotated,
        'global_unchanged'   : global_before == global_after,
    }
