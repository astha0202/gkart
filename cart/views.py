import uuid

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings

from store.models import Product
from orders.models import Order, OrderProduct
from payments.models import Payment
from payments.utils import create_razorpay_order
from accounts.utils import buyer_required

from .models import Cart


# =========================
# CART PAGE
# =========================
@buyer_required
def cart(request):

    account = request.user

    cart_items = Cart.objects.filter(
        account=account
    ).select_related("product")

    total = 0

    for item in cart_items:
        item.subtotal = item.product.price * item.quantity
        total += item.subtotal

    return render(
        request,
        "cart.html",
        {
            "cart_items": cart_items,
            "total": total,
        }
    )

# =========================
# ADD TO CART
# =========================

@buyer_required
def add_to_cart(request, product_id):

    if request.method != "POST":
        return redirect("home")

    account = request.user

    product = get_object_or_404(
        Product,
        id=product_id
    )

    quantity = int(
        request.POST.get("quantity", 1)
    )

    if quantity < 1:
        quantity = 1

    if quantity > product.stock:

        messages.error(
            request,
            f"Only {product.stock} items available."
        )

        return redirect(
            "product_detail",
            product.slug
        )

    cart_item, created = Cart.objects.get_or_create(
        account=account,
        product=product,
        defaults={
            "quantity": quantity
        }
    )

    if not created:

        cart_item.quantity += quantity

        if cart_item.quantity > product.stock:
            cart_item.quantity = product.stock

        cart_item.save()

    messages.success(
        request,
        f"{product.product_name} added to cart."
    )

    return redirect("cart")


# =========================
# REMOVE FROM CART
# =========================

@buyer_required
def remove_from_cart(request, cart_id):

    account_id = request.user.id

    cart_item = get_object_or_404(
        Cart,
        id=cart_id,
        account_id=account_id
    )

    cart_item.delete()

    messages.success(
        request,
        "Product removed from cart."
    )

    return redirect("cart")


# =========================
# UPDATE CART QUANTITY
# =========================

@buyer_required
def update_cart(request, cart_id):

    if request.method != "POST":
        return redirect("cart")

    account_id = request.user.id

    cart_item = get_object_or_404(
        Cart,
        id=cart_id,
        account_id=account_id
    )

    quantity = int(
        request.POST.get("quantity", 1)
    )

    if quantity < 1:
        quantity = 1

    if quantity > cart_item.product.stock:

        messages.error(
            request,
            f"Only {cart_item.product.stock} items available."
        )

        return redirect("cart")

    cart_item.quantity = quantity
    cart_item.save()

    messages.success(
        request,
        "Cart updated successfully."
    )

    return redirect("cart")

# =========================
# BUY NOW
# =========================
# =========================
# BUY NOW
# =========================

@buyer_required
def buy_now(request, product_id):

    product = get_object_or_404(
        Product,
        id=product_id
    )

    if request.method != "POST":
        return redirect(
            "product_detail",
            product.slug
        )

    account_id = request.user.id

    try:
        quantity = int(
            request.POST.get("quantity", 1)
        )
    except (TypeError, ValueError):
        quantity = 1

    if quantity < 1:
        quantity = 1

    if not product.is_available or product.stock < 1:
        messages.error(
            request,
            f"{product.product_name} is currently out of stock."
        )
        return redirect(
            "product_detail",
            product.slug
        )

    if quantity > product.stock:
        messages.error(
            request,
            f"Only {product.stock} items are available."
        )
        return redirect(
            "product_detail",
            product.slug
        )

    request.session["buy_now"] = {
        "product_id": product.id,
        "quantity": quantity,
    }

    return redirect("checkout")

    if request.method != "POST":
        return redirect("product_detail", product_id)

    account = request.user

    product = get_object_or_404(
        Product,
        id=product_id
    )

    # Get quantity from product detail page
    try:
        quantity = int(
            request.POST.get("quantity", 1)
        )
    except (TypeError, ValueError):
        quantity = 1

    if quantity < 1:
        quantity = 1

    # Check stock
    if not product.is_available or product.stock < 1:
        messages.error(
            request,
            f"{product.product_name} is currently out of stock."
        )
        return redirect(
            "product_detail",
            product.slug
        )

    if quantity > product.stock:
        messages.error(
            request,
            f"Only {product.stock} items are available."
        )
        return redirect(
            "product_detail",
            product.slug
        )

    # Save Buy Now product separately in session.
    # It will NOT be added to the normal cart.
    request.session["buy_now"] = {
        "product_id": product.id,
        "quantity": quantity,
    }

    return redirect("checkout")

    if request.method != "POST":
        return redirect("product_detail", product_id)

    account = request.user

    product = get_object_or_404(
        Product,
        id=product_id
    )

    # Get quantity from product detail page
    try:
        quantity = int(
            request.POST.get("quantity", 1)
        )
    except (TypeError, ValueError):
        quantity = 1

    if quantity < 1:
        quantity = 1

    # Check stock
    if not product.is_available or product.stock < 1:
        messages.error(
            request,
            f"{product.product_name} is currently out of stock."
        )
        return redirect(
            "product_detail",
            product.slug
        )

    if quantity > product.stock:
        messages.error(
            request,
            f"Only {product.stock} items are available."
        )
        return redirect(
            "product_detail",
            product.slug
        )

    # Save Buy Now product separately in session.
    # It will NOT be added to the normal cart.
    request.session["buy_now"] = {
        "product_id": product.id,
        "quantity": quantity,
    }

    return redirect("checkout")

