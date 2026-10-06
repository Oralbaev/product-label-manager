from django.db import models


class Category(models.Model):
    name = models.CharField('Название', max_length=100, unique=True)

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField('Название', max_length=200)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='products', verbose_name='Категория',
    )
    brand = models.CharField('Бренд', max_length=100, blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        related_name='variants', verbose_name='Товар',
    )
    size = models.CharField('Размер', max_length=20, blank=True)
    color = models.CharField('Цвет', max_length=50, blank=True)
    sku = models.CharField('Артикул', max_length=100, blank=True)
    barcode = models.CharField('Штрихкод', max_length=50, unique=True, blank=True)
    purchase_price = models.DecimalField('Закупочная цена', max_digits=10, decimal_places=2)
    selling_price = models.DecimalField('Цена продажи', max_digits=10, decimal_places=2)
    current_stock = models.PositiveIntegerField('Остаток', default=0)
    is_active = models.BooleanField('Активен', default=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Вариант товара'
        verbose_name_plural = 'Варианты товаров'

    def __str__(self):
        parts = [self.product.name]
        if self.size:
            parts.append(self.size)
        if self.color:
            parts.append(self.color)
        return ' — '.join(parts)


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        IN        = 'IN',       'Приход'
        OUT       = 'OUT',      'Расход'
        WRITE_OFF = 'WRITE_OFF','Списание'
        RETURN    = 'RETURN',   'Возврат'

    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE,
        related_name='movements', verbose_name='Вариант товара',
    )
    type = models.CharField('Тип', max_length=10, choices=MovementType.choices)
    quantity = models.PositiveIntegerField('Количество')
    purchase_price = models.DecimalField(
        'Закупочная цена', max_digits=10, decimal_places=2, null=True, blank=True,
    )
    comment = models.TextField('Комментарий', blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        verbose_name = 'Движение товара'
        verbose_name_plural = 'Движения товаров'

    def __str__(self):
        return f'{self.get_type_display()} {self.quantity} × {self.variant}'


class PrintJob(models.Model):
    """
    Audit record of one print request sent to BotaPrint.

    product_name/price are snapshots taken at print time — if the product is
    edited or archived later, historical entries must still show what was
    actually printed.
    """

    class Status(models.TextChoices):
        SUCCESS = 'SUCCESS', 'Успешно'
        FAILED  = 'FAILED',  'Ошибка'

    variant = models.ForeignKey(
        ProductVariant, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='print_jobs', verbose_name='Вариант товара',
    )
    product_name = models.CharField('Товар', max_length=200)
    price = models.DecimalField('Цена', max_digits=10, decimal_places=2)
    printer_name = models.CharField('Принтер', max_length=200, blank=True)
    label_size = models.CharField('Размер', max_length=20, blank=True)
    copies = models.PositiveIntegerField('Копии', default=1)
    status = models.CharField('Статус', max_length=10, choices=Status.choices)
    error_message = models.TextField('Ошибка', blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        verbose_name = 'Задание печати'
        verbose_name_plural = 'История печати'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.product_name} × {self.copies} ({self.get_status_display()})'
