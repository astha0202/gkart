from django import template

register = template.Library()


@register.filter
def star_state(avg_rating, star_number):
    """Returns 'full', 'half' or 'empty' for read-only half-star display."""
    if avg_rating is None:
        avg_rating = 0

    rounded = round(float(avg_rating) * 2) / 2
    star_number = int(star_number)

    if rounded >= star_number:
        return 'full'

    if rounded >= star_number - 0.5:
        return 'half'

    return 'empty'
