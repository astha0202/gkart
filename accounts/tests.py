from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from store.models import Product

from .models import Account, VendorProfile


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


def make_product(vendor, name, price='100.00'):
    return Product.objects.create(
        product_name=name,
        slug=name.lower().replace(' ', '-'),
        description='test product',
        price=Decimal(price),
        images='photos/products/test.jpg',
        stock=10,
        vendor=vendor,
        is_available=True,
    )


class VendorIsolationTests(TestCase):

    def setUp(self):
        self.mine = make_vendor('vendorone', 'Vendor One')
        self.theirs = make_vendor('vendortwo', 'Vendor Two')

        self.my_product = make_product(self.mine, 'My Widget')
        self.their_product = make_product(self.theirs, 'Their Widget')

    def test_vendor_only_sees_their_own_products_on_the_storefront(self):
        self.client.force_login(self.mine.account)

        for url in (
            reverse('home'),
            reverse('products'),
            reverse('search') + '?q=widget',
        ):
            response = self.client.get(url)

            self.assertContains(response, 'My Widget', msg_prefix=url)
            self.assertNotContains(response, 'Their Widget', msg_prefix=url)

    def test_buyer_still_sees_every_product(self):
        self.client.force_login(make_account('buyer', 'buyer@example.com'))

        response = self.client.get(reverse('products'))

        self.assertContains(response, 'My Widget')
        self.assertContains(response, 'Their Widget')

    def test_vendor_cannot_open_another_vendors_product_page(self):
        self.client.force_login(self.mine.account)

        self.assertEqual(
            self.client.get(
                reverse('product_detail', args=[self.their_product.slug])
            ).status_code,
            404,
        )

        self.assertEqual(
            self.client.get(
                reverse('product_detail', args=[self.my_product.slug])
            ).status_code,
            200,
        )

    def test_vendor_cannot_open_another_vendors_storefront(self):
        self.client.force_login(self.mine.account)

        self.assertEqual(
            self.client.get(
                reverse('vendor_store', args=[self.theirs.slug])
            ).status_code,
            404,
        )

    def test_vendor_is_sent_to_the_vendor_dashboard_not_the_buyer_one(self):
        self.client.force_login(self.mine.account)

        self.assertRedirects(
            self.client.get(reverse('dashboard')),
            reverse('vendor_dashboard'),
        )

    def test_vendor_never_sees_the_buyer_profile_page(self):
        self.client.force_login(self.mine.account)

        self.assertRedirects(
            self.client.get(reverse('details')),
            reverse('vendor_details'),
        )

        response = self.client.get(reverse('vendor_details'))

        self.assertContains(response, 'Vendor One')
        self.assertNotContains(response, 'My Wishlist')

    def test_buyer_cannot_reach_vendor_pages(self):
        self.client.force_login(make_account('buyer', 'buyer@example.com'))

        for name in (
            'vendor_dashboard',
            'vendor_products',
            'vendor_add_product',
            'vendor_profile',
            'vendor_details',
        ):
            response = self.client.get(reverse(name), follow=True)

            text = ' '.join(str(m) for m in response.context['messages'])

            self.assertIn(
                'only available to vendor accounts',
                text,
                msg=name,
            )


class AuthConsistencyTests(TestCase):

    def test_signed_out_hub_offers_login_and_sign_up_only(self):
        response = self.client.get(reverse('account'))

        self.assertContains(response, 'Login')
        self.assertContains(response, 'Sign Up')

        # Password recovery is a link, not a third call-to-action button.
        self.assertNotContains(response, '<h6>\n                            Forgot Password')

    def test_logged_in_buyer_is_taken_to_their_own_details(self):
        self.client.force_login(make_account('buyer', 'buyer@example.com'))

        self.assertRedirects(self.client.get(reverse('account')), reverse('details'))

    def test_logged_in_vendor_is_taken_to_their_own_details(self):
        vendor = make_vendor('vendorone', 'Vendor One')

        self.client.force_login(vendor.account)

        self.assertRedirects(
            self.client.get(reverse('account')), reverse('vendor_details')
        )

    def test_navbar_hides_login_signup_and_logout_once_signed_in(self):
        self.client.force_login(make_account('buyer', 'buyer@example.com'))

        response = self.client.get(reverse('home'))
        html = response.content.decode()

        for url in (
            reverse('login'),
            reverse('register'),
            reverse('logout'),
            reverse('vendor_login'),
            reverse('vendor_register'),
        ):
            self.assertNotIn(f'href="{url}"', html)

        # The account menu shows who is signed in instead.
        self.assertIn('Buyer', html)
        self.assertIn('buyer@example.com', html)

    def test_navbar_shows_login_and_sign_up_when_signed_out(self):
        html = self.client.get(reverse('home')).content.decode()

        self.assertIn('Log in', html)
        self.assertIn('Sign up', html)
        self.assertIn(f'href="{reverse("login")}"', html)
        self.assertIn(f'href="{reverse("register")}"', html)
        self.assertIn(f'href="{reverse("vendor_register")}"', html)

    def test_navbar_is_a_single_row_with_real_categories(self):
        from store.models import Category

        Category.objects.create(category_name='Electronics', slug='electronics')

        html = self.client.get(reverse('home')).content.decode()

        # One <nav>, not the old stacked pair.
        self.assertEqual(html.count('<nav class="gk-nav">'), 1)

        # Category menu comes from the database now.
        self.assertIn('Electronics', html)
        self.assertNotIn("Today's Deals", html)
        self.assertNotIn('Delivering to Ghaziabad', html)

    def test_vendor_navbar_shows_the_vendor_workspace(self):
        vendor = make_vendor('vendorone', 'Vendor One')

        self.client.force_login(vendor.account)

        html = self.client.get(reverse('home')).content.decode()

        self.assertIn('Vendor One', html)
        self.assertIn(f'href="{reverse("vendor_products")}"', html)
        self.assertIn(f'href="{reverse("quote_list_vendor")}"', html)

        # No shopper controls for a vendor.
        self.assertNotIn(f'href="{reverse("cart")}"', html)
        self.assertNotIn(f'href="{reverse("wishlist")}"', html)


