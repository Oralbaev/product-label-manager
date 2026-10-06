from django.urls import path
from . import views

urlpatterns = [
    path('',                                            views.dashboard,       name='dashboard'),

    path('products/',                                  views.product_list,    name='product_list'),
    path('products/archived/',                          views.product_archived_list, name='product_archived_list'),
    path('products/create/',                           views.product_create,  name='product_create'),
    path('products/<int:variant_id>/edit/',             views.product_edit,    name='product_edit'),
    path('products/<int:variant_id>/archive/',          views.product_archive, name='product_archive'),
    path('products/<int:variant_id>/restore/',          views.product_restore, name='product_restore'),
    path('products/<int:variant_id>/print/',           views.print_settings,  name='print_settings'),
    path('products/<int:variant_id>/print/submit/',     views.print_variant_submit, name='print_variant_submit'),
    path('products/<int:variant_id>/label/preview/',   views.label_preview,   name='label_preview'),
    path('products/<int:variant_id>/label/',           views.print_label,     name='print_label'),

    path('direct-print/',                               views.direct_print,    name='direct_print'),
    path('print-history/',                              views.print_history,   name='print_history'),

    path('api/printers/',                               views.printers_api,    name='printers_api'),
    path('api/health/',                                  views.health_api,      name='health_api'),
]
