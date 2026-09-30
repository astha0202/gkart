from django.db import models


class Order(models.Model):
    account = models.ForeignKey(
        'accounts.Account',
        on_delete=models.CASCADE
    )
    address = models.ForeignKey(
        'accounts.Address',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    order_number = models.CharField(max_length=50, unique=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(
        max_length=30,
        default='Pending'
    )

    is_ordered = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.order_number


class OrderProduct(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='order_products'
    )
    product = models.ForeignKey(
        'store.Product',
        on_delete=models.CASCADE
    )

    quantity = models.PositiveIntegerField(default=1)
    product_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    ordered = models.BooleanField(default=False)

    @property
    def sub_total(self):
        return self.product_price * self.quantity

    def __str__(self):
        return f"{self.order.order_number} - {self.product.product_name}"