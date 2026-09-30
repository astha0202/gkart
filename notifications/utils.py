from .models import Notification


def notify(recipient, message, link=''):
    """Create an in-app notification for a single recipient account."""
    return Notification.objects.create(
        recipient=recipient,
        message=message,
        link=link,
    )
