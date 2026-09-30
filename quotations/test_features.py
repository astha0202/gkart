"""Tests for GST slabs, bulk upload, QR/mobile view, lifecycle stepper,
ranking, item matrix, vendor profile boxes and the notification bell."""

import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from notifications.models import Notification

from .comparison import compare_quotes, item_rate_matrix, rank_label
from .models import Quote
from .tests import (
    REQUEST_DATA,
    VENDOR_RESPONSE,
    make_account,
    make_product,
    make_vendor,
)
from .utils import amount_in_words, match_catalog_products, parse_product_sheet


def price_post(quote, price, **overrides):
    item = quote.items.get()

    data = dict(
        VENDOR_RESPONSE,
        **{
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-id': str(item.id),
            'form-0-quoted_price': price,
        }
    )
    data.update(overrides)
    return data


class GstSlabTests(TestCase):

    def setUp(self):
        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.product = make_product(self.vendor, 'Steel Pipe', '100.00')
        self.product.gst_rate = Decimal('12.00')
        self.product.save()

        self.buyer = make_account('buyer', 'buyer@example.com')
        self.client.force_login(self.buyer)

        self.client.post(
            reverse('quote_request_create', args=[self.product.slug]),
            dict(REQUEST_DATA, quantity='2'),
        )
        self.quote = Quote.objects.get()

    def test_new_quote_starts_from_the_products_gst_slab(self):
        self.assertEqual(self.quote.tax_rate, Decimal('12.00'))
        # 2 x 100 = 200, 12% = 24
        self.assertEqual(self.quote.tax, Decimal('24.00'))

    def test_vendor_picks_a_slab_and_packaging_is_added(self):
        self.client.force_login(self.vendor.account)

        self.client.post(
            reverse('quote_send', args=[self.quote.quote_number]),
            price_post(
                self.quote, '50.00',
                tax_rate='5.00', shipping_charges='10', packaging_charges='15',
            ),
        )

        self.quote.refresh_from_db()

        # 2 x 50 = 100, 5% = 5, +10 freight +15 packaging
        self.assertEqual(self.quote.status, Quote.STATUS_QUOTED)
        self.assertEqual(self.quote.tax, Decimal('5.00'))
        self.assertEqual(self.quote.total, Decimal('130.00'))

    def test_a_non_slab_rate_is_rejected(self):
        self.client.force_login(self.vendor.account)

        self.client.post(
            reverse('quote_send', args=[self.quote.quote_number]),
            price_post(self.quote, '50.00', tax_rate='7.00'),
        )

        self.quote.refresh_from_db()
        self.assertEqual(self.quote.status, Quote.STATUS_PENDING)

    def test_pricing_page_offers_the_slab_dropdown(self):
        self.client.force_login(self.vendor.account)

        response = self.client.get(reverse('quote_send', args=[self.quote.quote_number]))

        self.assertContains(response, '<select name="tax_rate"')
        self.assertContains(response, '28% GST')
        self.assertContains(response, 'calc-grand')

    def test_vendor_form_is_prefilled_from_the_business_profile(self):
        self.vendor.gst_number = '22BBBBB0000B1Z5'
        self.vendor.bank_ifsc = 'ICIC0004321'
        self.vendor.save()

        self.client.force_login(self.vendor.account)

        response = self.client.get(reverse('quote_send', args=[self.quote.quote_number]))

        self.assertContains(response, 'value="22BBBBB0000B1Z5"')
        self.assertContains(response, 'value="ICIC0004321"')


