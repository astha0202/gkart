from cart.models import Cart

from .models import Category


def navigation(request):
    """Real data for the top navigation.

    The category menu used to be nine hard-coded links that all pointed at the
    same page; it is now driven by the categories that actually exist.
    """
    context = {
        'nav_categories': Category.objects.all().order_by('category_name')[:10],
        'cart_item_count': 0,
    }

    user = getattr(request, 'user', None)

    if user is not None and user.is_authenticated:
        context['cart_item_count'] = Cart.objects.filter(
            account=user
        ).count()

    return context
