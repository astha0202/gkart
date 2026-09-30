import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

from accounts.models import VendorProfile
from store.models import DEFAULT_GST_RATE, GST_SLAB_CHOICES, Product


# The quotation lifecycle, in order, as shown on the progress stepper.
LIFECYCLE_STEPS = [
    ('brief', 'Requirement Brief', 'Created by customer'),
    ('submitted', 'Quote Submitted', 'Rates & tax quoted'),
    ('selected', 'Quote Selected', 'Approved by customer'),
    ('po', 'PO Issued', 'Purchase order raised'),
    ('pi', 'Proforma Invoice', 'PI provided'),
    ('payment', 'Customer Payment', 'Payment made'),
    ('ack', 'Payment Ack', 'Receipt confirmed'),
    ('tax_invoice', 'Tax Invoice', 'Final invoice issued'),
]


def default_tax_rate_for(products):
    """The GST slab a new quotation starts from.

    Every product carries its own slab; when a quotation mixes slabs the
    highest one is used so the estimate never under-states the tax.
    """
    rates = [p.gst_rate for p in products if p.gst_rate is not None]
    return max(rates) if rates else DEFAULT_GST_RATE


class Quote(models.Model):

    STATUS_PENDING = 'pending'
    STATUS_QUOTED = 'quoted'
    STATUS_ACCEPTED = 'accepted'
    STATUS_REJECTED = 'rejected'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CONVERTED = 'converted'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_QUOTED, 'Quoted'),
        (STATUS_ACCEPTED, 'Accepted'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_CONVERTED, 'Converted'),
    ]

    quote_number = models.CharField(max_length=30, unique=True, blank=True)

    # Quotations created from a single buyer request to several vendors share
    # one request_group, so their responses can be compared side by side.
    request_group = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)

    # Unguessable key for the public, mobile-friendly status page the QR code
    # on an approved quotation points at.
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='quotes_as_buyer'
    )

    vendor = models.ForeignKey(
        VendorProfile,
        on_delete=models.CASCADE,
        related_name='quotes_as_vendor'
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING
    )

    buyer_notes = models.TextField(blank=True)
    vendor_notes = models.TextField(blank=True)

    requested_delivery_date = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)

    # ----- Buyer contact / billing details captured on the request form -----
    contact_name = models.CharField(max_length=100, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=15, blank=True)
    billing_address = models.TextField(blank=True)

    buyer_gst_number = models.CharField('Buyer GST number', max_length=20, blank=True)
    buyer_pan_number = models.CharField('Buyer PAN number', max_length=15, blank=True)

    buyer_bank_account_name = models.CharField(max_length=120, blank=True)
    buyer_bank_account_number = models.CharField(max_length=30, blank=True)
    buyer_bank_ifsc = models.CharField('Buyer bank IFSC', max_length=15, blank=True)
    buyer_bank_name = models.CharField(max_length=120, blank=True)

    validity_days = models.PositiveIntegerField(default=15)

    # ----- Commercial terms filled in by the vendor when pricing -----
    delivery_days = models.PositiveIntegerField(null=True, blank=True)
    payment_terms = models.CharField(max_length=200, blank=True)
    warranty_terms = models.CharField(max_length=200, blank=True)

    shipping_charges = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    packaging_charges = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        choices=GST_SLAB_CHOICES,
        default=DEFAULT_GST_RATE,
    )

    vendor_gst_number = models.CharField('Vendor GST number', max_length=20, blank=True)
    vendor_bank_account_name = models.CharField(max_length=120, blank=True)
    vendor_bank_account_number = models.CharField(max_length=30, blank=True)
    vendor_bank_ifsc = models.CharField('Vendor bank IFSC', max_length=15, blank=True)
    vendor_bank_name = models.CharField(max_length=120, blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.quote_number

    @property
    def is_priced(self):
        """True once the vendor has put a price against every line."""
        items = list(self.items.all())
        return bool(items) and all(item.quoted_price is not None for item in items)

    @property
    def is_estimate(self):
        """Totals still derived from listed prices, not from vendor pricing."""
        return not self.is_priced

    @property
    def is_approved(self):
        """The buyer has selected this quotation (it may already be a PO)."""
        return self.status in (self.STATUS_ACCEPTED, self.STATUS_CONVERTED)

    @property
    def taxable_amount(self):
        taxable = (self.subtotal or Decimal('0.00')) - (self.discount or Decimal('0.00'))
        return max(taxable, Decimal('0.00'))

    def lifecycle_steps(self):
        """The stepper: every lifecycle step with its state for this quote.

        state is one of 'done', 'current', 'todo' or 'stopped' (the step the
        quote was cancelled/rejected at).
        """
        purchase_order = getattr(self, 'purchase_order', None)
        proforma_invoice = (
            getattr(purchase_order, 'proforma_invoice', None)
            if purchase_order else None
        )

        submitted = self.status in (
            self.STATUS_QUOTED,
            self.STATUS_ACCEPTED,
            self.STATUS_CONVERTED,
            self.STATUS_REJECTED,
        ) or (self.status == self.STATUS_CANCELLED and self.is_priced)

        reached = {
            'brief': self.created_at,
            'submitted': submitted,
            'selected': self.is_approved,
            'po': purchase_order and purchase_order.created_at,
            'pi': proforma_invoice and proforma_invoice.created_at,
            'payment': purchase_order and purchase_order.payment_marked_at,
            'ack': purchase_order and purchase_order.payment_acknowledged_at,
            'tax_invoice': purchase_order and purchase_order.tax_invoice_issued_at,
        }

        stopped = self.status in (self.STATUS_CANCELLED, self.STATUS_REJECTED)

        steps = []
        current_found = False

        for number, (key, label, caption) in enumerate(LIFECYCLE_STEPS, start=1):
            value = reached[key]

            if value:
                state = 'done'
            elif not current_found:
                current_found = True
                state = 'stopped' if stopped else 'current'

                if stopped:
                    caption = self.get_status_display()
            else:
                state = 'todo'

            steps.append({
                'number': number,
                'key': key,
                'label': label,
                'caption': caption,
                'state': state,
                # A real timestamp where the step records one.
                'at': value if hasattr(value, 'year') else None,
            })

        return steps

    @property
    def current_step(self):
        """The first step not yet reached (None once the lifecycle is complete)."""
        for step in self.lifecycle_steps():
            if step['state'] in ('current', 'stopped'):
                return step

        return None

    def recalculate_totals(self, tax_rate=None):
        """Recompute subtotal/tax/total.

        Before the vendor prices the quotation each line falls back to the
        product's listed price, so the buyer always sees a meaningful estimate
        instead of a zero total.
        """
        if tax_rate is None:
            tax_rate = self.tax_rate / Decimal('100')

        subtotal = sum(
            (item.line_total() for item in self.items.all()),
            Decimal('0.00')
        )

        discount = self.discount or Decimal('0.00')
        shipping = self.shipping_charges or Decimal('0.00')
        packaging = self.packaging_charges or Decimal('0.00')

        taxable = subtotal - discount

        if taxable < 0:
            taxable = Decimal('0.00')

        self.subtotal = subtotal.quantize(Decimal('0.01'))
        self.tax = (taxable * tax_rate).quantize(Decimal('0.01'))
        self.total = (taxable + self.tax + shipping + packaging).quantize(Decimal('0.01'))

        self.save(update_fields=['subtotal', 'tax', 'total'])


class QuoteItem(models.Model):
    quote = models.ForeignKey(
        Quote,
        on_delete=models.CASCADE,
        related_name='items'
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='quote_items'
    )

    quantity = models.PositiveIntegerField(default=1)

    listed_price = models.DecimalField(max_digits=10, decimal_places=2)
    quoted_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Optional reference the buyer attaches (datasheet, spec sheet, etc.),
    # e.g. from the "Supporting Link" column of a bulk upload.
    supporting_link = models.URLField(max_length=500, blank=True)

    @property
    def effective_price(self):
        return self.quoted_price if self.quoted_price is not None else self.listed_price

    def line_total(self):
        return self.effective_price * self.quantity

    def __str__(self):
        return f"{self.quote.quote_number} - {self.product.product_name}"


class QuoteHistory(models.Model):
    quote = models.ForeignKey(
        Quote,
        on_delete=models.CASCADE,
        related_name='history'
    )

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )

    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    comment = models.TextField(blank=True)

    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']
        verbose_name_plural = 'Quote histories'

    def __str__(self):
        return f"{self.quote.quote_number}: {self.from_status or '-'} -> {self.to_status}"


class PurchaseOrder(models.Model):

    STATUS_OPEN = 'open'
    STATUS_FULFILLED = 'fulfilled'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_FULFILLED, 'Fulfilled'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    po_number = models.CharField(max_length=30, unique=True, blank=True)

    quote = models.OneToOneField(
        Quote,
        on_delete=models.CASCADE,
        related_name='purchase_order'
    )

    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='purchase_orders'
    )

    vendor = models.ForeignKey(
        VendorProfile,
        on_delete=models.CASCADE,
        related_name='purchase_orders'
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN
    )

    # ----- Steps 6-8 of the lifecycle: payment, acknowledgement, tax invoice -----
    payment_reference = models.CharField('Payment reference / UTR', max_length=100, blank=True)
    payment_marked_at = models.DateTimeField(null=True, blank=True)
    payment_acknowledged_at = models.DateTimeField(null=True, blank=True)
    tax_invoice_number = models.CharField(max_length=30, blank=True)
    tax_invoice_issued_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.po_number


class ProformaInvoice(models.Model):
    pi_number = models.CharField(max_length=30, unique=True, blank=True)

    po = models.OneToOneField(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name='proforma_invoice'
    )

    pdf_file = models.FileField(upload_to='proforma_invoices/', blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.pi_number
