from django.db import models
from accounts.models import Account
from store.models import Product

class CartItem(models.Model):
    account = models.ForeignKey(
        'accounts.Account',
        on_delete=models.CASCADE
    )

    product = models.ForeignKey(
        'store.Product',
        on_delete=models.CASCADE
    )

    quantity = models.PositiveIntegerField(default=1)

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.account} - {self.product}"



class Cart(models.Model):
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE
    )

    quantity = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.account.email} - {self.product.product_name}"