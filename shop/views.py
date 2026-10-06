from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Sum
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages

from botaprint.paper_sizes import SUPPORTED_LABEL_SIZES, DEFAULT_LABEL_SIZE

from . import printing_service
from .models import Product, ProductVariant, PrintJob
from .forms import ProductCreateForm, ProductEditForm, DirectPrintForm
from .services import (
    create_product_with_variant_and_stock,
    update_product_and_variant,
    archive_variant,
    restore_variant,
)
from .label_service import generate_label_pdf, LABEL_W_MM, LABEL_H_MM  # used by label_preview / print_label


# ── Dashboard ─────────────────────────────────────────────────────────────────

def dashboard(request):
    active_variants = ProductVariant.objects.filter(is_active=True)
    successful_jobs = PrintJob.objects.filter(status=PrintJob.Status.SUCCESS)

    stats = {
        'product_count': Product.objects.filter(variants__is_active=True).distinct().count(),
        'variant_count': active_variants.count(),
        'success_count': successful_jobs.count(),
        'labels_printed': successful_jobs.aggregate(total=Sum('copies'))['total'] or 0,
    }
    recent_jobs = PrintJob.objects.select_related('variant', 'variant__product').order_by('-created_at')[:8]

    return render(request, 'shop/dashboard.html', {
        'stats': stats,
        'recent_jobs': recent_jobs,
    })


# ── Product list ──────────────────────────────────────────────────────────────

SORT_OPTIONS = {
    'newest':     ('-created_at', 'Сначала новые'),
    'oldest':     ('created_at', 'Сначала старые'),
    'name':       ('product__name', 'По названию (А-Я)'),
    'price_asc':  ('selling_price', 'Цена: по возрастанию'),
    'price_desc': ('-selling_price', 'Цена: по убыванию'),
}
DEFAULT_SORT = 'newest'


def product_list(request):
    q = (request.GET.get('q') or '').strip()
    sort = request.GET.get('sort') or DEFAULT_SORT
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT

    variants = (
        ProductVariant.objects
        .filter(is_active=True)
        .select_related('product', 'product__category')
        .order_by(SORT_OPTIONS[sort][0])
    )

    if q:
        # SQLite's LIKE only case-folds ASCII, so Q(...__icontains=q) alone
        # misses Cyrillic queries typed in a different case than stored
        # (e.g. "футболка" vs "Футболка"). The candidate set still comes
        # from the ORM; the case-insensitive match is done in Python so
        # Russian/Kazakh product names search reliably.
        needle = q.lower()
        variants = [
            v for v in variants
            if needle in v.product.name.lower() or needle in v.barcode.lower() or needle in v.sku.lower()
        ]

    paginator = Paginator(variants, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'shop/product_list.html', {
        'page_obj': page_obj,
        'q': q,
        'sort': sort,
        'sort_options': SORT_OPTIONS,
        'total_count': paginator.count,
    })


def product_archived_list(request):
    variants = (
        ProductVariant.objects
        .filter(is_active=False)
        .select_related('product', 'product__category')
        .order_by('-updated_at')
    )
    paginator = Paginator(variants, 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'shop/product_archived.html', {'page_obj': page_obj})


# ── Create product ────────────────────────────────────────────────────────────

def product_create(request):
    form = ProductCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            create_product_with_variant_and_stock(
                product_name=d['product_name'],
                selling_price=d['selling_price'],
                purchase_price=d['purchase_price'],
            )
            messages.success(request, 'Товар успешно создан.')
            return redirect('product_list')
        except Exception as exc:
            messages.error(request, f'Ошибка: {exc}')
    return render(request, 'shop/product_create.html', {'form': form})


# ── Edit product ──────────────────────────────────────────────────────────────

def product_edit(request, variant_id):
    variant = get_object_or_404(ProductVariant, pk=variant_id)

    if request.method == 'POST':
        form = ProductEditForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            update_product_and_variant(
                variant,
                product_name=d['product_name'],
                category=d['category'],
                brand=d['brand'],
                size=d['size'],
                color=d['color'],
                sku=d['sku'],
                selling_price=d['selling_price'],
                purchase_price=d['purchase_price'] if d['purchase_price'] is not None else 0,
            )
            messages.success(request, 'Товар обновлён.')
            return redirect('product_list')
    else:
        form = ProductEditForm(initial={
            'product_name': variant.product.name,
            'category': variant.product.category_id,
            'brand': variant.product.brand,
            'size': variant.size,
            'color': variant.color,
            'sku': variant.sku,
            'selling_price': variant.selling_price,
            'purchase_price': variant.purchase_price,
        })

    return render(request, 'shop/product_edit.html', {'form': form, 'variant': variant})


# ── Archive / restore ─────────────────────────────────────────────────────────

