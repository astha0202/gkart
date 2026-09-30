import uuid

from django.db import migrations


def split_existing_request_groups(apps, schema_editor):
    """Give every pre-existing quote its own request group.

    Adding `request_group` with a callable default evaluates that default once
    for the whole table, so every historical quote would otherwise end up in a
    single group and be compared against unrelated requests.
    """
    Quote = apps.get_model('quotations', 'Quote')

    for quote in Quote.objects.all().iterator():
        Quote.objects.filter(pk=quote.pk).update(request_group=uuid.uuid4())


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('quotations', '0003_quote_billing_address_quote_buyer_bank_account_name_and_more'),
    ]

    operations = [
        migrations.RunPython(split_existing_request_groups, noop),
    ]
