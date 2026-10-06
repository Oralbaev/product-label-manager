from django.contrib import admin
from .models import Category, Product, ProductVariant, StockMovement, PrintJob

admin.site.register(Category)
admin.site.register(Product)


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'barcode', 'selling_price', 'current_stock', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('product__name', 'barcode', 'sku')


admin.site.register(StockMovement)


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ('product_name', 'printer_name', 'label_size', 'copies', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('product_name', 'printer_name')
