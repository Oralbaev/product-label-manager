"""
debug_setprinter_fallback.py — BotaPrint SetPrinter fallback self-test.

Run:
    py debug_setprinter_fallback.py

Steps:
  1. Open Xprinter XP-365B with PRINTER_ALL_ACCESS.
  2. Save the original global DEVMODE.
  3. Build+apply a test DEVMODE for size 43x25 via SetPrinter.
  4. Read back GetPrinter() and verify PaperWidth/PaperLength changed.
  5. Restore the original DEVMODE in `finally`.
  6. Read back GetPrinter() again and verify the restore succeeded.

This script temporarily changes global printer settings but always restores
them. It does NOT print anything.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

TARGET_PRINTER = 'Xprinter XP-365B'
TEST_SIZE_KEY = '43x25'


def snapshot(devmode) -> dict:
    return {
        'PaperSize'  : getattr(devmode, 'PaperSize',   None),
        'PaperWidth' : getattr(devmode, 'PaperWidth',  None),
        'PaperLength': getattr(devmode, 'PaperLength', None),
    }


def main() -> int:
    try:
        import win32print
    except ImportError as exc:
        print(f'FATAL: pywin32 not available: {exc}')
        return 1

    from botaprint import printing
    from botaprint.paper_sizes import SUPPORTED_LABEL_SIZES

    if TEST_SIZE_KEY not in SUPPORTED_LABEL_SIZES:
        print(f'FATAL: {TEST_SIZE_KEY!r} not in SUPPORTED_LABEL_SIZES')
        return 1
    dims = SUPPORTED_LABEL_SIZES[TEST_SIZE_KEY]
    width_mm, height_mm = dims['width_mm'], dims['height_mm']

    print('=' * 70)
    print(f'BotaPrint SetPrinter fallback self-test — {TARGET_PRINTER!r}')
    print(f'Test size: {TEST_SIZE_KEY} ({width_mm}x{height_mm} mm)')
    print('=' * 70)

    names = {p['name'] for p in printing.list_printers()}
    if TARGET_PRINTER not in names:
        print(f'FATAL: target printer {TARGET_PRINTER!r} not found.')
        return 1

    ok = True
    restored_ok = False

    hprinter = win32print.OpenPrinter(
        TARGET_PRINTER, {'DesiredAccess': win32print.PRINTER_ALL_ACCESS}
    )
    try:
        info = win32print.GetPrinter(hprinter, 2)
        original_devmode = info['pDevMode']
        printing.assert_valid_devmode(original_devmode, 'original_devmode')
        original_snapshot = snapshot(original_devmode)
        print(f'Original DEVMODE: {original_snapshot}')

        try:
            # ── Build + apply test DEVMODE ──────────────────────────────────
            try:
                modified_devmode = printing.build_job_devmode(
                    TARGET_PRINTER, width_mm=width_mm, height_mm=height_mm
                )
                printing.assert_valid_devmode(modified_devmode, 'modified_devmode')
            except Exception as exc:
                print(f'FAIL: build_job_devmode raised: {exc!r}')
                return 1

            print(f'Modified DEVMODE (pre-SetPrinter): {snapshot(modified_devmode)}')

            info['pDevMode'] = modified_devmode
            win32print.SetPrinter(hprinter, 2, info, 0)
            print('SetPrinter applied.')

            # ── Verify global settings actually changed ─────────────────────
            info_after = win32print.GetPrinter(hprinter, 2)
            dm_after   = info_after['pDevMode']
            after_snapshot = snapshot(dm_after)
            print(f'Global DEVMODE after SetPrinter: {after_snapshot}')

            expected_w = width_mm * 10
            expected_l = height_mm * 10
            changed = (after_snapshot['PaperWidth'] == expected_w
                       and after_snapshot['PaperLength'] == expected_l)
            print(f'Global PaperWidth/PaperLength changed as expected: {changed}')
            if not changed:
                ok = False

        finally:
            # ── ALWAYS restore original DEVMODE ──────────────────────────────
            print('Restoring original DEVMODE...')
            try:
                printing.assert_valid_devmode(original_devmode, 'original_devmode')
                info['pDevMode'] = original_devmode
                win32print.SetPrinter(hprinter, 2, info, 0)

                info_restored = win32print.GetPrinter(hprinter, 2)
                restored_snapshot = snapshot(info_restored['pDevMode'])
                print(f'Global DEVMODE after restore: {restored_snapshot}')

                restored_ok = (
                    restored_snapshot['PaperWidth']  == original_snapshot['PaperWidth']
                    and restored_snapshot['PaperLength'] == original_snapshot['PaperLength']
                )
                print(f'Restore verified: {restored_ok}')
                if not restored_ok:
                    ok = False
            except Exception as exc:
                print(f'CRITICAL: restore failed: {exc!r}')
                ok = False

    finally:
        win32print.ClosePrinter(hprinter)

    print('=' * 70)
    print('RESULT:', 'OK' if ok else 'FAILED')
    print('=' * 70)
    print('No print job was sent.')
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