# =========================
# CHECKOUT
# =========================

@buyer_required
def checkout(request):

    account = request.user

    checkout_items = []
    total = 0

    # ---------------------------------
    # BUY NOW CHECKOUT
    # ---------------------------------

    buy_now_data = request.session.get("buy_now")

    if buy_now_data:

        product = get_object_or_404(
            Product,
            id=buy_now_data["product_id"]
        )

        quantity = buy_now_data["quantity"]

        if quantity > product.stock:
            messages.error(
                request,
                f"Only {product.stock} items are available."
            )

            request.session.pop("buy_now", None)

            return redirect(
                "product_detail",
                product.slug
            )

        subtotal = product.price * quantity

        checkout_items.append({
            "product": product,
            "quantity": quantity,
            "subtotal": subtotal,
        })

        total = subtotal

        checkout_type = "buy_now"

    # ---------------------------------
    # NORMAL CART CHECKOUT
    # ---------------------------------

    else:

        cart_items = Cart.objects.filter(
            account=account
        ).select_related("product")

        for item in cart_items:

            if item.quantity > item.product.stock:

                messages.error(
                    request,
                    f"Only {item.product.stock} "
                    f"{item.product.product_name} available."
                )

                return redirect("cart")

            subtotal = (
                item.product.price *
                item.quantity
            )

            checkout_items.append({
                "product": item.product,
                "quantity": item.quantity,
                "subtotal": subtotal,
            })

            total += subtotal

        checkout_type = "cart"

    # ---------------------------------
    # EMPTY CHECKOUT
    # ---------------------------------

    if not checkout_items:

        messages.error(
            request,
            "Your checkout is empty."
        )

        return redirect("cart")

    # Default address
    address = (
        account.addresses
        .filter(is_default=True)
        .first()
    )

    return render(
        request,
        "checkout.html",
        {
            "account": account,
            "checkout_items": checkout_items,
            "total": total,
            "address": address,
            "checkout_type": checkout_type,
        }
    )

@buyer_required
def payment_page(request):

    account = request.user

    checkout_items = []
    total = 0

    buy_now_data = request.session.get("buy_now")

    if buy_now_data:

        product = get_object_or_404(Product, id=buy_now_data["product_id"])
        quantity = buy_now_data["quantity"]

        if quantity > product.stock:
            messages.error(
                request,
                f"Only {product.stock} items are available."
            )
            request.session.pop("buy_now", None)
            return redirect("product_detail", product.slug)

        subtotal = product.price * quantity

        checkout_items.append({
            "product": product,
            "quantity": quantity,
            "subtotal": subtotal,
        })

        total = subtotal

    else:

        cart_items = Cart.objects.filter(
            account=account
        ).select_related("product")

        for item in cart_items:

            if item.quantity > item.product.stock:
                messages.error(
                    request,
                    f"Only {item.product.stock} "
                    f"{item.product.product_name} available."
                )
                return redirect("cart")

            subtotal = item.product.price * item.quantity

            checkout_items.append({
                "product": item.product,
                "quantity": item.quantity,
                "subtotal": subtotal,
            })

            total += subtotal

    if not checkout_items:
        messages.error(request, "Your checkout is empty.")
        return redirect("cart")

    # Reuse a pending order from this session if the cart hasn't changed,
    # so refreshing the payment page doesn't create duplicate orders.
    pending_order_id = request.session.get("pending_order_id")
    order = None

    if pending_order_id:
        order = Order.objects.filter(
            id=pending_order_id,
            account=account,
            is_ordered=False,
            total_amount=total
        ).first()

    if not order:

        address = account.addresses.filter(is_default=True).first()

        order = Order.objects.create(
            account=account,
            address=address,
            order_number=uuid.uuid4().hex[:12].upper(),
            total_amount=total,
            status="Pending",
            is_ordered=False,
        )

        for item in checkout_items:
            OrderProduct.objects.create(
                order=order,
                product=item["product"],
                quantity=item["quantity"],
                product_price=item["product"].price,
            )

        request.session["pending_order_id"] = order.id

    payment = Payment.objects.filter(order=order, status="Created").first()

    if not payment:
        razorpay_order = create_razorpay_order(total, order.id)
        payment = Payment.objects.create(
            order=order,
            razorpay_order_id=razorpay_order["id"],
            amount=total,
            status="Created",
        )

    return render(
        request,
        "payment.html",
        {
            "order": order,
            "checkout_items": checkout_items,
            "total": total,
            "razorpay_key_id": settings.RAZORPAY_KEY_ID,
            "razorpay_order_id": payment.razorpay_order_id,
            "amount_paise": int(total * 100),
        }
    )
