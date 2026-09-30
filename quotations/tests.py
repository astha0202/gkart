from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Account, VendorProfile
from cart.models import Cart
from store.models import Product

from .models import Quote


def make_account(username, email, is_verified=True):
    return Account.objects.create_user(
        username=username,
        email=email,
        password='pass12345!',
        full_name=username.title(),
        phone='9990000000',
        is_verified=is_verified,
        is_active=True,
    )


def make_vendor(username, business_name):
    account = make_account(username, f'{username}@example.com')

    return VendorProfile.objects.create(
        account=account,
        business_name=business_name,
        phone_number='9990000000',
        is_approved=True,
    )


def make_product(vendor, name, price):
    return Product.objects.create(
        product_name=name,
        slug=name.lower().replace(' ', '-'),
        description='test product',
        price=Decimal(price),
        images='photos/products/test.jpg',
        stock=100,
        vendor=vendor,
        is_available=True,
    )


REQUEST_DATA = {
    'contact_name': 'Buyer One',
    'contact_email': 'buyer@example.com',
    'contact_phone': '9876543210',
    'billing_address': '12 Market Road, Ghaziabad',
    'buyer_gst_number': '22AAAAA0000A1Z5',
    'buyer_pan_number': 'ABCDE1234F',
    'validity_days': '15',
    'buyer_notes': 'Please quote for bulk.',
}


VENDOR_RESPONSE = {
    'delivery_days': '7',
    'payment_terms': '50% advance',
    'warranty_terms': '12 months',
    'shipping_charges': '0',
    'discount': '0',
    'tax_rate': '18.00',
    'vendor_gst_number': '22BBBBB0000B1Z5',
    'vendor_bank_account_name': 'Vendor Ltd',
    'vendor_bank_account_number': '998877665544',
    'vendor_bank_ifsc': 'ICIC0004321',
    'vendor_bank_name': 'ICICI Bank',
    'vendor_notes': 'Best rate for you.',
}


class QuotationTotalsTests(TestCase):

    def setUp(self):
        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.product = make_product(self.vendor, 'Steel Pipe', '100.00')
        self.buyer = make_account('buyer', 'buyer@example.com')
        self.client.force_login(self.buyer)

    def test_request_is_created_with_a_non_zero_estimated_total(self):
        response = self.client.post(
            reverse('quote_request_create', args=[self.product.slug]),
            dict(REQUEST_DATA, quantity='4'),
        )

        quote = Quote.objects.get()

        self.assertRedirects(
            response,
            reverse('quote_detail', args=[quote.quote_number]),
        )

        # 4 x 100 = 400 subtotal, +18% tax
        self.assertEqual(quote.subtotal, Decimal('400.00'))
        self.assertEqual(quote.tax, Decimal('72.00'))
        self.assertEqual(quote.total, Decimal('472.00'))
        self.assertTrue(quote.is_estimate)

    def test_tax_details_are_stored(self):
        self.client.post(
            reverse('quote_request_create', args=[self.product.slug]),
            dict(REQUEST_DATA, quantity='1'),
        )

        quote = Quote.objects.get()

        self.assertEqual(quote.buyer_gst_number, '22AAAAA0000A1Z5')
        self.assertEqual(quote.buyer_pan_number, 'ABCDE1234F')
        self.assertEqual(quote.billing_address, '12 Market Road, Ghaziabad')

    def test_customer_is_not_asked_for_bank_details(self):
        response = self.client.get(
            reverse('quote_request_create', args=[self.product.slug])
        )

        self.assertNotContains(response, 'buyer_bank_account_number')
        self.assertNotContains(response, 'Bank Details')

    def test_invalid_request_reports_an_error_and_creates_nothing(self):
        bad = dict(REQUEST_DATA, quantity='1', contact_phone='')

        response = self.client.post(
            reverse('quote_request_create', args=[self.product.slug]),
            bad,
            follow=True,
        )

        self.assertEqual(Quote.objects.count(), 0)

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('not sent', text)

        # The rest of what was typed is still on the redisplayed form.
        self.assertContains(response, '12 Market Road, Ghaziabad')

    def test_logged_in_email_cannot_be_overridden(self):
        self.client.post(
            reverse('quote_request_create', args=[self.product.slug]),
            dict(REQUEST_DATA, quantity='1', contact_email='attacker@evil.com'),
        )

        quote = Quote.objects.get()
        self.assertEqual(quote.contact_email, self.buyer.email)


