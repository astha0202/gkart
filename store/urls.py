from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('products/', views.products, name='products'),
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),
    path('categories/', views.categories, name='categories'),
    path('contact/', views.contact, name='contact'),
    path('search/', views.search, name='search'),
    path('<slug:store_slug>/', views.vendor_store, name='vendor_store'),
]