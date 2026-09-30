from django import forms

from .models import Review
from .widgets import StarRatingWidget

RATING_CHOICES = [(5, '5'), (4, '4'), (3, '3'), (2, '2'), (1, '1')]


class ReviewForm(forms.ModelForm):
    rating = forms.ChoiceField(
        choices=RATING_CHOICES,
        widget=StarRatingWidget,
    )

    class Meta:
        model = Review
        fields = ['rating', 'title', 'body']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Summarize your review'
            }),
            'body': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'What did you like or dislike?'
            }),
        }
