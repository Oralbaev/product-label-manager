import json
import urllib.error
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.urls import reverse

from .models import Product, ProductVariant, PrintJob
from .services import create_product_with_variant_and_stock


def _fake_urlopen(payload: dict):
    """Build a mock replacing urllib.request.urlopen, returning `payload` as JSON."""
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode('utf-8')
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    mock = MagicMock(return_value=cm)
    return mock


class ProductSearchTests(TestCase):
    def setUp(self):
        self.v1 = create_product_with_variant_and_stock(
            product_name='Футболка детская', selling_price=Decimal('3000'), barcode='2000000001',
        )
        self.v2 = create_product_with_variant_and_stock(
            product_name='Куртка зимняя', selling_price=Decimal('15000'), barcode='2000000002',
        )
        self.v2.sku = 'JCK-01'
        self.v2.save(update_fields=['sku'])

    def test_search_by_name(self):
        res = self.client.get(reverse('product_list'), {'q': 'футболка'})
        self.assertContains(res, 'Футболка детская')
        self.assertNotContains(res, 'Куртка зимняя')

    def test_search_by_barcode(self):
        res = self.client.get(reverse('product_list'), {'q': '2000000002'})
        self.assertContains(res, 'Куртка зимняя')
        self.assertNotContains(res, 'Футболка детская')

    def test_search_by_sku(self):
        res = self.client.get(reverse('product_list'), {'q': 'JCK-01'})
        self.assertContains(res, 'Куртка зимняя')

    def test_query_preserved_in_response(self):
        res = self.client.get(reverse('product_list'), {'q': 'футболка'})
        self.assertContains(res, 'value="футболка"')

    def test_sort_price_desc(self):
        res = self.client.get(reverse('product_list'), {'sort': 'price_desc'})
        content = res.content.decode()
        self.assertLess(content.index('Куртка зимняя'), content.index('Футболка детская'))


class ProductEditTests(TestCase):
    def setUp(self):
        self.variant = create_product_with_variant_and_stock(
            product_name='Шапка', selling_price=Decimal('2000'), barcode='2000000003',
        )

    def test_edit_updates_product_and_variant_atomically(self):
        url = reverse('product_edit', args=[self.variant.id])
        res = self.client.post(url, {
            'product_name': 'Шапка зимняя',
            'category': '',
            'brand': 'BrandX',
            'size': 'M',
            'color': 'Синий',
            'sku': 'HAT-01',
            'selling_price': '2500',
            'purchase_price': '1200',
        })
        self.assertRedirects(res, reverse('product_list'))

        self.variant.refresh_from_db()
        self.variant.product.refresh_from_db()
        self.assertEqual(self.variant.product.name, 'Шапка зимняя')
        self.assertEqual(self.variant.product.brand, 'BrandX')
        self.assertEqual(self.variant.size, 'M')
        self.assertEqual(self.variant.color, 'Синий')
        self.assertEqual(self.variant.sku, 'HAT-01')
        self.assertEqual(self.variant.selling_price, Decimal('2500'))
        self.assertEqual(self.variant.purchase_price, Decimal('1200'))

    def test_barcode_is_never_editable(self):
        url = reverse('product_edit', args=[self.variant.id])
        original_barcode = self.variant.barcode
        self.client.post(url, {
            'product_name': 'Шапка зимняя', 'category': '', 'brand': '', 'size': '',
            'color': '', 'sku': '', 'selling_price': '2500', 'purchase_price': '',
        })
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.barcode, original_barcode)


class ProductArchiveTests(TestCase):
    def setUp(self):
        self.variant = create_product_with_variant_and_stock(
            product_name='Носки', selling_price=Decimal('500'), barcode='2000000004',
        )

    def test_archive_hides_from_active_catalog(self):
        self.client.post(reverse('product_archive', args=[self.variant.id]))
        self.variant.refresh_from_db()
        self.assertFalse(self.variant.is_active)

        self.client.get(reverse('product_list'))  # consume the "moved to archive" flash message
        res = self.client.get(reverse('product_list'))
        self.assertNotContains(res, 'Носки')

    def test_archived_product_appears_in_archive_list(self):
        self.client.post(reverse('product_archive', args=[self.variant.id]))
        res = self.client.get(reverse('product_archived_list'))
        self.assertContains(res, 'Носки')

    def test_restore_returns_product_to_active_catalog(self):
        self.client.post(reverse('product_archive', args=[self.variant.id]))
        self.client.post(reverse('product_restore', args=[self.variant.id]))
        self.variant.refresh_from_db()
        self.assertTrue(self.variant.is_active)

        res = self.client.get(reverse('product_list'))
        self.assertContains(res, 'Носки')

    def test_archive_requires_post(self):
        res = self.client.get(reverse('product_archive', args=[self.variant.id]))
        self.assertEqual(res.status_code, 405)


