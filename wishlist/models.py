from django.db import models


class WishlistItem(models.Model):
    account = models.ForeignKey(
        'accounts.Account',
        on_delete=models.CASCADE,
        related_name='wishlist_items'
    )

    product = models.ForeignKey(
        'store.Product',
        on_delete=models.CASCADE,
        related_name='wishlist_items'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('account', 'product')

    def __str__(self):
        return f"{self.account.username} - {self.product.product_name}"