class EmailVerificationTests(TestCase):

    def test_registering_shows_the_activation_link_inline(self):
        response = self.client.post(
            reverse('register'),
            {
                'full_name': 'New Buyer',
                'username': 'newbuyer',
                'email': 'new@example.com',
                'phone': '9876543210',
                'password': 'pass12345!',
                'confirm_password': 'pass12345!',
            },
            follow=True,
        )

        self.assertContains(response, 'Activate my account now')
        self.assertContains(response, '/account/activate/')

    def test_unverified_login_offers_the_activation_link_on_the_page(self):
        make_account('pending', 'pending@example.com', is_verified=False)

        response = self.client.post(
            reverse('login'),
            {'email': 'pending@example.com', 'password': 'pass12345!'},
            follow=True,
        )

        self.assertContains(response, 'Activate my account now')

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('not verified', text)

    def test_activating_verifies_the_account_and_drops_the_banner(self):
        account = make_account('pending', 'pending@example.com', is_verified=False)

        self.client.post(
            reverse('login'),
            {'email': 'pending@example.com', 'password': 'pass12345!'},
        )

        link = self.client.session['pending_activation']['link']

        response = self.client.get(link, follow=True)

        account.refresh_from_db()

        self.assertTrue(account.is_verified)
        self.assertNotIn('pending_activation', self.client.session)
        self.assertNotContains(response, 'Activate my account now')

    def test_verified_badge_is_shown_on_the_buyer_profile(self):
        self.client.force_login(make_account('buyer', 'buyer@example.com'))

        response = self.client.get(reverse('details'))

        self.assertContains(response, 'Verified')

    def test_verified_badge_is_shown_on_the_vendor_profile(self):
        vendor = make_vendor('vendorone', 'Vendor One')

        self.client.force_login(vendor.account)

        response = self.client.get(reverse('vendor_details'))

        self.assertContains(response, 'Email Verified')


class ErrorFeedbackTests(TestCase):
    """Failed actions must always say what went wrong."""

    def test_register_mismatched_passwords_reports_the_reason(self):
        response = self.client.post(
            reverse('register'),
            {
                'full_name': 'New Buyer',
                'username': 'newbuyer',
                'email': 'new@example.com',
                'phone': '9876543210',
                'password': 'pass12345!',
                'confirm_password': 'different!',
            },
            follow=True,
        )

        self.assertContains(response, 'Passwords do not match')
        self.assertFalse(Account.objects.filter(username='newbuyer').exists())

    def test_bad_login_reports_the_reason_on_the_page(self):
        make_account('buyer', 'buyer@example.com')

        response = self.client.post(
            reverse('login'),
            {'email': 'buyer@example.com', 'password': 'wrong'},
            follow=True,
        )

        self.assertContains(response, 'Invalid email or password')

    def test_forgot_password_for_unknown_email_reports_the_reason(self):
        response = self.client.post(
            reverse('forgot_password'),
            {'email': 'nobody@example.com'},
            follow=True,
        )

        self.assertContains(response, 'No account found with this email')


class BuyerAreaIsolationTests(TestCase):

    def setUp(self):
        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.client.force_login(self.vendor.account)

    def test_vendor_is_redirected_away_from_shopper_pages(self):
        for name in ('cart', 'checkout', 'orders', 'wishlist', 'quotation'):
            response = self.client.get(reverse(name), follow=True)

            self.assertRedirects(
                response,
                reverse('vendor_dashboard'),
                msg_prefix=name,
            )