class MultiVendorComparisonTests(TestCase):

    def setUp(self):
        self.vendor_a = make_vendor('vendora', 'Alpha Traders')
        self.vendor_b = make_vendor('vendorb', 'Beta Supplies')
        self.vendor_c = make_vendor('vendorc', 'Gamma Works')

        self.product_a = make_product(self.vendor_a, 'Pipe A', '100.00')
        self.product_b = make_product(self.vendor_b, 'Pipe B', '100.00')
        self.product_c = make_product(self.vendor_c, 'Pipe C', '100.00')

        self.buyer = make_account('buyer', 'buyer@example.com')
        self.client.force_login(self.buyer)

        for product in (self.product_a, self.product_b, self.product_c):
            Cart.objects.create(
                account=self.buyer, product=product, quantity=2
            )

    def _send_request(self):
        return self.client.post(reverse('quotation'), REQUEST_DATA)

    def test_one_request_reaches_every_vendor_in_one_group(self):
        self._send_request()

        quotes = Quote.objects.all()

        self.assertEqual(quotes.count(), 3)
        self.assertEqual(len({q.request_group for q in quotes}), 1)

    def test_comparison_recommends_the_best_offer(self):
        self._send_request()

        prices = {
            'Alpha Traders': ('90.00', '10'),
            'Beta Supplies': ('70.00', '3'),
            'Gamma Works': ('80.00', '20'),
        }

        for quote in Quote.objects.all():
            price, delivery = prices[quote.vendor.business_name]

            self.client.force_login(quote.vendor.account)

            item = quote.items.get()

            self.client.post(
                reverse('quote_send', args=[quote.quote_number]),
                dict(
                    VENDOR_RESPONSE,
                    delivery_days=delivery,
                    **{
                        'form-TOTAL_FORMS': '1',
                        'form-INITIAL_FORMS': '1',
                        'form-MIN_NUM_FORMS': '0',
                        'form-MAX_NUM_FORMS': '1000',
                        'form-0-id': str(item.id),
                        'form-0-quoted_price': price,
                    }
                ),
            )

        for quote in Quote.objects.all():
            self.assertEqual(
                quote.status, Quote.STATUS_QUOTED, quote.vendor.business_name
            )

        self.client.force_login(self.buyer)

        group = Quote.objects.first().request_group

        response = self.client.get(reverse('quote_compare', args=[group]))

        self.assertEqual(response.status_code, 200)

        best = response.context['best']

        # Beta is both the cheapest and the fastest.
        self.assertEqual(best['quote'].vendor.business_name, 'Beta Supplies')
        self.assertIn('Lowest price', best['badges'])
        self.assertIn('Fastest delivery', best['badges'])
        self.assertIn('lowest total', best['reason'])

        self.assertContains(response, 'BEST FOR YOU')

    def test_detailed_comparison_lists_every_field(self):
        self._send_request()

        group = Quote.objects.first().request_group

        response = self.client.get(
            reverse('quote_compare_detail', args=[group])
        )

        self.assertEqual(response.status_code, 200)

        labels = [line['label'] for line in response.context['matrix']]

        for expected in (
            'Total',
            'Payment terms',
            'Delivery lead time',
            'Bank - IFSC',
            'Vendor GST number',
        ):
            self.assertIn(expected, labels)

    def test_another_buyer_cannot_open_the_comparison(self):
        self._send_request()

        group = Quote.objects.first().request_group

        self.client.force_login(make_account('other', 'other@example.com'))

        response = self.client.get(reverse('quote_compare', args=[group]))

        self.assertEqual(response.status_code, 404)


