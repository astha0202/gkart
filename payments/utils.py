import razorpay
from django.conf import settings


def get_razorpay_client():
    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )


def create_razorpay_order(amount, order_id_for_notes):
    client = get_razorpay_client()

    return client.order.create({
        "amount": int(amount * 100),
        "currency": "INR",
        "payment_capture": 1,
        "notes": {"order_id": str(order_id_for_notes)},
    })