class PrintJobTests(TestCase):
    def setUp(self):
        self.variant = create_product_with_variant_and_stock(
            product_name='Куртка', selling_price=Decimal('12500'), barcode='2000000005',
        )

    @patch('shop.printing_service.urllib.request.urlopen')
    def test_successful_print_creates_printjob(self, mock_urlopen):
        mock_urlopen.side_effect = _fake_urlopen({'success': True, 'message': 'ok'})

        url = reverse('print_variant_submit', args=[self.variant.id])
        res = self.client.post(url, {'printer_name': 'Xprinter XP-365B', 'paper_size': '43x25', 'copies': '2'})

        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['success'])

        job = PrintJob.objects.get()
        self.assertEqual(job.status, PrintJob.Status.SUCCESS)
        self.assertEqual(job.variant_id, self.variant.id)
        self.assertEqual(job.product_name, 'Куртка')
        self.assertEqual(job.price, Decimal('12500'))
        self.assertEqual(job.copies, 2)
        self.assertEqual(job.printer_name, 'Xprinter XP-365B')

    @patch('shop.printing_service.urllib.request.urlopen')
    def test_botaprint_failure_response_creates_failed_printjob(self, mock_urlopen):
        mock_urlopen.side_effect = _fake_urlopen({'success': False, 'message': 'Принтер не найден'})

        url = reverse('print_variant_submit', args=[self.variant.id])
        res = self.client.post(url, {'printer_name': 'Ghost Printer', 'paper_size': '43x25', 'copies': '1'})

        self.assertEqual(res.status_code, 502)
        self.assertFalse(res.json()['success'])

        job = PrintJob.objects.get()
        self.assertEqual(job.status, PrintJob.Status.FAILED)
        self.assertIn('не найден', job.error_message)

    @patch('shop.printing_service.urllib.request.urlopen')
    def test_unreachable_botaprint_creates_failed_printjob(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError('connection refused')

        url = reverse('print_variant_submit', args=[self.variant.id])
        res = self.client.post(url, {'printer_name': 'Xprinter XP-365B', 'paper_size': '43x25', 'copies': '1'})

        self.assertEqual(res.status_code, 502)
        job = PrintJob.objects.get()
        self.assertEqual(job.status, PrintJob.Status.FAILED)

    def test_print_submit_requires_post(self):
        url = reverse('print_variant_submit', args=[self.variant.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 405)

    def test_print_submit_requires_printer(self):
        url = reverse('print_variant_submit', args=[self.variant.id])
        res = self.client.post(url, {'printer_name': '', 'paper_size': '43x25', 'copies': '1'})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(PrintJob.objects.count(), 0)


class DirectPrintHistoryTests(TestCase):
    @patch('shop.printing_service.urllib.request.urlopen')
    def test_direct_print_creates_printjob_without_variant(self, mock_urlopen):
        mock_urlopen.side_effect = _fake_urlopen({'success': True, 'message': 'ok'})

        res = self.client.post(reverse('direct_print'), {
            'product_name': 'Разовый ценник',
            'price': '1990',
            'printer_name': 'Xprinter XP-365B',
            'paper_size': '43x25',
            'copies': '3',
        })

        self.assertRedirects(res, reverse('direct_print'))
        job = PrintJob.objects.get()
        self.assertIsNone(job.variant)
        self.assertEqual(job.product_name, 'Разовый ценник')
        self.assertEqual(job.price, Decimal('1990'))
        self.assertEqual(job.status, PrintJob.Status.SUCCESS)

    def test_direct_print_history_appears_on_history_page(self):
        PrintJob.objects.create(
            product_name='Товар без варианта', price=Decimal('500'), printer_name='P1',
            label_size='43x25', copies=1, status=PrintJob.Status.SUCCESS,
        )
        res = self.client.get(reverse('print_history'))
        self.assertContains(res, 'Товар без варианта')
        self.assertContains(res, 'Прямая печать')
