from django.db.models import Avg, Count

from orders.models import OrderProduct


def has_verified_purchase(user, product):
    """A buyer may only review a product they actually paid for and had fulfilled."""
    if not user.is_authenticated:
        return False

    return OrderProduct.objects.filter(
        order__account=user,
        product=product,
        ordered=True,
    ).exists()


def annotate_ratings(queryset):
    """Attach avg_rating / review_count to a Product queryset for cards & listings."""
    return queryset.annotate(
        avg_rating=Avg('reviews__rating'),
        review_count=Count('reviews', distinct=True),
    )


def rating_histogram(product):
    """5 -> 1 star breakdown used on the product detail page."""
    counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}

    for row in product.reviews.values('rating').annotate(count=Count('id')):
        counts[row['rating']] = row['count']

    total = sum(counts.values())

    histogram = []
    for star in (5, 4, 3, 2, 1):
        count = counts[star]
        percent = round((count / total) * 100) if total else 0
        histogram.append({'star': star, 'count': count, 'percent': percent})

    return histogram
