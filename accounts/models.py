from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.text import slugify

class Account(AbstractUser):
    full_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15)
    is_verified = models.BooleanField(default=False)

    groups = models.ManyToManyField(
        'auth.Group',
        blank=True,
        related_name='account_set',
        related_query_name='account',
    )

    user_permissions = models.ManyToManyField(
        'auth.Permission',
        blank=True,
        related_name='account_set',
        related_query_name='account',
    )

    def __str__(self):
        return self.email
class UserProfile(models.Model):
    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE
    )
    profile_picture = models.ImageField(
        upload_to='photos/profile/',
        blank=True,
        null=True
    )
    phone_number = models.CharField(
        max_length=15,
        blank=True
    )
    def __str__(self):
        return self.account.username

class Address(models.Model):
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='addresses'
    )
    address_line_1 = models.CharField(max_length=200)
    address_line_2 = models.CharField(
        max_length=200,
        blank=True
    )
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(
        max_length=100,
        default='India'
    )
    pincode = models.CharField(max_length=10)
    is_default = models.BooleanField(default=False)
    def __str__(self):
        return f"{self.account.username} - {self.city}"

class VendorProfile(models.Model):
    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE
    )
    business_name = models.CharField(max_length=200)
    business_description = models.TextField(
        blank=True
    )
    phone_number = models.CharField(
        max_length=15,
        blank=True
    )
    is_approved = models.BooleanField(default=True)

    # ----- 1. Organization details -----
    gst_number = models.CharField('GSTIN', max_length=20, blank=True)
    pan_number = models.CharField('PAN', max_length=15, blank=True)
    cin_number = models.CharField('CIN', max_length=25, blank=True)
    business_email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    business_address = models.TextField(blank=True)

    # ----- 2. Bank details (printed on quotations / proforma invoices) -----
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_name = models.CharField('A/C holder', max_length=120, blank=True)
    bank_account_number = models.CharField('Account number', max_length=30, blank=True)
    bank_ifsc = models.CharField('IFSC code', max_length=15, blank=True)
    bank_branch = models.CharField('Branch', max_length=120, blank=True)

    # ----- 3. Default terms & conditions for every quotation -----
    terms_validity = models.CharField('Validity', max_length=200, blank=True)
    terms_delivery = models.CharField('Delivery', max_length=255, blank=True)
    terms_payment = models.CharField('Payment', max_length=200, blank=True)
    terms_remarks = models.TextField('Remarks', blank=True)

    slug = models.SlugField(
        max_length=220,
        unique=True,
        null=True,
        blank=True
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.business_name) or f'vendor-{self.account_id}'
            slug = base_slug
            counter = 1

            while VendorProfile.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1

            self.slug = slug

        super().save(*args, **kwargs)

    @property
    def has_bank_details(self):
        return all((
            self.bank_account_name,
            self.bank_account_number,
            self.bank_ifsc,
            self.bank_name,
        ))

    def __str__(self):
        return self.business_name
