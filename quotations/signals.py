from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import ProformaInvoice, PurchaseOrder, Quote


def _generate_number(prefix, model, field_name):
    """Sequential, date-scoped, collision-safe number generator, e.g. QT-20260918-0001."""
    # localdate() follows the configured TIME_ZONE, so the date in a
    # document number matches the date shown next to it.
    today = timezone.localdate().strftime('%Y%m%d')
    base = f"{prefix}-{today}"

    count = model.objects.filter(**{f"{field_name}__startswith": base}).count() + 1
    number = f"{base}-{count:04d}"

    while model.objects.filter(**{field_name: number}).exists():
        count += 1
        number = f"{base}-{count:04d}"

    return number


def next_tax_invoice_number():
    """Tax invoices are issued on the purchase order, numbered TI-YYYYMMDD-####."""
    return _generate_number('TI', PurchaseOrder, 'tax_invoice_number')


@receiver(pre_save, sender=Quote)
def set_quote_number(sender, instance, **kwargs):
    if not instance.quote_number:
        instance.quote_number = _generate_number('QT', Quote, 'quote_number')


@receiver(pre_save, sender=PurchaseOrder)
def set_po_number(sender, instance, **kwargs):
    if not instance.po_number:
        instance.po_number = _generate_number('PO', PurchaseOrder, 'po_number')


@receiver(pre_save, sender=ProformaInvoice)
def set_pi_number(sender, instance, **kwargs):
    if not instance.pi_number:
        instance.pi_number = _generate_number('PI', ProformaInvoice, 'pi_number')
