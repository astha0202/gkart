from django.test import TestCase
from django.urls import reverse

from accounts.tests import make_account, make_product, make_vendor
from cart.models import Cart

from .models import WishlistItem


class WishlistActionTests(TestCase):

    def setUp(self):
        self.vendor = make_vendor('vendorone', 'Vendor One')
        self.product = make_product(self.vendor, 'Test Widget')

        self.buyer = make_account('buyer', 'buyer@example.com')
        self.client.force_login(self.buyer)

        self.item = WishlistItem.objects.create(
            account=self.buyer, product=self.product
        )

    def test_page_has_no_dead_buttons(self):
        html = self.client.get(reverse('wishlist')).content.decode()

        # Both buttons were <a href="#"> placeholders.
        card = html[html.index('My Wishlist'):html.index('<footer')]

        self.assertNotIn('href="#"', card)
        self.assertIn(reverse('move_to_cart', args=[self.item.id]), card)
        self.assertIn(
            reverse('remove_from_wishlist', args=[self.item.id]), card
        )

    def test_move_to_cart_adds_to_cart_and_clears_the_wishlist_entry(self):
        response = self.client.post(
            reverse('move_to_cart', args=[self.item.id]), follow=True
        )

        self.assertRedirects(response, reverse('cart'))

        self.assertEqual(
            Cart.objects.get(account=self.buyer, product=self.product).quantity,
            1,
        )
        self.assertFalse(WishlistItem.objects.filter(pk=self.item.pk).exists())

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('moved to your cart', text)

    def test_move_to_cart_increments_an_existing_cart_line(self):
        Cart.objects.create(
            account=self.buyer, product=self.product, quantity=2
        )

        self.client.post(reverse('move_to_cart', args=[self.item.id]))

        self.assertEqual(
            Cart.objects.get(account=self.buyer, product=self.product).quantity,
            3,
        )

    def test_out_of_stock_product_is_kept_and_explained(self):
        self.product.stock = 0
        self.product.save(update_fields=['stock'])

        response = self.client.post(
            reverse('move_to_cart', args=[self.item.id]), follow=True
        )

        self.assertFalse(Cart.objects.filter(account=self.buyer).exists())
        self.assertTrue(WishlistItem.objects.filter(pk=self.item.pk).exists())

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('out of stock', text)

    def test_cart_already_holding_all_stock_is_explained(self):
        self.product.stock = 1
        self.product.save(update_fields=['stock'])

        Cart.objects.create(
            account=self.buyer, product=self.product, quantity=1
        )

        response = self.client.post(
            reverse('move_to_cart', args=[self.item.id]), follow=True
        )

        self.assertEqual(
            Cart.objects.get(account=self.buyer, product=self.product).quantity,
            1,
        )

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('already holds', text)

    def test_remove_deletes_the_entry(self):
        response = self.client.post(
            reverse('remove_from_wishlist', args=[self.item.id]), follow=True
        )

        self.assertFalse(WishlistItem.objects.filter(pk=self.item.pk).exists())

        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('removed from your wishlist', text)

    def test_clear_empties_the_wishlist(self):
        self.client.post(reverse('clear_wishlist'), follow=True)

        self.assertFalse(
            WishlistItem.objects.filter(account=self.buyer).exists()
        )

    def test_get_requests_do_not_crash(self):
        # These views used to be `pass` stubs, which raised
        # "view didn't return an HttpResponse object".
        for name in ('move_to_cart', 'clear_wishlist'):
            args = [self.item.id] if name == 'move_to_cart' else []

            response = self.client.get(reverse(name, args=args))

            self.assertEqual(response.status_code, 302, name)

    def test_another_buyer_cannot_touch_this_wishlist(self):
        self.client.force_login(make_account('other', 'other@example.com'))

        self.assertEqual(
            self.client.post(
                reverse('remove_from_wishlist', args=[self.item.id])
            ).status_code,
            404,
        )

        self.assertTrue(WishlistItem.objects.filter(pk=self.item.pk).exists())
