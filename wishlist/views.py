from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from accounts.utils import buyer_required
from cart.models import Cart
from store.models import Product
from .models import WishlistItem


@buyer_required
def wishlist(request):

    account = request.user

    wishlist_items = WishlistItem.objects.filter(
        account=account
    ).select_related("product")

    return render(
        request,
        "wishlist.html",
        {
            "account": account,
            "wishlist_items": wishlist_items,
        }
    )


@buyer_required
def add_to_wishlist(request, product_id):

    if request.method != "POST":
        return redirect("home")

    account = request.user

    product = get_object_or_404(
        Product,
        id=product_id
    )

    wishlist_item, created = WishlistItem.objects.get_or_create(
        account=account,
        product=product
    )

    if created:
        messages.success(
            request,
            f"{product.product_name} added to your wishlist."
        )
    else:
        messages.info(
            request,
            f"{product.product_name} is already in your wishlist."
        )

    return redirect(
        "product_detail",
        product.slug
    )


@buyer_required
def remove_from_wishlist(request, wishlist_item_id):

    if request.method != "POST":
        return redirect("wishlist")

    wishlist_item = get_object_or_404(
        WishlistItem,
        id=wishlist_item_id,
        account=request.user
    )

    product_name = wishlist_item.product.product_name

    wishlist_item.delete()

    messages.success(
        request,
        f"{product_name} was removed from your wishlist."
    )

    return redirect("wishlist")


@buyer_required
def move_to_cart(request, wishlist_item_id):
    """Put a saved product in the cart and take it off the wishlist."""

    if request.method != "POST":
        return redirect("wishlist")

    wishlist_item = get_object_or_404(
        WishlistItem,
        id=wishlist_item_id,
        account=request.user
    )

    product = wishlist_item.product

    if not product.is_available or product.stock < 1:
        messages.error(
            request,
            f"{product.product_name} is out of stock, so it could not be "
            f"moved to your cart. It is still saved in your wishlist."
        )
        return redirect("wishlist")

    cart_item, created = Cart.objects.get_or_create(
        account=request.user,
        product=product,
        defaults={"quantity": 1}
    )

    if not created:
        if cart_item.quantity >= product.stock:
            messages.warning(
                request,
                f"Your cart already holds all {product.stock} available "
                f"units of {product.product_name}."
            )
            return redirect("wishlist")

        cart_item.quantity += 1
        cart_item.save(update_fields=["quantity"])

    wishlist_item.delete()

    messages.success(
        request,
        f"{product.product_name} was moved to your cart."
    )

    return redirect("cart")


@buyer_required
def clear_wishlist(request):

    if request.method != "POST":
        return redirect("wishlist")

    deleted, _ = WishlistItem.objects.filter(
        account=request.user
    ).delete()

    if deleted:
        messages.success(request, "Your wishlist has been cleared.")
    else:
        messages.info(request, "Your wishlist was already empty.")

    return redirect("wishlist")


@buyer_required
def store(request):

    return redirect("products")
