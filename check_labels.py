#!/usr/bin/env python
"""
Проверка размеров страниц PDF-этикеток.

Запуск из корня проекта:
    python check_labels.py

Для каждого поддерживаемого размера бумаги генерирует PDF,
читает MediaBox и проверяет, что размер совпадает с ожидаемым.
Также проверяет, что количество страниц = count (по умолчанию 2).

Требует: pip install pypdf
"""
import io
import os
import sys

# ── Django setup ──────────────────────────────────────────────────────────────
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from shop.label_service import generate_label_pdf, VALID_PAPER_SIZES

# ── pypdf ──────────────────────────────────────────────────────────────────────
try:
    from pypdf import PdfReader
except ImportError:
    print("pypdf не установлен. Установите: pip install pypdf")
    sys.exit(1)

# ── Fake variant (no DB needed) ───────────────────────────────────────────────
class _FakeProduct:
    name = 'Куртка детская зимняя'

class _FakeVariant:
    product       = _FakeProduct()
    selling_price = 12500
    barcode       = '2000000001'

_variant = _FakeVariant()
COPIES   = 2   # how many pages to generate per test


def check_all() -> bool:
    """Generate a PDF for each size, verify MediaBox and page count."""
    PT_PER_INCH = 72.0
    MM_PER_INCH = 25.4
    PT_TO_MM    = MM_PER_INCH / PT_PER_INCH  # ≈ 0.3528

    header = (
        f"{'Размер':<10}  "
        f"{'Ожид. Ш':>9}  {'Ожид. В':>9}  "
        f"{'Факт. Ш':>9}  {'Факт. В':>9}  "
        f"{'Стр.':>5}  Статус"
    )
    print(header)
    print('-' * len(header))

    all_ok = True
    for size_str in sorted(VALID_PAPER_SIZES):
        exp_w, exp_h = VALID_PAPER_SIZES[size_str]

        try:
            pdf_bytes = generate_label_pdf(_variant, count=COPIES, paper_size=size_str)
        except Exception as exc:
            print(f"  {size_str:<10}  ОШИБКА генерации: {exc}")
            all_ok = False
            continue

        reader  = PdfReader(io.BytesIO(pdf_bytes))
        n_pages = len(reader.pages)
        page    = reader.pages[0]

        # MediaBox dimensions in mm
        # PDF internal unit = 1/72 inch  →  * 25.4 / 72 = mm
        actual_w = float(page.mediabox.width)  * PT_TO_MM
        actual_h = float(page.mediabox.height) * PT_TO_MM

        size_ok  = abs(actual_w - exp_w) < 0.5 and abs(actual_h - exp_h) < 0.5
        pages_ok = n_pages == COPIES
        ok       = size_ok and pages_ok

        if not ok:
            all_ok = False

        status = 'OK' if ok else 'OSHIBKA'
        issues = []
        if not size_ok:
            issues.append(f'размер: ожид {exp_w}×{exp_h} мм, факт {actual_w:.2f}×{actual_h:.2f} мм')
        if not pages_ok:
            issues.append(f'страниц: ожид {COPIES}, факт {n_pages}')

        detail = '  ← ' + '; '.join(issues) if issues else ''

        print(
            f"  {size_str:<10}  "
            f"{exp_w:>7.2f} мм  {exp_h:>7.2f} мм  "
            f"{actual_w:>7.2f} мм  {actual_h:>7.2f} мм  "
            f"{n_pages:>5}  {status}{detail}"
        )

    return all_ok


def main() -> None:
    print()
    print('BotaLabel — проверка размеров PDF-этикеток')
    print(f'Тест: {COPIES} копии для каждого размера')
    print()

    ok = check_all()

    print()
    if ok:
        print('Все размеры корректны. A4 не обнаружен.')
        print()
        print('Совет: если PDF выглядит как A4 в браузере — это браузер масштабирует')
        print('маленькую страницу под экран. Реальный размер MediaBox правильный.')
    else:
        print('ОШИБКИ: проверьте вывод выше.')
        sys.exit(1)


if __name__ == '__main__':
    main()
