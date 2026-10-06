#!/usr/bin/env python
"""
Verify that the real label endpoint returns a PDF with the correct fixed size.

Fixed label size: 43 mm x 25 mm.

Expected MediaBox:
  width  ~= 121.89 pt  (43 mm)
  height ~=  70.87 pt  (25 mm)

Usage (from project root):
    python scripts/check_label_sizes.py

Requirements:
    pip install pypdf
"""

import io
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

try:
    from pypdf import PdfReader
except ImportError:
    print('ERROR: pypdf not installed.  Run: pip install pypdf')
    sys.exit(1)

from django.test import RequestFactory
from shop.views import print_label
from shop.models import ProductVariant
from shop.label_service import LABEL_W_MM, LABEL_H_MM

PT_TO_MM  = 25.4 / 72.0
TOLERANCE = 0.5   # mm


def main() -> None:
    variant = ProductVariant.objects.select_related('product').first()
    if not variant:
        print('ERROR: No products in database. Create a product first.')
        sys.exit(1)

    rf = RequestFactory()
    print()
    print(f'Fixed label size: {LABEL_W_MM} x {LABEL_H_MM} mm')
    print(f'Testing variant : id={variant.id}  barcode={variant.barcode}')
    print()

    all_ok = True

    for copies in (1, 3, 5):
        req  = rf.get(f'/products/{variant.id}/label/', {'count': str(copies)})
        resp = print_label(req, variant.id)

        if resp.status_code != 200:
            print(f'copies={copies}: HTTP {resp.status_code} -- FAIL')
            all_ok = False
            continue

        reader  = PdfReader(io.BytesIO(resp.content))
        n_pages = len(reader.pages)
        page    = reader.pages[0]
        w_mm    = float(page.mediabox.width)  * PT_TO_MM
        h_mm    = float(page.mediabox.height) * PT_TO_MM
        w_pt    = float(page.mediabox.width)
        h_pt    = float(page.mediabox.height)

        size_ok  = abs(w_mm - LABEL_W_MM) < TOLERANCE and abs(h_mm - LABEL_H_MM) < TOLERANCE
        pages_ok = n_pages == copies
        is_a4    = w_mm > 200 or h_mm > 200

        ok = size_ok and pages_ok and not is_a4
        if not ok:
            all_ok = False

        issues = []
        if is_a4:
            issues.append('IS A4!')
        elif not size_ok:
            issues.append(f'expected {LABEL_W_MM}x{LABEL_H_MM}mm got {w_mm:.2f}x{h_mm:.2f}mm')
        if not pages_ok:
            issues.append(f'expected {copies} pages, got {n_pages}')

        result = 'OK' if ok else ('FAIL: ' + '; '.join(issues))
        print(
            f'  count={copies}:  pages={n_pages}  '
            f'size={w_mm:.2f}x{h_mm:.2f}mm  ({w_pt:.2f}x{h_pt:.2f}pt)  {result}'
        )

    print()
    if all_ok:
        print('All checks passed. Label is 43x25mm, not A4.')
    else:
        print('FAILURES found. Restart the Django server and re-run.')
        sys.exit(1)


if __name__ == '__main__':
    main()
