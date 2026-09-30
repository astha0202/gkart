from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'order',
        'razorpay_order_id',
        'razorpay_payment_id',
        'amount',
        'status',
        'created_at'
    )

    list_filter = ('status', 'created_at')
    search_fields = (
        'order__order_number',
        'razorpay_order_id',
        'razorpay_payment_id'
    )
