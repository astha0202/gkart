from django.urls import path
from . import views


urlpatterns = [
    path('', views.wishlist, name='wishlist'),
    path('add/<int:product_id>/', views.add_to_wishlist, name='add_to_wishlist'),
    path('remove/<int:wishlist_item_id>/', views.remove_from_wishlist, name='remove_from_wishlist'),
    path('move_to_cart/<int:wishlist_item_id>/', views.move_to_cart, name='move_to_cart'),
    path('clear/', views.clear_wishlist, name='clear_wishlist'),
    path('store/', views.store, name='store'),
]