class VendorPricingTests(TestCase):

    def setUp(self):
        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.product = make_product(self.vendor, 'Steel Pipe', '100.00')
        self.buyer = make_account('buyer', 'buyer@example.com')

        self.client.force_login(self.buyer)
        self.client.post(
            reverse('quote_request_create', args=[self.product.slug]),
            dict(REQUEST_DATA, quantity='2'),
        )

        self.quote = Quote.objects.get()

    def _post(self, **overrides):
        item = self.quote.items.get()

        data = dict(
            VENDOR_RESPONSE,
            **{
                'form-TOTAL_FORMS': '1',
                'form-INITIAL_FORMS': '1',
                'form-MIN_NUM_FORMS': '0',
                'form-MAX_NUM_FORMS': '1000',
                'form-0-id': str(item.id),
                'form-0-quoted_price': '90.00',
            }
        )
        data.update(overrides)

        self.client.force_login(self.vendor.account)

        return self.client.post(
            reverse('quote_send', args=[self.quote.quote_number]),
            data,
            follow=True,
        )

    def test_totals_use_the_quoted_price_discount_and_shipping(self):
        self._post(discount='20.00', shipping_charges='50.00')

        self.quote.refresh_from_db()

        # 2 x 90 = 180, less 20 discount = 160, +18% tax = 28.80, +50 shipping
        self.assertEqual(self.quote.subtotal, Decimal('180.00'))
        self.assertEqual(self.quote.tax, Decimal('28.80'))
        self.assertEqual(self.quote.total, Decimal('238.80'))
        self.assertFalse(self.quote.is_estimate)

    def test_missing_bank_details_are_rejected_with_a_message(self):
        response = self._post(vendor_bank_ifsc='')

        self.quote.refresh_from_db()
        self.assertEqual(self.quote.status, Quote.STATUS_PENDING)

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('not sent', text)

    def test_missing_price_is_rejected_with_a_message(self):
        response = self._post(**{'form-0-quoted_price': ''})

        self.quote.refresh_from_db()
        self.assertEqual(self.quote.status, Quote.STATUS_PENDING)

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('quoted price for every item', text)

    def test_a_different_vendor_cannot_price_the_quote(self):
        other = make_vendor('vendortwo', 'Vendor Two')

        self.client.force_login(other.account)

        response = self.client.get(
            reverse('quote_send', args=[self.quote.quote_number])
        )

        self.assertEqual(response.status_code, 404)


class NotificationLinkTests(TestCase):
    """Every notification a quotation flow raises must point at a real page."""

    def setUp(self):
        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.product = make_product(self.vendor, 'Steel Pipe', '100.00')
        self.buyer = make_account('buyer', 'buyer@example.com')

    def _assert_all_links_resolve(self):
        from django.urls import Resolver404, resolve
        from notifications.models import Notification

        links = list(
            Notification.objects.exclude(link='').values_list('link', flat=True)
        )

        self.assertTrue(links, 'the flow raised no notifications')

        for link in links:
            try:
                resolve(link)
            except Resolver404:
                self.fail(f'notification link does not resolve: {link}')

    def test_links_from_the_full_quote_lifecycle_resolve(self):
        self.client.force_login(self.buyer)

        self.client.post(
            reverse('quote_request_create', args=[self.product.slug]),
            dict(REQUEST_DATA, quantity='2'),
        )

        quote = Quote.objects.get()
        item = quote.items.get()

        self.client.force_login(self.vendor.account)
        self.client.post(
            reverse('quote_send', args=[quote.quote_number]),
            dict(
                VENDOR_RESPONSE,
                **{
                    'form-TOTAL_FORMS': '1',
                    'form-INITIAL_FORMS': '1',
                    'form-MIN_NUM_FORMS': '0',
                    'form-MAX_NUM_FORMS': '1000',
                    'form-0-id': str(item.id),
                    'form-0-quoted_price': '90.00',
                }
            ),
        )

        self.client.force_login(self.buyer)
        self.client.post(reverse('quote_accept', args=[quote.quote_number]))

        self._assert_all_links_resolve()

    def test_opening_a_notification_reaches_the_quotation(self):
        from notifications.models import Notification

        self.client.force_login(self.buyer)

        self.client.post(
            reverse('quote_request_create', args=[self.product.slug]),
            dict(REQUEST_DATA, quantity='1'),
        )

        quote = Quote.objects.get()

        # The vendor was notified about the new request.
        notification = Notification.objects.get(recipient=self.vendor.account)

        self.client.force_login(self.vendor.account)

        response = self.client.get(
            reverse('notification_read', args=[notification.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, quote.quote_number)

        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_a_notification_pointing_nowhere_is_explained(self):
        from notifications.models import Notification

        notification = Notification.objects.create(
            recipient=self.buyer,
            message='Stale notification',
            link='/quotations/vendor/QT-does-not-exist/',
        )

        self.client.force_login(self.buyer)

        response = self.client.get(
            reverse('notification_read', args=[notification.pk]),
            follow=True,
        )

        self.assertRedirects(response, reverse('notification_list'))

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('no longer exists', text)
