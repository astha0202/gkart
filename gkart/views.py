"""Project-level views."""

from django.contrib import messages
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def csrf_failure(request, reason=''):
    """Recover from a CSRF failure instead of showing Django's 403 page.

    This fires for ordinary, non-malicious reasons: a form left open in a tab
    while you signed in somewhere else (Django rotates the token on login),
    the back button after a login, or cookies being cleared. The user is sent
    back to the form - which re-renders with a fresh token - and told what
    happened, rather than hitting a dead end.
    """
    messages.error(
        request,
        'Your session expired while that page was open, so the form was not '
        'submitted for security reasons. Nothing was lost - please fill it in '
        'again on this fresh page.'
    )

    referer = request.META.get('HTTP_REFERER')

    if referer and url_has_allowed_host_and_scheme(
        url=referer,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(referer)

    # Fall back to the page the form posted to; these are all GET-able.
    return redirect(request.path or 'home')
