from django.shortcuts import render

from accounts.utils import buyer_required

from .models import Order


@buyer_required
def orders(request):
    order_list = Order.objects.filter(
        account=request.user
    ).prefetch_related('order_products__product').order_by('-created_at')

    return render(request, 'orders.html', {'orders': order_list})