"""
debug_printer_sizes.py — BotaPrint self-test (no real print job).

Run:
    py debug_printer_sizes.py

For each test size (30x20, 43x25, 58x40):
  1. Build a per-job DEVMODE via botaprint.printing.build_job_devmode().
  2. Print the DocumentProperties() result type/value.
  3. Verify PaperWidth/PaperLength on the returned DEVMODE.
  4. Create a printer DC with win32gui.CreateDC(..., devmode) (per-job DEVMODE).
  5. Print GDI device caps: HORZSIZE, VERTSIZE, HORZRES, VERTRES,
     PHYSICALWIDTH, PHYSICALHEIGHT, PHYSICALOFFSETX, PHYSICALOFFSETY,
     LOGPIXELSX, LOGPIXELSY.

Does NOT send anything to the printer.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

TARGET_PRINTER = 'Xprinter XP-365B'
TEST_SIZES = ['30x20', '43x25', '58x40']


def main() -> int:
    try:
        import win32con
        import win32gui
        import win32print
        import win32ui
    except ImportError as exc:
        print(f'FATAL: pywin32 not available: {exc}')
        return 1

    from botaprint import printing
    from botaprint.paper_sizes import SUPPORTED_LABEL_SIZES

    print('=' * 70)
    print('BotaPrint debug: printer enumeration')
    print('=' * 70)
    printers = printing.list_printers()
    if not printers:
        print('No printers found (EnumPrinters returned nothing).')
        return 1
    for p in printers:
        marker = ' [default]' if p['is_default'] else ''
        print(f"  - {p['name']}{marker}")

    names = {p['name'] for p in printers}
    if TARGET_PRINTER not in names:
        print(f'\nFATAL: target printer {TARGET_PRINTER!r} not found among installed printers.')
        return 1
    print(f'\nTarget printer found: {TARGET_PRINTER!r}')

    overall_ok = True

    for size_key in TEST_SIZES:
        print()
        print('=' * 70)
        print(f'Testing size: {size_key}')
        print('=' * 70)

        if size_key not in SUPPORTED_LABEL_SIZES:
            print(f'  SKIP: {size_key!r} not in SUPPORTED_LABEL_SIZES')
            overall_ok = False
            continue

        dims = SUPPORTED_LABEL_SIZES[size_key]
        width_mm, height_mm = dims['width_mm'], dims['height_mm']
        print(f'  Requested: {width_mm}x{height_mm} mm '
              f'(PaperWidth={width_mm * 10}, PaperLength={height_mm * 10} tenths-mm)')

        # ── Build per-job DEVMODE ──────────────────────────────────────────
        try:
            devmode = printing.build_job_devmode(
                TARGET_PRINTER, width_mm=width_mm, height_mm=height_mm
            )
        except Exception as exc:
            print(f'  FAIL: build_job_devmode raised: {exc!r}')
            overall_ok = False
            continue

        result_type = type(devmode).__name__
        print(f'  build_job_devmode() returned type={result_type}')

        try:
            printing.assert_valid_devmode(devmode, 'devmode')
        except Exception as exc:
            print(f'  FAIL: assert_valid_devmode: {exc}')
            overall_ok = False
            continue

        actual_w = getattr(devmode, 'PaperWidth', None)
        actual_l = getattr(devmode, 'PaperLength', None)
        print(f'  DEVMODE.PaperSize   = {getattr(devmode, "PaperSize", "?")}')
        print(f'  DEVMODE.PaperWidth  = {actual_w}  (expected {width_mm * 10})')
        print(f'  DEVMODE.PaperLength = {actual_l}  (expected {height_mm * 10})')

        size_accepted = (actual_w == width_mm * 10 and actual_l == height_mm * 10)
        print(f'  Driver accepted requested size: {size_accepted}')
        if not size_accepted:
            overall_ok = False

        # ── Create per-job printer DC ──────────────────────────────────────
        # win32gui.CreateDC's arg count varies by pywin32 build: try the
        # 4-arg form (Driver, Device, Output, InitData) first, fall back to
        # the 3-arg form (Driver, Device, InitData) used by pywin32 311.
        try:
            try:
                hdc = win32gui.CreateDC('WINSPOOL', TARGET_PRINTER, None, devmode)
            except TypeError:
                hdc = win32gui.CreateDC('WINSPOOL', TARGET_PRINTER, devmode)
            if not hdc:
                raise RuntimeError('CreateDC returned null HDC')
            dc = win32ui.CreateDCFromHandle(hdc)
        except Exception as exc:
            print(f'  FAIL: CreateDC with per-job DEVMODE failed: {exc!r}')
            overall_ok = False
            continue

        try:
            caps = {
                'HORZSIZE'       : dc.GetDeviceCaps(win32con.HORZSIZE),
                'VERTSIZE'       : dc.GetDeviceCaps(win32con.VERTSIZE),
                'HORZRES'        : dc.GetDeviceCaps(win32con.HORZRES),
                'VERTRES'        : dc.GetDeviceCaps(win32con.VERTRES),
                'PHYSICALWIDTH'  : dc.GetDeviceCaps(win32con.PHYSICALWIDTH),
                'PHYSICALHEIGHT' : dc.GetDeviceCaps(win32con.PHYSICALHEIGHT),
                'PHYSICALOFFSETX': dc.GetDeviceCaps(win32con.PHYSICALOFFSETX),
                'PHYSICALOFFSETY': dc.GetDeviceCaps(win32con.PHYSICALOFFSETY),
                'LOGPIXELSX'     : dc.GetDeviceCaps(win32con.LOGPIXELSX),
                'LOGPIXELSY'     : dc.GetDeviceCaps(win32con.LOGPIXELSY),
            }
            print('  GDI device caps:')
            for k, v in caps.items():
                print(f'    {k:16s} = {v}')
        finally:
            try:
                dc.DeleteDC()
            except Exception:
                pass

    print()
    print('=' * 70)
    print('RESULT:', 'ALL SIZES OK' if overall_ok else 'SOME CHECKS FAILED (see above)')
    print('=' * 70)
    print('No print job was sent.')
    return 0 if overall_ok else 2


if __name__ == '__main__':
    sys.exit(main())
