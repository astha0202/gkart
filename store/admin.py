from django.contrib import admin
from .models import Category, Product, Variation, ProductGallery


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('category_name', 'slug')
    search_fields = ('category_name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'product_name',
        'category',
        'price',
        'stock',
        'is_available',
        'created_at'
    )

    list_filter = (
        'category',
        'is_available',
        'created_at'
    )

    search_fields = (
        'product_name',
        'description'
    )


@admin.register(Variation)
class VariationAdmin(admin.ModelAdmin):
    list_display = (
        'product',
        'variation_category',
        'variation_value',
        'is_active'
    )

    list_filter = (
        'variation_category',
        'is_active'
    )


@admin.register(ProductGallery)
class ProductGalleryAdmin(admin.ModelAdmin):
    list_display = ('product', 'image')