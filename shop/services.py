from django.db import transaction
from .models import Product, ProductVariant, Category


def _generate_barcode() -> str:
    last = (
        ProductVariant.objects
        .filter(barcode__startswith='200000')
        .order_by('-barcode')
        .values_list('barcode', flat=True)
        .first()
    )
    if last:
        return str(int(last) + 1)
    return '2000000001'


@transaction.atomic
def create_product_with_variant_and_stock(
    *,
    product_name: str,
    selling_price,
    purchase_price=None,
    barcode: str = '',
) -> ProductVariant:
    product = Product.objects.create(name=product_name)

    if not barcode:
        barcode = _generate_barcode()

    variant = ProductVariant.objects.create(
        product=product,
        size='',
        color='',
        sku='',
        barcode=barcode,
        purchase_price=purchase_price if purchase_price is not None else 0,
        selling_price=selling_price,
        current_stock=0,
    )

    return variant


@transaction.atomic
def update_product_and_variant(variant: ProductVariant, *, product_name: str, category: Category | None,
                               brand: str, size: str, color: str, sku: str,
                               selling_price, purchase_price) -> ProductVariant:
    """
    Update the Product and its ProductVariant together as one unit of work.

    The barcode is intentionally never touched here — it is not exposed to
    normal editing.
    """
    product = variant.product
    product.name = product_name
    product.category = category
    product.brand = brand
    product.save(update_fields=['name', 'category', 'brand', 'updated_at'])

    variant.size = size
    variant.color = color
    variant.sku = sku
    variant.selling_price = selling_price
    variant.purchase_price = purchase_price
    variant.save(update_fields=[
        'size', 'color', 'sku', 'selling_price', 'purchase_price', 'updated_at',
    ])

    return variant


def archive_variant(variant: ProductVariant) -> None:
    variant.is_active = False
    variant.save(update_fields=['is_active', 'updated_at'])


def restore_variant(variant: ProductVariant) -> None:
    variant.is_active = True
    variant.save(update_fields=['is_active', 'updated_at'])