class BulkUploadParserTests(TestCase):

    def test_csv_with_flexible_headers(self):
        upload = SimpleUploadedFile(
            'list.csv',
            b'Item Name,Qty,URL\nSteel Pipe,6,example.com/spec\n,,\nBolt,abc,\nNut,,\n',
        )

        rows, problems = parse_product_sheet(upload)

        self.assertEqual(
            [(r['name'], r['quantity'], r['link']) for r in rows],
            [('Steel Pipe', 6, 'https://example.com/spec'), ('Nut', 1, '')],
        )
        self.assertTrue(any('Bolt' in p for p in problems))

    def test_xlsx(self):
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(['Product Name', 'Quantity', 'Supporting Link'])
        sheet.append(['Steel Pipe', 4, 'https://example.com/a'])

        buffer = io.BytesIO()
        workbook.save(buffer)

        rows, problems = parse_product_sheet(
            SimpleUploadedFile('list.xlsx', buffer.getvalue())
        )

        self.assertEqual(rows[0]['quantity'], 4)
        self.assertEqual(rows[0]['link'], 'https://example.com/a')
        self.assertEqual(problems, [])

    def test_matching_reaches_every_vendor_selling_the_item(self):
        a = make_vendor('vendora', 'Alpha')
        b = make_vendor('vendorb', 'Beta')

        pa = make_product(a, 'Steel Pipe', '100.00')
        pb = make_product(b, 'steel  pipe', '90.00')
        pb.slug = 'steel-pipe-b'
        pb.save()

        lines, unmatched = match_catalog_products(
            [{'row': 2, 'name': 'Steel Pipe', 'quantity': 3, 'link': ''},
             {'row': 3, 'name': 'Unobtainium', 'quantity': 1, 'link': ''}],
            [pa, pb],
        )

        self.assertEqual({line['product'] for line in lines}, {pa, pb})
        self.assertEqual([row['name'] for row in unmatched], ['Unobtainium'])


class BulkUploadFlowTests(TestCase):

    def setUp(self):
        self.vendor_a = make_vendor('vendora', 'Alpha Traders')
        self.vendor_b = make_vendor('vendorb', 'Beta Supplies')

        self.pipe_a = make_product(self.vendor_a, 'Steel Pipe', '100.00')
        self.pipe_b = make_product(self.vendor_b, 'Steel Pipe B', '95.00')
        self.pipe_b.product_name = 'Steel Pipe'
        self.pipe_b.save()

        self.buyer = make_account('buyer', 'buyer@example.com')
        self.client.force_login(self.buyer)

    def _upload(self, content, name='list.csv'):
        return self.client.post(
            reverse('quote_upload'),
            {'file': SimpleUploadedFile(name, content)},
            follow=True,
        )

    def test_upload_fills_the_form_and_reports_unmatched_rows(self):
        response = self._upload(
            b'Product Name,Quantity,Supporting Link\n'
            b'Steel Pipe,6,https://example.com/spec\n'
            b'Mystery Widget,2,\n'
        )

        self.assertRedirects(response, reverse('quotation'))
        self.assertEqual(len(self.client.session['quote_upload']), 2)

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('1 of 2', text)
        self.assertIn('Mystery Widget', text)

        # Both vendors' rows are on the form, with the uploaded quantity.
        self.assertContains(response, 'name="line_product"', count=2)
        self.assertContains(response, 'value="6"', count=2)
        self.assertContains(response, 'From uploaded file')

    def test_submitting_uploaded_rows_creates_one_quote_per_vendor(self):
        self._upload(b'Product Name,Quantity,Supporting Link\nSteel Pipe,6,https://example.com/spec\n')

        response = self.client.post(
            reverse('quotation'),
            dict(
                REQUEST_DATA,
                line_product=[str(self.pipe_a.id), str(self.pipe_b.id)],
                line_quantity=['6', '8'],
                line_link=['https://example.com/spec', ''],
            ),
        )

        quotes = Quote.objects.all()
        self.assertEqual(quotes.count(), 2)
        self.assertRedirects(
            response, reverse('quote_compare', args=[quotes[0].request_group])
        )

        item_a = Quote.objects.get(vendor=self.vendor_a).items.get()
        item_b = Quote.objects.get(vendor=self.vendor_b).items.get()

        self.assertEqual(item_a.quantity, 6)
        self.assertEqual(item_a.supporting_link, 'https://example.com/spec')
        self.assertEqual(item_b.quantity, 8)

        # The upload is consumed once the request is sent.
        self.assertNotIn('quote_upload', self.client.session)

    def test_a_bad_file_is_reported_and_changes_nothing(self):
        response = self._upload(b'Colour,Size\nred,L\n')

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('Product Name', text)
        self.assertNotIn('quote_upload', self.client.session)

        response = self._upload(b'hello', name='list.pdf')
        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('.xlsx or .csv', text)

    def test_template_download(self):
        response = self.client.get(reverse('quote_upload_template'))

        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn(b'Product Name,Quantity,Supporting Link', response.content)


