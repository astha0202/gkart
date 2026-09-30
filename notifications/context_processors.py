from .models import Notification

RECENT_LIMIT = 6

# Every quotation notification links somewhere under this prefix.
QUOTATION_LINK_PREFIX = '/quotations/'


def unread_notification_count(request):
    """Unread counts + the latest few notifications for the navbar."""
    if not request.user.is_authenticated:
        return {}

    mine = Notification.objects.filter(recipient=request.user)
    unread = mine.filter(is_read=False)

    return {
        'unread_notification_count': unread.count(),
        'unread_quotation_count': unread.filter(
            link__startswith=QUOTATION_LINK_PREFIX
        ).count(),
        'recent_notifications': mine[:RECENT_LIMIT],
    }
