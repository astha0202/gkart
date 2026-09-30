from .utils import get_vendor


def user_role(request):
    """Everything the templates need to tell a vendor from a buyer.

    Also carries the pending activation link, so it can be offered inline at
    the top of any page instead of only by email.
    """
    context = {
        'pending_activation': request.session.get('pending_activation'),
    }

    if not request.user.is_authenticated:
        context.update({
            'is_vendor_account': False,
            'vendor_profile': None,
            'account_home_url': 'account',
        })
        return context

    vendor = get_vendor(request)

    context.update({
        'is_vendor_account': vendor is not None,
        'vendor_profile': vendor,
        'quotes_url_name': 'quote_list_vendor' if vendor else 'quote_list_buyer',
        'account_home_url': 'vendor_details' if vendor else 'details',
        'dashboard_url_name': 'vendor_dashboard' if vendor else 'dashboard',
        'logout_url_name': 'vendor_logout' if vendor else 'logout',
        'is_email_verified': request.user.is_verified,
    })

    return context