class LifecycleTests(TestCase):
    """Stepper, QR code, mobile view, payment -> ack -> tax invoice."""

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

    def _states(self):
        self.quote.refresh_from_db()
        return [step['state'] for step in self.quote.lifecycle_steps()]

    def _price_and_accept(self):
        self.client.force_login(self.vendor.account)
        self.client.post(
            reverse('quote_send', args=[self.quote.quote_number]),
            price_post(self.quote, '90.00'),
        )
        self.client.force_login(self.buyer)
        self.client.post(reverse('quote_accept', args=[self.quote.quote_number]))

    def test_stepper_follows_the_workflow_to_the_end(self):
        self.assertEqual(self._states(), ['done', 'current'] + ['todo'] * 6)

        self._price_and_accept()
        self.assertEqual(self._states(), ['done'] * 5 + ['current', 'todo', 'todo'])

        detail = reverse('quote_detail', args=[self.quote.quote_number])

        # A payment without a reference is refused.
        self.client.post(reverse('quote_mark_paid', args=[self.quote.quote_number]), {})
        self.assertEqual(self._states()[5], 'current')

        self.client.post(
            reverse('quote_mark_paid', args=[self.quote.quote_number]),
            {'payment_reference': 'UTR123'},
        )
        self.assertEqual(self._states()[5:], ['done', 'current', 'todo'])

        # Only the vendor may acknowledge; the buyer is bounced.
        self.client.post(reverse('quote_ack_payment', args=[self.quote.quote_number]))
        self.assertEqual(self._states()[6], 'current')

        self.client.force_login(self.vendor.account)
        self.client.post(reverse('quote_ack_payment', args=[self.quote.quote_number]))
        self.client.post(reverse('quote_issue_tax_invoice', args=[self.quote.quote_number]))

        self.assertEqual(self._states(), ['done'] * 8)

        po = self.quote.purchase_order
        po.refresh_from_db()
        self.assertTrue(po.tax_invoice_number.startswith('TI-'))
        self.assertEqual(po.status, po.STATUS_FULFILLED)

        response = self.client.get(reverse('tax_invoice_download', args=[self.quote.quote_number]))
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

        self.assertEqual(self.client.get(detail).status_code, 200)

    def test_cancelled_quote_shows_where_it_stopped(self):
        self.client.post(reverse('quote_cancel', args=[self.quote.quote_number]))

        self.assertEqual(self._states()[:2], ['done', 'stopped'])

    def test_qr_code_only_appears_once_approved(self):
        detail = reverse('quote_detail', args=[self.quote.quote_number])

        self.assertNotContains(self.client.get(detail), 'Quotation QR')

        self._price_and_accept()

        response = self.client.get(detail)
        self.assertContains(response, 'Quotation QR')
        self.assertContains(response, '<svg')
        self.assertContains(response, reverse('quote_mobile', args=[self.quote.public_token]))

    def test_mobile_view_is_public_and_hides_bank_details(self):
        self._price_and_accept()
        self.client.logout()

        response = self.client.get(reverse('quote_mobile', args=[self.quote.public_token]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.quote.quote_number)
        self.assertContains(response, 'Steel Pipe')
        self.assertNotContains(response, VENDOR_RESPONSE['vendor_bank_account_number'])
        self.assertNotContains(response, REQUEST_DATA['buyer_pan_number'])

    def test_printable_invoice_and_pdf(self):
        self._price_and_accept()

        response = self.client.get(
            reverse('invoice_view', args=[self.quote.quote_number, 'proforma'])
        )

        self.assertContains(response, 'Proforma Invoice')
        self.assertContains(response, 'Quotation to Delivery Workflow')
        self.assertContains(response, 'Rupees')

        pi = self.quote.purchase_order.proforma_invoice
        pdf = self.client.get(reverse('pi_download', args=[pi.pi_number]))
        self.assertTrue(b''.join(pdf.streaming_content).startswith(b'%PDF'))

        # No tax invoice yet.
        self.assertEqual(
            self.client.get(
                reverse('invoice_view', args=[self.quote.quote_number, 'tax'])
            ).status_code,
            404,
        )

    def test_invoice_is_private_to_the_parties(self):
        self._price_and_accept()
        self.client.force_login(make_account('other', 'other@example.com'))

        response = self.client.get(
            reverse('invoice_view', args=[self.quote.quote_number, 'proforma'])
        )
        self.assertEqual(response.status_code, 404)


class RankingTests(TestCase):

    def setUp(self):
        self.buyer = make_account('buyer', 'buyer@example.com')
        self.vendors = [make_vendor(f'v{i}', f'Vendor {i}') for i in range(4)]

        from cart.models import Cart

        for i, vendor in enumerate(self.vendors):
            product = make_product(vendor, f'Switch {i}', '100.00')
            product.product_name = 'Cisco Switch'
            product.save()
            Cart.objects.create(account=self.buyer, product=product, quantity=2)

        self.client.force_login(self.buyer)
        self.client.post(reverse('quotation'), REQUEST_DATA)

        prices = ['70.00', '90.00', '80.00']  # the 4th vendor never responds

        for quote, price in zip(Quote.objects.order_by('vendor__business_name'), prices):
            self.client.force_login(quote.vendor.account)
            self.client.post(
                reverse('quote_send', args=[quote.quote_number]),
                price_post(quote, price),
            )

        self.client.force_login(self.buyer)

    def test_rank_labels(self):
        self.assertEqual(
            [rank_label(n) for n in (1, 2, 3, 4, None)],
            ['Best Deal', 'Second Best Deal', 'Good', 'Average', 'Awaiting quote'],
        )

    def test_list_ranks_vendor_quotes_best_first(self):
        response = self.client.get(reverse('quote_list_buyer'))

        group = response.context['grouped_quotes'][0]
        totals = [row['quote'].total for row in group['rows'] if row['rank']]

        self.assertEqual(totals, sorted(totals))
        self.assertEqual(
            [row['rank_label'] for row in group['rows']],
            ['Best Deal', 'Second Best Deal', 'Good', 'Awaiting quote'],
        )
        self.assertGreater(group['savings'], 0)
        self.assertContains(response, 'BEST FOR YOU')
        self.assertContains(response, 'Second Best Deal')

    def test_item_matrix_marks_the_lowest_rate(self):
        quotes = list(Quote.objects.all())
        rows = compare_quotes(quotes)['rows']

        matrix = item_rate_matrix(rows)

        # Same product name across vendors -> one line in the matrix.
        self.assertEqual(len(matrix), 1)

        line = matrix[0]
        best_cells = [c for c in line['cells'] if c and c['is_best_rate']]

        self.assertEqual(line['best_rate'], Decimal('70.00'))
        self.assertEqual(len(best_cells), 1)
        # The unpriced vendor's list price never counts as the best rate.
        self.assertTrue(any(c['is_estimate'] for c in line['cells']))

        response = self.client.get(
            reverse('quote_compare', args=[quotes[0].request_group])
        )
        self.assertContains(response, 'Item-by-Item Rate Comparison Matrix')
        self.assertContains(response, 'Lowest rate')


class VendorProfileBoxesTests(TestCase):

    def setUp(self):
        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.client.force_login(self.vendor.account)

    BASIC = {
        'business_name': 'Vendor One',
        'full_name': 'Owner Name',
        'phone_number': '9998887776',
        'business_description': '',
    }

    def test_three_sections_save_and_render(self):
        self.client.post(
            reverse('vendor_profile'),
            dict(
                self.BASIC,
                gst_number='22aaaaa0000a1z5',
                bank_name='HDFC Bank',
                bank_account_name='Vendor One',
                bank_account_number='34567890876543',
                bank_ifsc='hdfc0004567',
                terms_validity='15 days from date of issue',
            ),
        )

        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.gst_number, '22AAAAA0000A1Z5')
        self.assertEqual(self.vendor.bank_ifsc, 'HDFC0004567')

        response = self.client.get(reverse('vendor_details'))

        for title in ('Organization Details', 'Bank Details', 'Terms &amp; Conditions'):
            self.assertContains(response, title)

        self.assertContains(response, '15 days from date of issue')

    def test_half_filled_bank_details_are_rejected(self):
        response = self.client.post(
            reverse('vendor_profile'),
            dict(self.BASIC, bank_name='HDFC Bank', gst_number=''),
        )

        self.assertContains(response, 'bank details must be complete')
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.bank_name, '')

    def test_clearing_one_section_leaves_the_others(self):
        self.vendor.bank_name = 'HDFC Bank'
        self.vendor.terms_payment = '50% advance'
        self.vendor.save()

        self.client.post(reverse('vendor_profile_section_clear', args=['bank']))

        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.bank_name, '')
        self.assertEqual(self.vendor.terms_payment, '50% advance')


