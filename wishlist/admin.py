from django.contrib import admin
from .models import WishlistItem


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = (
        'account',
        'product',
        'created_at'
    )

    search_fields = (
        'account__username',
        'account__email',
        'product__product_name'
    )

    list_filter = ('created_at',)