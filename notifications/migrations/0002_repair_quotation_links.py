import re

from django.db import migrations


BROKEN = re.compile(r'^/quotations/vendor/(?P<quote_number>[^/]+)/$')


def repair_quotation_links(apps, schema_editor):
    """Point old notifications at a URL that exists.

    They were written as /quotations/vendor/<number>/, which never matched a
    route - the vendor's view of a quotation is /quotations/<number>/, the
    same detail page the buyer uses.
    """
    Notification = apps.get_model('notifications', 'Notification')

    for notification in Notification.objects.filter(
        link__startswith='/quotations/vendor/'
    ).iterator():
        match = BROKEN.match(notification.link)

        if not match:
            # e.g. /quotations/vendor/<number>/send/, which is a real route.
            continue

        Notification.objects.filter(pk=notification.pk).update(
            link='/quotations/{}/'.format(match.group('quote_number'))
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(repair_quotation_links, noop),
    ]
