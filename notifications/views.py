from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve

from .models import Notification


def _is_usable(link):
    """True when a stored link still matches a route on this site."""
    if not link.startswith('/'):
        return False

    try:
        resolve(link)
    except Resolver404:
        return False

    return True


@login_required(login_url='login')
def notification_list(request):
    notifications = Notification.objects.filter(recipient=request.user)

    return render(
        request,
        'notifications/notification_list.html',
        {'notifications': notifications}
    )


@login_required(login_url='login')
def notification_read(request, pk):
    notification = get_object_or_404(
        Notification,
        pk=pk,
        recipient=request.user
    )

    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=['is_read'])

    if notification.link:
        if _is_usable(notification.link):
            return redirect(notification.link)

        # An old notification can outlive the page it pointed at; say so
        # rather than dropping the user on a 404.
        messages.warning(
            request,
            'That notification points to a page that no longer exists.'
        )

    return redirect('notification_list')


@login_required(login_url='login')
def mark_all_notifications_read(request):
    Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).update(is_read=True)

    return redirect('notification_list')
