from django.db import migrations, models
from django.utils.text import slugify


def backfill_vendor_slugs(apps, schema_editor):
    VendorProfile = apps.get_model('accounts', 'VendorProfile')

    existing_slugs = set(
        VendorProfile.objects.exclude(slug__isnull=True)
        .exclude(slug='')
        .values_list('slug', flat=True)
    )

    for vendor in VendorProfile.objects.filter(slug__isnull=True):
        base_slug = slugify(vendor.business_name) or f'vendor-{vendor.pk}'
        slug = base_slug
        counter = 1

        while slug in existing_slugs:
            slug = f'{base_slug}-{counter}'
            counter += 1

        existing_slugs.add(slug)
        vendor.slug = slug
        vendor.save(update_fields=['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_remove_account_otp_remove_account_otp_created_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendorprofile',
            name='slug',
            field=models.SlugField(blank=True, max_length=220, null=True, unique=True),
        ),
        migrations.RunPython(backfill_vendor_slugs, migrations.RunPython.noop),
    ]