class VendorProfileEditTests(TestCase):

    def setUp(self):
        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.client.force_login(self.vendor.account)

    def test_profile_saves(self):
        self.client.post(
            reverse('vendor_profile'),
            {
                'business_name': 'Vendor One Updated',
                'full_name': 'Owner Name',
                'phone_number': '9998887776',
                'business_description': 'We supply pipes.',
            },
        )

        self.vendor.refresh_from_db()

        self.assertEqual(self.vendor.business_name, 'Vendor One Updated')
        self.assertEqual(self.vendor.business_description, 'We supply pipes.')

    def test_invalid_profile_reports_the_reason_and_keeps_input(self):
        response = self.client.post(
            reverse('vendor_profile'),
            {
                'business_name': '',
                'full_name': 'Owner Name',
                'phone_number': 'abc',
                'business_description': 'Kept text.',
            },
        )

        self.assertContains(response, 'Business name is required')
        self.assertContains(response, 'Phone number must be 7-15 digits')
        self.assertContains(response, 'Kept text.')

        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.business_name, 'Vendor One')

    def test_email_is_read_only_on_the_profile(self):
        html = self.client.get(reverse('vendor_profile')).content.decode()

        self.assertIn('readonly', html)
        self.assertNotIn('name="email"', html)


class RegistrationInputTests(TestCase):

    def test_failed_registration_keeps_what_was_typed(self):
        response = self.client.post(
            reverse('register'),
            {
                'full_name': 'New Buyer',
                'username': 'newbuyer',
                'email': 'new@example.com',
                'phone': '9876543210',
                'password': 'pass12345!',
                'confirm_password': 'different!',
            },
        )

        self.assertContains(response, 'value="New Buyer"')
        self.assertContains(response, 'value="new@example.com"')
        self.assertContains(response, 'value="newbuyer"')

    def test_failed_vendor_registration_keeps_what_was_typed(self):
        response = self.client.post(
            reverse('vendor_register'),
            {
                'business_name': 'Alpha Traders',
                'business_type': 'dealer',
                'business_address': '5 Industrial Estate',
                'full_name': 'Owner Name',
                'username': 'alpha',
                'email': 'alpha@example.com',
                'phone': '9876543210',
                'password': 'pass12345!',
                'confirm_password': 'different!',
            },
        )

        self.assertContains(response, 'value="Alpha Traders"')
        self.assertContains(response, '5 Industrial Estate')
        self.assertContains(response, 'Passwords do not match')

    def test_vendor_registration_stores_type_and_address(self):
        self.client.post(
            reverse('vendor_register'),
            {
                'business_name': 'Alpha Traders',
                'business_type': 'dealer',
                'business_address': '5 Industrial Estate',
                'full_name': 'Owner Name',
                'username': 'alpha',
                'email': 'alpha@example.com',
                'phone': '9876543210',
                'password': 'pass12345!',
                'confirm_password': 'pass12345!',
            },
        )

        vendor = VendorProfile.objects.get(business_name='Alpha Traders')

        self.assertIn('Dealer', vendor.business_description)
        self.assertIn('5 Industrial Estate', vendor.business_description)


class AuthCrossLinkTests(TestCase):
    """Customer and vendor entry points must each offer a way across."""

    def test_login_pages_link_to_each_other(self):
        self.assertContains(
            self.client.get(reverse('login')),
            f'href="{reverse("vendor_login")}"',
        )

        self.assertContains(
            self.client.get(reverse('vendor_login')),
            f'href="{reverse("login")}"',
        )

    def test_sign_up_pages_link_to_each_other(self):
        self.assertContains(
            self.client.get(reverse('register')),
            f'href="{reverse("vendor_register")}"',
        )

        self.assertContains(
            self.client.get(reverse('vendor_register')),
            f'href="{reverse("register")}"',
        )


class CsrfRecoveryTests(TestCase):
    """A stale form must not dead-end on Django's raw 403 page.

    Django rotates the CSRF token on login, so a form left open in another tab
    (or reached with the back button) posts a token that no longer matches.
    """

    def _token(self, client, url):
        import re

        html = client.get(url).content.decode()
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)

        return match.group(1) if match else None

    def test_stale_token_redirects_back_with_an_explanation(self):
        from django.test import Client

        make_account('buyer', 'buyer@example.com')
        vendor = make_vendor('vendorone', 'Vendor One')

        client = Client(enforce_csrf_checks=True)

        # Tab 1: open the vendor login page.
        stale_token = self._token(client, reverse('vendor_login'))

        # Tab 2: sign in as a customer, which rotates the CSRF token.
        client.post(
            reverse('login'),
            {
                'email': 'buyer@example.com',
                'password': 'pass12345!',
                'csrfmiddlewaretoken': self._token(client, reverse('login')),
            },
        )

        # Tab 1: submit the now-stale form.
        response = client.post(
            reverse('vendor_login'),
            {
                'email': vendor.account.email,
                'password': 'pass12345!',
                'csrfmiddlewaretoken': stale_token,
            },
            HTTP_REFERER='http://testserver' + reverse('vendor_login'),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('session expired', text)

    def test_visiting_vendor_login_does_not_sign_a_customer_out(self):
        buyer = make_account('buyer', 'buyer@example.com')

        self.client.force_login(buyer)

        response = self.client.get(reverse('vendor_login'), follow=True)

        self.assertRedirects(response, reverse('details'))

        # Still signed in - the page no longer destroys the session.
        self.assertEqual(
            int(self.client.session['_auth_user_id']), buyer.id
        )

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('signed in as a customer', text)
