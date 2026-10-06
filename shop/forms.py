from decimal import Decimal, InvalidOperation

from django import forms

from botaprint.paper_sizes import SUPPORTED_LABEL_SIZES, DEFAULT_LABEL_SIZE

from .models import Category


class ProductCreateForm(forms.Form):
    product_name = forms.CharField(
        max_length=200,
        label='Название товара',
        error_messages={
            'required': 'Введите название товара',
            'max_length': 'Название не должно превышать 200 символов',
        },
        widget=forms.TextInput(attrs={'placeholder': 'Например: Футболка детская'}),
    )
    selling_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        label='Цена продажи (₸)',
        error_messages={
            'required': 'Введите цену продажи',
            'invalid': 'Введите корректную цену',
        },
        widget=forms.NumberInput(attrs={'placeholder': '3000'}),
    )
    purchase_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        label='Закупочная цена (₸)',
        required=False,
        error_messages={
            'invalid': 'Введите корректную цену',
        },
        widget=forms.NumberInput(attrs={'placeholder': '0'}),
    )


class DirectPrintForm(forms.Form):
    """
    Manual label print — no Product/ProductVariant is created or touched.
    printer_name has no server-side choice list: the <select> is populated
    client-side from BotaPrint's /printers (same as print_settings.html),
    since the printer list is read live from Windows, not from Django.
    """
    product_name = forms.CharField(
        max_length=200,
        label='Название товара',
        error_messages={
            'required': 'Введите название товара',
            'max_length': 'Название не должно превышать 200 символов',
        },
        widget=forms.TextInput(attrs={'placeholder': 'Например: Футболка детская'}),
    )
    price = forms.CharField(
        label='Цена',
        error_messages={'required': 'Введите цену'},
        widget=forms.TextInput(attrs={'placeholder': '12990 или 12 990 ₸'}),
    )
    printer_name = forms.CharField(
        label='Принтер',
        error_messages={'required': 'Выберите принтер'},
    )
    paper_size = forms.ChoiceField(
        label='Размер ценника',
        choices=[(k, k) for k in SUPPORTED_LABEL_SIZES],
        initial=DEFAULT_LABEL_SIZE,
        error_messages={'invalid_choice': 'Неподдерживаемый размер ценника'},
    )
    copies = forms.IntegerField(
        label='Количество',
        min_value=1,
        max_value=100,
        initial=1,
        error_messages={
            'required': 'Введите количество копий',
            'min_value': 'Количество должно быть от 1 до 100',
            'max_value': 'Количество должно быть от 1 до 100',
            'invalid': 'Введите целое число от 1 до 100',
        },
    )

    def clean_price(self) -> Decimal:
        raw = self.cleaned_data['price']
        # Accept "12990", "12 990", "12 990 ₸" — strip currency sign and
        # any whitespace (regular or non-breaking) before parsing the number.
        # The cleaned numeric value is sent to BotaPrint as-is; BotaPrint's
        # own _format_price() re-applies canonical " "-grouped "₸" formatting
        # at render time, so no ₸/spacing needs to be reconstructed here.
        cleaned = raw.replace('\xa0', ' ').replace('₸', '').replace(' ', '').strip()
        try:
            value = Decimal(cleaned)
        except (InvalidOperation, ValueError):
            raise forms.ValidationError('Введите корректную цену')
        if value < 0:
            raise forms.ValidationError('Цена должна быть не меньше 0')
        return value


class ProductEditForm(forms.Form):
    """
    Edits a Product + its ProductVariant together. The barcode is
    intentionally not editable here — see services.update_product_and_variant.
    """
    product_name = forms.CharField(
        max_length=200,
        label='Название товара',
        error_messages={'required': 'Введите название товара'},
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        required=False,
        label='Категория',
        empty_label='Без категории',
    )
    brand = forms.CharField(max_length=100, required=False, label='Бренд')
    size = forms.CharField(max_length=20, required=False, label='Размер')
    color = forms.CharField(max_length=50, required=False, label='Цвет')
    sku = forms.CharField(max_length=100, required=False, label='Артикул')
    selling_price = forms.DecimalField(
        max_digits=10, decimal_places=2, label='Цена продажи (₸)',
        error_messages={'required': 'Введите цену продажи', 'invalid': 'Введите корректную цену'},
    )
    purchase_price = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False, label='Закупочная цена (₸)',
        error_messages={'invalid': 'Введите корректную цену'},
    )
