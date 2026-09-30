from django.urls import path

from . import views

urlpatterns = [
    path('mine/', views.my_reviews, name='my_reviews'),
    path('product/<int:product_id>/add/', views.review_create, name='review_create'),
    path('<int:review_id>/edit/', views.review_edit, name='review_edit'),
    path('<int:review_id>/delete/', views.review_delete, name='review_delete'),
]
