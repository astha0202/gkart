"""Helpers for keeping the vendor and buyer experiences separated."""

from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from .models import VendorProfile


def get_vendor(request):
    """The VendorProfile of the logged-in user, or None for buyers/guests."""
    user = getattr(request, 'user', None)

    if user is None or not user.is_authenticated:
        return None

    # Cached per request so the many isolation checks cost one query at most.
    if not hasattr(request, '_vendor_profile'):
        request._vendor_profile = VendorProfile.objects.filter(
            account=user
        ).first()

    return request._vendor_profile


def is_vendor(request):
    return get_vendor(request) is not None


def vendor_required(view):
    """Only a logged-in, approved vendor may reach the wrapped view."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Please login to your vendor account first.')
            return redirect('vendor_login')

        vendor = get_vendor(request)

        if vendor is None:
            messages.error(
                request,
                'This page is only available to vendor accounts.'
            )
            return redirect('details')

        if not vendor.is_approved:
            messages.warning(
                request,
                'Your vendor account is waiting for approval.'
            )
            return redirect('vendor_login')

        request.vendor = vendor

        return view(request, *args, **kwargs)

    return wrapper


def buyer_required(view):
    """Block vendor accounts from buyer-only pages and send them to their own."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Please login first.')
            return redirect('login')

        if is_vendor(request):
            messages.info(
                request,
                'You are signed in as a vendor. '
                'Here is your vendor dashboard instead.'
            )
            return redirect('vendor_dashboard')

        return view(request, *args, **kwargs)

    return wrapper


def visible_products(request, queryset):
    """Restrict a product queryset to what the current account may browse.

    A signed-in vendor only ever sees their own catalogue; everybody else
    sees the whole storefront.
    """
    vendor = get_vendor(request)

    if vendor is None:
        return queryset

    return queryset.filter(vendor=vendor)
