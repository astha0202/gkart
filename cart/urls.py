from django.urls import path

from quotations import views as quotation_views

from . import views

urlpatterns = [

    path(
        "",
        views.cart,
        name="cart"
    ),

    path(
        "add/<int:product_id>/",
        views.add_to_cart,
        name="add_to_cart"
    ),

    path(
        "remove/<int:cart_id>/",
        views.remove_from_cart,
        name="remove_from_cart"
    ),

    path(
        "update/<int:cart_id>/",
        views.update_cart,
        name="update_cart"
    ),
    path(
        "buy-now/<int:product_id>/",
        views.buy_now,
        name="buy_now"
    ),
    path(
        "checkout/",
        views.checkout,
        name="checkout"
    ),
    path(
        "payment/",
        views.payment_page,
        name="payment"
    ),
    path(
        "quotation/",
        quotation_views.quote_request_page,
        name="quotation"
    ),
]