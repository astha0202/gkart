from decimal import Decimal

from django.db import models
from accounts.models import VendorProfile


# Indian GST slabs. A product carries its own slab, and a quotation starts
# from the slab of the products on it (the vendor can still change it).
GST_SLAB_CHOICES = [
    (Decimal('0.00'), '0% GST (Exempt)'),
    (Decimal('5.00'), '5% GST'),
    (Decimal('12.00'), '12% GST'),
    (Decimal('18.00'), '18% GST (Standard)'),
    (Decimal('28.00'), '28% GST (Luxury)'),
]

DEFAULT_GST_RATE = Decimal('18.00')


class Category(models.Model):
    category_name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=100, unique=True)

    def __str__(self):
        return self.category_name


class Product(models.Model):
    product_name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    images = models.ImageField(upload_to='photos/products/')
    stock = models.IntegerField()

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    vendor = models.ForeignKey(
        VendorProfile,
        on_delete=models.CASCADE,
        related_name='products',
        null=True,
        blank=True
    )

    gst_rate = models.DecimalField(
        'GST rate (%)',
        max_digits=5,
        decimal_places=2,
        choices=GST_SLAB_CHOICES,
        default=DEFAULT_GST_RATE,
    )

    is_available = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.product_name

class Variation(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='variations'
    )

    variation_category = models.CharField(max_length=100)
    variation_value = models.CharField(max_length=100)

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.product.product_name} - {self.variation_category}: {self.variation_value}"


class ProductGallery(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='gallery'
    )

    image = models.ImageField(
        upload_to='photos/products/gallery/'
    )

    def __str__(self):
        return self.product.product_name