from django.contrib import admin
from .models import Order, OrderProduct


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number',
        'account',
        'total_amount',
        'status',
        'is_ordered',
        'created_at'
    )

    list_filter = ('status', 'is_ordered', 'created_at')
    search_fields = (
        'order_number',
        'account__username',
        'account__email'
    )


@admin.register(OrderProduct)
class OrderProductAdmin(admin.ModelAdmin):
    list_display = (
        'order',
        'product',
        'quantity',
        'product_price',
        'ordered'
    )

    list_filter = ('ordered',)