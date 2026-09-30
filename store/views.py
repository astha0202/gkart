from django.db.models import Avg, Count, Q, Value
from django.db.models.functions import Replace
from django.http import Http404
from django.shortcuts import render, get_object_or_404

from accounts.models import VendorProfile
from accounts.utils import get_vendor, visible_products
from quotations.forms import QuoteRequestForm
from reviews.forms import ReviewForm
from reviews.models import Review
from reviews.utils import annotate_ratings, has_verified_purchase, rating_histogram

from .models import Product, Category


def home(request):
    products = annotate_ratings(
        visible_products(request, Product.objects.filter(is_available=True))
    )
    categories = Category.objects.all()

    # Category filter
    selected_categories = request.GET.getlist('category')

    if selected_categories:
        products = products.filter(
            category_id__in=selected_categories
        )

    # Price filter
    price = request.GET.get('price')

    if price == 'under500':
        products = products.filter(price__lt=500)

    elif price == '500-1000':
        products = products.filter(price__gte=500, price__lte=1000)

    elif price == '1000-5000':
        products = products.filter(price__gte=1000, price__lte=5000)

    elif price == 'above5000':
        products = products.filter(price__gt=5000)

    # Availability filter
    availability = request.GET.get('availability')

    if availability == 'in_stock':
        products = products.filter(stock__gt=0)

    elif availability == 'out_stock':
        products = products.filter(stock=0)

    sort = request.GET.get('sort')

    if sort == 'price_low':
        products = products.order_by('price')

    elif sort == 'price_high':
        products = products.order_by('-price')

    elif sort == 'newest':
        products = products.order_by('-created_at')

    elif sort == 'oldest':
        products = products.order_by('created_at')

    elif sort == 'name_az':
        products = products.order_by('product_name')

    elif sort == 'name_za':
        products = products.order_by('-product_name')

    return render(
        request,
        'home.html',
        {
            'products': products,
            'categories': categories,
            'selected_categories': selected_categories,
            'selected_price': price,
            'selected_availability': availability,
        }
    )


def products(request):
    products = annotate_ratings(
        visible_products(request, Product.objects.filter(is_available=True))
    )
    return render(request, 'products.html', {'products': products})


def search(request):
    query = request.GET.get('q', '').strip()

    products = annotate_ratings(
        visible_products(request, Product.objects.filter(is_available=True))
    )

    if query:
        # Match individual words against name/description/category, e.g.
        # "blue shirt" finds products matching "blue" and/or "shirt".
        word_filter = Q()

        for word in query.split():
            word_filter |= (
                Q(product_name__icontains=word) |
                Q(description__icontains=word) |
                Q(category__category_name__icontains=word)
            )

        # Also match ignoring spaces, e.g. "smartwatch" finds "Smart Watch"
        # and "smart watch" finds "SmartWatch".
        normalized_query = query.replace(' ', '')

        products = products.annotate(
            normalized_name=Replace('product_name', Value(' '), Value(''))
        ).filter(
            word_filter | Q(normalized_name__icontains=normalized_query)
        ).distinct()

    return render(
        request,
        'search_results.html',
        {
            'products': products,
            'query': query,
        }
    )


def product_detail(request, slug):
    product = get_object_or_404(
        annotate_ratings(Product.objects.all()),
        slug=slug
    )

    vendor = get_vendor(request)

    # A signed-in vendor only ever browses their own catalogue.
    if vendor is not None and product.vendor_id != vendor.id:
        raise Http404('Product not found.')

    product_reviews = product.reviews.select_related('user').order_by('-created_at')
    histogram = rating_histogram(product)

    can_review = False
    user_review = None

    if request.user.is_authenticated:
        user_review = product_reviews.filter(user=request.user).first()

        if not user_review and has_verified_purchase(request.user, product):
            can_review = True

    return render(
        request,
        'product_detail.html',
        {
            'product': product,
            'reviews': product_reviews,
            'histogram': histogram,
            'can_review': can_review,
            'user_review': user_review,
            'review_form': ReviewForm(),
            'quote_form': QuoteRequestForm(
                account=request.user if request.user.is_authenticated else None
            ),
            'is_vendor_viewing': vendor is not None,
        }
    )


def vendor_store(request, store_slug):
    vendor = get_object_or_404(VendorProfile, slug=store_slug, is_approved=True)

    own_vendor = get_vendor(request)

    # Vendors cannot browse a competitor's storefront.
    if own_vendor is not None and own_vendor.id != vendor.id:
        raise Http404('Store not found.')

    products = annotate_ratings(
        Product.objects.filter(vendor=vendor, is_available=True)
    )

    store_rating = Review.objects.filter(product__vendor=vendor).aggregate(
        avg_rating=Avg('rating'),
        review_count=Count('id'),
    )

    return render(
        request,
        'store_detail.html',
        {
            'vendor': vendor,
            'products': products,
            'store_avg_rating': store_rating['avg_rating'],
            'store_review_count': store_rating['review_count'],
        }
    )


def categories(request):
    # Vendors see counts for their own catalogue only.
    # Product.category has no related_name, so the reverse accessor is `product`.
    product_filter = Q(product__is_available=True)

    vendor = get_vendor(request)

    if vendor is not None:
        product_filter &= Q(product__vendor=vendor)

    category_list = Category.objects.annotate(
        product_count=Count('product', filter=product_filter)
    ).order_by('category_name')

    return render(
        request,
        'categories.html',
        {'categories': category_list}
    )


def contact(request):
    return render(request, 'contact.html')
