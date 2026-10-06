"""
BotaPrint unit tests.

Run from the project root:
    python -m pytest botaprint/tests.py -v
or:
    python botaprint/tests.py

Tests that require a physical printer are skipped automatically.
Windows GDI calls are mocked so the tests run on any OS.
"""

import sys
import os
import io
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow imports from botaprint/ regardless of working directory
sys.path.insert(0, str(Path(__file__).parent))

import printing


# ── Price formatting ──────────────────────────────────────────────────────────


class TestFormatPrice(unittest.TestCase):
    def test_round_number(self):
        self.assertEqual(printing._format_price(3000), '3 000 ₸')

    def test_thousands(self):
        self.assertEqual(printing._format_price(12500), '12 500 ₸')

    def test_decimal_input(self):
        self.assertEqual(printing._format_price(Decimal('3000.00')), '3 000 ₸')

    def test_zero(self):
        self.assertEqual(printing._format_price(0), '0 ₸')

    def test_large(self):
        self.assertEqual(printing._format_price(1000000), '1 000 000 ₸')

    def test_float_rounds_down(self):
        # Only integer part used
        self.assertEqual(printing._format_price(3000.99), '3 000 ₸')


# ── Label image rendering ─────────────────────────────────────────────────────


class TestRenderLabelImage(unittest.TestCase):
    """render_label_image uses only Pillow — no Windows calls needed."""

    DPI = 203

    @classmethod
    def _expected_size(cls):
        w = round(printing.LABEL_W_MM / 25.4 * cls.DPI)   # 344
        h = round(printing.LABEL_H_MM / 25.4 * cls.DPI)   # 200
        return w, h

    def _render(self, name='Тест', price=3000):
        w, h = self._expected_size()
        return printing.render_label_image(name, price, w, h, dpi=self.DPI)

    def test_dimensions_203dpi(self):
        img = self._render()
        self.assertEqual(img.size, self._expected_size())

    def test_dimensions_close_to_344x200(self):
        w, h = self._expected_size()
        self.assertAlmostEqual(w, 344, delta=2)
        self.assertAlmostEqual(h, 200, delta=2)

    def test_white_background(self):
        img = self._render()
        # All four corners must be white
        for corner in [(0, 0), (img.width - 1, 0), (0, img.height - 1),
                       (img.width - 1, img.height - 1)]:
            self.assertEqual(img.getpixel(corner), (255, 255, 255),
                             f'Corner {corner} is not white')

    def test_has_black_pixels(self):
        img = self._render('А', 1)
        # Sample a grid of pixels instead of loading all via deprecated getdata()
        found_dark = any(
            img.getpixel((x, y))[0] < 200
            for y in range(0, img.height, 4)
            for x in range(0, img.width, 4)
        )
        self.assertTrue(found_dark, 'No dark pixels found — text not rendered')

    def test_rgb_mode(self):
        img = self._render()
        self.assertEqual(img.mode, 'RGB')

    def test_cyrillic_name(self):
        # Must not raise
        img = self._render(name='Куртка детская зимняя', price=12500)
        self.assertEqual(img.size, self._expected_size())

    def test_long_name_wraps(self):
        # Should not raise even for a very long name
        img = self._render(name='Очень длинное название товара которое не помещается', price=500)
        self.assertEqual(img.size, self._expected_size())

    def test_price_thousands(self):
        img = self._render(name='Товар', price=12500)
        self.assertEqual(img.size, self._expected_size())


# ── Text wrapping ─────────────────────────────────────────────────────────────


class TestWrapText(unittest.TestCase):
    def setUp(self):
        from PIL import Image, ImageDraw, ImageFont
        img         = Image.new('RGB', (500, 200), 'white')
        self.draw   = ImageDraw.Draw(img)
        self.font   = printing._load_font(10, 96)

    def test_short_text_single_line(self):
        lines = printing.wrap_text(self.draw, 'Футболка', self.font, max_width=400)
        self.assertEqual(len(lines), 1)

    def test_long_text_wraps(self):
        lines = printing.wrap_text(
            self.draw,
            'Очень длинное название которое не влезет в одну строку',
            self.font,
            max_width=100,
        )
        self.assertGreater(len(lines), 1)

    def test_empty_text(self):
        lines = printing.wrap_text(self.draw, '', self.font, max_width=200)
        self.assertEqual(lines, [''])


# ── Request validation (via main.py) ─────────────────────────────────────────


class TestPrintRequest(unittest.TestCase):
    """Validate Pydantic schema accepts correct requests and rejects bad ones."""

    def setUp(self):
        # Import here so missing fastapi doesn't break other tests
        from main import PrintRequest
        self.model = PrintRequest

    def _make(self, **kwargs):
        defaults = dict(printer_name='Printer', product_name='Товар', price=3000, copies=1)
        defaults.update(kwargs)
        return self.model(**defaults)

    def test_valid_request(self):
        req = self._make()
        self.assertEqual(req.copies, 1)
        self.assertEqual(req.price, 3000)

    def test_copies_default(self):
        from main import PrintRequest
        req = PrintRequest(printer_name='P', product_name='T', price=100)
        self.assertEqual(req.copies, 1)

    def test_price_as_float(self):
        req = self._make(price=3000.0)
        self.assertAlmostEqual(req.price, 3000.0)

    def test_price_as_string_coerced(self):
        # Pydantic v2 coerces numeric strings to float
        req = self._make(price='3000.00')
        self.assertAlmostEqual(float(req.price), 3000.0, places=1)


# ── Per-job DEVMODE logic ─────────────────────────────────────────────────────


