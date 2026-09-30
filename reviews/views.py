from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from store.models import Product

from .forms import ReviewForm
from .models import Review
from .utils import has_verified_purchase


@login_required(login_url='login')
def review_create(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if not has_verified_purchase(request.user, product):
        messages.error(
            request,
            'You can only review products from a paid or delivered order.'
        )
        return redirect('product_detail', slug=product.slug)

    if Review.objects.filter(user=request.user, product=product).exists():
        messages.error(request, 'You have already reviewed this product.')
        return redirect('product_detail', slug=product.slug)

    if request.method != 'POST':
        return redirect('product_detail', slug=product.slug)

    form = ReviewForm(request.POST)

    if form.is_valid():
        review = form.save(commit=False)
        review.user = request.user
        review.product = product
        review.is_verified_purchase = True
        review.save()

        messages.success(request, 'Thank you! Your review has been posted.')
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)

    return redirect('product_detail', slug=product.slug)


@login_required(login_url='login')
def review_edit(request, review_id):
    review = get_object_or_404(Review, id=review_id, user=request.user)

    if request.method == 'POST':
        form = ReviewForm(request.POST, instance=review)

        if form.is_valid():
            form.save()
            messages.success(request, 'Review updated.')
            return redirect('product_detail', slug=review.product.slug)

        messages.error(request, 'Please correct the errors below.')
    else:
        form = ReviewForm(instance=review)

    return render(request, 'reviews/review_edit.html', {'form': form, 'review': review})


@login_required(login_url='login')
def review_delete(request, review_id):
    review = get_object_or_404(Review, id=review_id, user=request.user)

    if request.method == 'POST':
        product_slug = review.product.slug
        review.delete()
        messages.success(request, 'Review deleted.')
        return redirect('product_detail', slug=product_slug)

    return redirect('my_reviews')


@login_required(login_url='login')
def my_reviews(request):
    reviews = Review.objects.filter(user=request.user).select_related('product')
    return render(request, 'reviews/my_reviews.html', {'reviews': reviews})