class NotificationBellTests(TestCase):

    def test_bell_lists_recent_notifications_on_every_page(self):
        buyer = make_account('buyer', 'buyer@example.com')
        Notification.objects.create(recipient=buyer, message='Quote QT-1 priced')

        self.client.force_login(buyer)

        for name in ('home', 'quote_list_buyer', 'dashboard'):
            response = self.client.get(reverse(name))
            self.assertContains(response, 'Quote QT-1 priced', msg_prefix=name)
            self.assertContains(response, 'Mark all read', msg_prefix=name)


class QuotationBadgeTests(TestCase):
    """The navbar Quotations link flashes the count of unread quotation updates."""

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

    def test_only_quotation_notifications_are_counted(self):
        Notification.objects.create(recipient=self.buyer, message='Order shipped', link='/orders/')
        Notification.objects.create(
            recipient=self.buyer, message='Priced', link=f'/quotations/{self.quote.quote_number}/'
        )
        Notification.objects.create(
            recipient=self.buyer, message='Also priced', link=f'/quotations/{self.quote.quote_number}/'
        )

        response = self.client.get(reverse('home'))

        self.assertEqual(response.context['unread_quotation_count'], 2)
        self.assertEqual(response.context['unread_notification_count'], 3)
        self.assertContains(response, 'class="gk-count"')
        self.assertContains(response, '2 unread quotation updates')

    def test_vendor_sees_new_requests_and_opening_the_quote_clears_them(self):
        self.client.force_login(self.vendor.account)

        response = self.client.get(reverse('vendor_dashboard'))
        self.assertEqual(response.context['unread_quotation_count'], 1)

        response = self.client.get(reverse('quote_detail', args=[self.quote.quote_number]))
        self.assertEqual(response.context['unread_quotation_count'], 0)
        self.assertNotContains(response, 'class="gk-count"')

    def test_no_badge_when_nothing_is_unread(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.context['unread_quotation_count'], 0)
        self.assertNotContains(response, 'class="gk-count"')


class AmountInWordsTests(TestCase):

    def test_indian_numbering(self):
        self.assertEqual(amount_in_words(Decimal('354.00')),
                         'Rupees Three Hundred Fifty Four Only')
        self.assertEqual(amount_in_words(Decimal('125000.50')),
                         'Rupees One Lakh Twenty Five Thousand and Fifty Paise Only')