class TestBuildJobDevmode(unittest.TestCase):
    """
    Verify that build_job_devmode() modifies only a local copy and never calls
    SetPrinter (which would persist changes globally).
    """

    def _make_fake_devmode(self):
        dm = MagicMock()
        dm.PaperSize   = 9     # A4 (global default)
        dm.PaperWidth  = 2100  # 210 mm (A4)
        dm.PaperLength = 2970  # 297 mm (A4)
        dm.Orientation = 1
        dm.Fields      = 0
        return dm

    def test_job_devmode_sets_43x25(self):
        """After build_job_devmode(), the returned DEVMODE must be 43×25 mm."""
        dm = self._make_fake_devmode()

        import win32print as w32p_mod
        fake_info = {'pDevMode': dm, 'pDriverName': 'XPRINTER'}

        with patch('win32print.OpenPrinter', return_value=object()), \
             patch('win32print.ClosePrinter'), \
             patch('win32print.DocumentProperties', side_effect=Exception('skip')), \
             patch('win32print.GetPrinter', return_value=fake_info):
            result = printing.build_job_devmode('FakePrinter')

        self.assertIsNotNone(result)
        self.assertEqual(result.PaperSize,   256)
        self.assertEqual(result.PaperWidth,  430)
        self.assertEqual(result.PaperLength, 250)
        self.assertEqual(result.Orientation, 1)

    def test_setprinter_never_called(self):
        """build_job_devmode() must NOT call SetPrinter."""
        dm = self._make_fake_devmode()

        with patch('win32print.OpenPrinter', return_value=object()), \
             patch('win32print.ClosePrinter'), \
             patch('win32print.DocumentProperties', side_effect=Exception('skip')), \
             patch('win32print.GetPrinter', return_value={'pDevMode': dm}), \
             patch('win32print.SetPrinter') as mock_set:
            printing.build_job_devmode('FakePrinter')
            mock_set.assert_not_called()


class TestComputeDestRect(unittest.TestCase):
    """Verify centred destination rectangle calculation."""

    def test_exact_fit(self):
        """When physical page == label size, dest should be at (0,0)."""
        caps = {'phys_w': 344, 'phys_h': 200, 'phys_ox': 0, 'phys_oy': 0,
                'horzres': 344, 'vertres': 200}
        rect = printing._compute_dest_rect(caps, 344, 200)
        self.assertEqual(rect, (0, 0, 344, 200))

    def test_large_page_centering(self):
        """Label must be centred on a 76.2×101.6 mm page (old global default)."""
        # 76.2 mm at 203 DPI ≈ 608 px;  101.6 mm ≈ 814 px
        phys_w, phys_h = 608, 814
        label_w, label_h = 344, 200   # 43×25 mm at 203 DPI
        phys_ox, phys_oy = 10, 10
        caps = {'phys_w': phys_w, 'phys_h': phys_h,
                'phys_ox': phys_ox, 'phys_oy': phys_oy,
                'horzres': 588, 'vertres': 794}
        rect = printing._compute_dest_rect(caps, label_w, label_h)
        # Physical centre minus offset
        exp_x = round(phys_w / 2 - label_w / 2) - phys_ox   # 132 - 10 = 122
        exp_y = round(phys_h / 2 - label_h / 2) - phys_oy   # 307 - 10 = 297
        self.assertEqual(rect[0], exp_x)
        self.assertEqual(rect[1], exp_y)
        self.assertEqual(rect[2], exp_x + label_w)
        self.assertEqual(rect[3], exp_y + label_h)

    def test_small_offsets(self):
        """Non-printable margin offsets must be subtracted."""
        caps = {'phys_w': 344, 'phys_h': 200, 'phys_ox': 5, 'phys_oy': 3,
                'horzres': 334, 'vertres': 194}
        rect = printing._compute_dest_rect(caps, 344, 200)
        # page centre = (172, 100); label half = (172, 100); dest_physical=(0,0); dest_dc=(-5,-3)
        self.assertEqual(rect[0], -5)
        self.assertEqual(rect[1], -3)


class TestGlobalSettingsPreservation(unittest.TestCase):
    """
    Verify read_global_devmode() reads without writing and
    that the print path never calls SetPrinter.
    """

    def test_read_global_devmode_no_setprinter(self):
        dm = MagicMock()
        dm.PaperSize   = 9
        dm.PaperWidth  = 2100
        dm.PaperLength = 2970
        dm.Orientation = 1

        with patch('win32print.OpenPrinter', return_value=object()), \
             patch('win32print.ClosePrinter'), \
             patch('win32print.GetPrinter', return_value={'pDevMode': dm}), \
             patch('win32print.SetPrinter') as mock_set:
            result = printing.read_global_devmode('FakePrinter')
            mock_set.assert_not_called()

        self.assertEqual(result['PaperSize'],   9)
        self.assertEqual(result['PaperWidth'],  2100)
        self.assertEqual(result['PaperLength'], 2970)


# ── No SumatraPDF references in active code ───────────────────────────────────


class TestNoSumatraPDF(unittest.TestCase):
    def _read(self, filename):
        path = Path(__file__).parent / filename
        return path.read_text(encoding='utf-8', errors='ignore').lower()

    def test_printing_py_no_sumatra(self):
        src = self._read('printing.py')
        # No subprocess invocation (old SumatraPDF approach)
        self.assertNotIn('subprocess', src)
        # No PDF URL download
        self.assertNotIn('pdf_url', src)
        # No SumatraPDF executable reference
        self.assertNotIn('sumatrapdf.exe', src)

    def test_main_py_no_sumatra(self):
        src = self._read('main.py')
        # No subprocess (old SumatraPDF approach)
        self.assertNotIn('subprocess', src)
        # No PDF URL
        self.assertNotIn('pdf_url', src)
        # No SumatraPDF executable reference
        self.assertNotIn('sumatrapdf.exe', src)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    unittest.main(verbosity=2)
