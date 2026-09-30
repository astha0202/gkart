from django import forms


class StarRatingWidget(forms.RadioSelect):
    """Renders 1-5 radio inputs as clickable stars (see static/css/style.css: .star-rating)."""
    template_name = 'widgets/star_rating_widget.html'
    option_template_name = 'widgets/star_rating_option.html'
