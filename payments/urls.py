from django.urls import path
from . import views

urlpatterns = [

    path(
        "verify/",
        views.verify_payment,
        name="verify_payment"
    ),

    path(
        "cod/<int:order_id>/",
        views.cash_on_delivery,
        name="cod_payment"
    ),

    path(
        "success/<str:order_number>/",
        views.payment_success,
        name="payment_success"
    ),

    path(
        "failed/<str:order_number>/",
        views.payment_failed,
        name="payment_failed"
    ),
]
