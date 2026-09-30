from django.db import models

# Create your models here.
class RecentlyViewed(models.Model):
    account = models.ForeignKey(
        'accounts.Account',
        on_delete=models.CASCADE
    )
    product = models.ForeignKey(
        'store.Product',
        on_delete=models.CASCADE
    )
    viewed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.account} - {self.product}"