def product_archive(request, variant_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    variant = get_object_or_404(ProductVariant, pk=variant_id)
    archive_variant(variant)
    messages.success(request, f'«{variant.product.name}» перемещён в архив.')
    return redirect('product_list')


def product_restore(request, variant_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    variant = get_object_or_404(ProductVariant, pk=variant_id)
    restore_variant(variant)
    messages.success(request, f'«{variant.product.name}» восстановлен из архива.')
    return redirect('product_archived_list')


# ── Print settings page (BotaPrint) ──────────────────────────────────────────

def print_settings(request, variant_id):
    variant = get_object_or_404(ProductVariant, pk=variant_id)
    return render(request, 'shop/print_settings.html', {
        'variant': variant,
        'paper_sizes': SUPPORTED_LABEL_SIZES,
        'default_paper_size': DEFAULT_LABEL_SIZE,
    })


def print_variant_submit(request, variant_id):
    """
    AJAX endpoint used by print_settings.html.

    Browser -> Django -> BotaPrint -> Windows GDI -> Printer.
    Records a PrintJob either way; never talks to BotaPrint from the browser.
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    variant = get_object_or_404(ProductVariant, pk=variant_id)
    printer_name = (request.POST.get('printer_name') or '').strip()
    paper_size = request.POST.get('paper_size') or DEFAULT_LABEL_SIZE

    try:
        copies = int(request.POST.get('copies', 1))
    except (TypeError, ValueError):
        copies = 0
    copies = max(1, min(100, copies)) if copies > 0 else 1

    if not printer_name:
        return JsonResponse({'success': False, 'message': 'Выберите принтер'}, status=400)
    if paper_size not in SUPPORTED_LABEL_SIZES:
        return JsonResponse({'success': False, 'message': 'Неподдерживаемый размер ценника'}, status=400)

    job = printing_service.print_label(
        printer_name=printer_name,
        product_name=variant.product.name,
        price=variant.selling_price,
        copies=copies,
        paper_size=paper_size,
        variant=variant,
    )

    if job.status == PrintJob.Status.SUCCESS:
        return JsonResponse({'success': True, 'message': 'Ценник отправлен на печать'})
    return JsonResponse(
        {'success': False, 'message': job.error_message or 'Ошибка печати'},
        status=502,
    )


# ── Read-only BotaPrint proxy (kept same-origin; BotaPrint itself stays on 127.0.0.1 only) ──

def printers_api(request):
    return JsonResponse(printing_service.get_printers())


def health_api(request):
    return JsonResponse({'ok': printing_service.check_health()})


# ── Direct print — manual label, no Product/ProductVariant is created ─────────

def direct_print(request):
    """
    Print a one-off price label without touching the products table.

    GET  — render an empty form (paper sizes from botaprint.paper_sizes;
           printer list is loaded client-side via the /api/printers/ proxy).
    POST — validate, then hand off to printing_service, which talks to
           BotaPrint and records a PrintJob (variant=None) either way.
    """
    if request.method == 'POST':
        form = DirectPrintForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            job = printing_service.print_label(
                printer_name=d['printer_name'],
                product_name=d['product_name'],
                price=d['price'],
                copies=d['copies'],
                paper_size=d['paper_size'],
            )
            if job.status == PrintJob.Status.SUCCESS:
                messages.success(request, 'Ценник отправлен на печать')
            else:
                messages.error(request, job.error_message or 'Ошибка печати')
            return redirect('direct_print')
    else:
        form = DirectPrintForm(initial={
            'paper_size': DEFAULT_LABEL_SIZE,
            'copies'    : 1,
        })

    return render(request, 'shop/direct_print.html', {
        'form'      : form,
        'paper_sizes': SUPPORTED_LABEL_SIZES,
    })


# ── Print history ─────────────────────────────────────────────────────────────

def print_history(request):
    status = request.GET.get('status') or 'all'
    jobs = PrintJob.objects.select_related('variant', 'variant__product').order_by('-created_at')
    if status in (PrintJob.Status.SUCCESS, PrintJob.Status.FAILED):
        jobs = jobs.filter(status=status)

    paginator = Paginator(jobs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'shop/print_history.html', {
        'page_obj': page_obj,
        'status': status,
    })


# ── Label print-preview (browser-based fallback) ─────────────────────────────

def label_preview(request, variant_id):
    variant = get_object_or_404(ProductVariant, pk=variant_id)

    try:
        count = max(1, min(100, int(request.GET.get('count', 1))))
    except (ValueError, TypeError):
        count = 1

    pdf_url = (
        reverse('print_label', args=[variant_id])
        + '?' + urlencode({'count': count})
    )

    return render(request, 'shop/label_preview.html', {
        'variant': variant,
        'count': count,
        'size': f'{LABEL_W_MM}x{LABEL_H_MM}',
        'pdf_url': pdf_url,
    })


# ── Raw PDF endpoint ──────────────────────────────────────────────────────────

def print_label(request, variant_id):
    """
    Returns a PDF label for the given variant.

    Query params:
        count  — number of pages / copies (default 1, max 100)

    Page size is always fixed: 30 mm × 20 mm.
    """
    variant = get_object_or_404(ProductVariant, pk=variant_id)

    try:
        count = max(1, min(100, int(request.GET.get('count', 1))))
    except (ValueError, TypeError):
        count = 1

    pdf_bytes = generate_label_pdf(variant, count=count)

    # Sanity-check: page must be ~30×20 mm, never A4 (≈210×297 mm).
    if __debug__:
        try:
            from pypdf import PdfReader
            import io as _io
            _pg = PdfReader(_io.BytesIO(pdf_bytes)).pages[0]
            _w  = float(_pg.mediabox.width)  * 25.4 / 72
            _h  = float(_pg.mediabox.height) * 25.4 / 72
            assert not (_w > 200 or _h > 100), (
                f'Label PDF has wrong size ({_w:.1f}×{_h:.1f} mm); '
                f'expected ~{LABEL_W_MM}×{LABEL_H_MM} mm. '
                'Restart the server and check label_service.py.'
            )
        except ImportError:
            pass

    filename = f'label_{variant.barcode}.pdf'
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response
