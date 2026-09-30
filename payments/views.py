import razorpay

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from orders.models import Order
from cart.models import Cart
from .models import Payment
from .utils import get_razorpay_client
from accounts.utils import buyer_required


def _mark_order_paid(order):
    for order_product in order.order_products.select_related("product"):
        product = order_product.product
        product.stock = max(product.stock - order_product.quantity, 0)
        product.save()

        order_product.ordered = True
        order_product.save()

        Cart.objects.filter(
            account=order.account,
            product=product
        ).delete()


def verify_payment(request):

    if request.method != "POST":
        return redirect("cart")

    razorpay_payment_id = request.POST.get("razorpay_payment_id")
    razorpay_order_id = request.POST.get("razorpay_order_id")
    razorpay_signature = request.POST.get("razorpay_signature")

    payment = get_object_or_404(Payment, razorpay_order_id=razorpay_order_id)
    order = payment.order

    client = get_razorpay_client()

    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        })
    except razorpay.errors.SignatureVerificationError:
        payment.status = "Failed"
        payment.razorpay_payment_id = razorpay_payment_id or ""
        payment.save()

        messages.error(request, "Payment verification failed. Please try again.")
        return redirect("payment_failed", order_number=order.order_number)

    payment.razorpay_payment_id = razorpay_payment_id
    payment.razorpay_signature = razorpay_signature
    payment.status = "Success"
    payment.save()

    order.status = "Paid"
    order.is_ordered = True
    order.save()

    _mark_order_paid(order)

    request.session.pop("buy_now", None)
    request.session.pop("pending_order_id", None)

    messages.success(request, "Payment successful! Your order has been placed.")
    return redirect("payment_success", order_number=order.order_number)


@buyer_required
def cash_on_delivery(request, order_id):

    if request.method != "POST":
        return redirect("cart")

    account_id = request.user.id

    order = get_object_or_404(
        Order,
        id=order_id,
        account_id=account_id,
        is_ordered=False
    )

    order.status = "Cash on Delivery"
    order.is_ordered = True
    order.save()

    _mark_order_paid(order)

    request.session.pop("buy_now", None)
    request.session.pop("pending_order_id", None)

    messages.success(request, "Order placed successfully. Pay on delivery.")
    return redirect("payment_success", order_number=order.order_number)


def payment_success(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    return render(request, "payment_success.html", {"order": order})


def payment_failed(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    return render(request, "payment_failed.html", {"order": order})
