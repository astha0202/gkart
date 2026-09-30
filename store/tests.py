"""Smoke tests: every page still renders for each kind of visitor.

These catch template-level breakage (a bad {% url %}, a missing variable, a
mangled include) that unit tests on the views would not.
"""

from django.test import TestCase
from django.urls import reverse

from accounts.tests import make_account, make_product, make_vendor
from cart.models import Cart


class AnonymousPageTests(TestCase):

    def setUp(self):
        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.product = make_product(self.vendor, 'Test Widget')

    def test_public_pages_render(self):
        urls = [
            reverse('home'),
            reverse('products'),
            reverse('categories'),
            reverse('contact'),
            reverse('search') + '?q=widget',
            reverse('product_detail', args=[self.product.slug]),
            reverse('vendor_store', args=[self.vendor.slug]),
            reverse('account'),
            reverse('login'),
            reverse('register'),
            reverse('forgot_password'),
            reverse('vendor_login'),
            reverse('vendor_register'),
            reverse('vendor_forgot_password'),
        ]

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class BuyerPageTests(TestCase):

    def setUp(self):
        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.product = make_product(self.vendor, 'Test Widget')

        self.buyer = make_account('buyer', 'buyer@example.com')
        self.client.force_login(self.buyer)

        Cart.objects.create(
            account=self.buyer, product=self.product, quantity=2
        )
        self.client.session['account_id'] = self.buyer.id

    def test_buyer_pages_render(self):
        session = self.client.session
        session['account_id'] = self.buyer.id
        session.save()

        urls = [
            reverse('home'),
            reverse('details'),
            reverse('dashboard'),
            reverse('cart'),
            reverse('checkout'),
            reverse('quotation'),
            reverse('quote_list_buyer'),
            reverse('quote_request_create', args=[self.product.slug]),
            reverse('orders'),
            reverse('wishlist'),
            reverse('notification_list'),
            reverse('address'),
            reverse('my_reviews'),
            reverse('product_detail', args=[self.product.slug]),
        ]

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class VendorPageTests(TestCase):

    def setUp(self):
        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.product = make_product(self.vendor, 'Test Widget')

        self.client.force_login(self.vendor.account)

        session = self.client.session
        session['account_id'] = self.vendor.account.id
        session.save()

    def test_vendor_pages_render(self):
        urls = [
            reverse('home'),
            reverse('vendor_dashboard'),
            reverse('vendor_details'),
            reverse('vendor_products'),
            reverse('vendor_add_product'),
            reverse('vendor_profile'),
            reverse('vendor_edit_product', args=[self.product.id]),
            reverse('quote_list_vendor'),
            reverse('notification_list'),
            reverse('product_detail', args=[self.product.slug]),
        ]

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class CategoryNavigationTests(TestCase):

    def setUp(self):
        from store.models import Category

        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.category = Category.objects.create(
            category_name='Electronics', slug='electronics'
        )

        product = make_product(self.vendor, 'Test Widget')
        product.category = self.category
        product.save()

    def test_nav_category_menu_links_to_a_filtered_catalogue(self):
        html = self.client.get(reverse('home')).content.decode()

        self.assertIn(
            f'href="{reverse("home")}?category={self.category.id}"',
            html,
        )

    def test_categories_page_lists_categories_with_counts(self):
        response = self.client.get(reverse('categories'))

        self.assertContains(response, 'Electronics')
        self.assertContains(response, '1 product')
        self.assertNotContains(response, 'Your categories page content goes here')


class ProductPageTests(TestCase):

    def setUp(self):
        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.product = make_product(self.vendor, 'Test Widget')

        self.buyer = make_account('buyer', 'buyer@example.com')
        self.client.force_login(self.buyer)

    def test_only_one_quantity_field(self):
        html = self.client.get(
            reverse('product_detail', args=[self.product.slug])
        ).content.decode()

        # A duplicate id meant getElementById found an orphan field outside
        # every form, so Buy Now ignored the quantity that was typed.
        self.assertEqual(html.count('id="productQuantity"'), 1)
        self.assertEqual(html.count('name="quantity"'), 2)  # cart + buy-now hidden

    def test_no_request_quotation_button(self):
        response = self.client.get(
            reverse('product_detail', args=[self.product.slug])
        )

        self.assertNotContains(response, 'Request Quotation')
        self.assertNotContains(
            response,
            reverse('quote_request_create', args=[self.product.slug]),
        )

    def test_quantity_field_is_inside_the_add_to_cart_form(self):
        html = self.client.get(
            reverse('product_detail', args=[self.product.slug])
        ).content.decode()

        form_start = html.index(reverse('add_to_cart', args=[self.product.id]))
        form_end = html.index('</form>', form_start)

        self.assertIn('id="productQuantity"', html[form_start:form_end])


class FooterTests(TestCase):

    def test_footer_has_no_placeholder_links(self):
        html = self.client.get(reverse('home')).content.decode()

        footer = html[html.index('<footer'):]

        self.assertNotIn('href="#"', footer)
        self.assertNotIn('home.html', footer)
        self.assertIn(reverse('contact'), footer)
        self.assertIn(reverse('products'), footer)
