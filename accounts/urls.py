from django.urls import path
from . import views

urlpatterns = [
    path('', views.account, name='account'),
    path('account/',views.account, name='account'),
    path('register/', views.register, name='register'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),
    path('reset-password/<uidb64>/<token>/',views.reset_password,name='reset_password'),
    path('address/', views.address, name='address'),
    path('vendor_register/', views.vendor_register, name='vendor_register'),
    path('vendor_login/', views.vendor_login, name='vendor_login'),
    path('vendor_logout/', views.vendor_logout, name='vendor_logout'),
    path('vendor_dashboard/', views.vendor_dashboard, name='vendor_dashboard'),
    path('vendor/products/', views.vendor_products, name='vendor_products'),
    path('address/edit/<int:address_id>/', views.edit_address, name='edit_address'),
    path('address/delete/<int:address_id>/', views.delete_address, name='delete_address'),
    path('vendor/add-product/', views.vendor_add_product, name='vendor_add_product'),
    path('vendor/profile/', views.vendor_profile, name='vendor_profile'),
    path(
        'vendor/profile/<str:section>/clear/',
        views.vendor_profile_section_clear,
        name='vendor_profile_section_clear'
    ),
    path('vendor/products/edit/<int:product_id>/', views.vendor_edit_product, name='vendor_edit_product'),
    path('vendor/products/delete/<int:product_id>/', views.vendor_delete_product, name='vendor_delete_product'),
    path('details/', views.details, name='details'),
    path('vendor/details/', views.vendor_details, name='vendor_details'),
    path('dashboard/', views.buyer_dashboard, name='dashboard'),
    path('activation-sent/', views.activation_sent, name='activation_sent'),
    path('vendor/activation-sent/', views.vendor_activation_sent, name='vendor_activation_sent'),
    path('activate/<uidb64>/<token>/', views.activate_account, name='activate_account'),
    path('resend-activation/', views.resend_activation, name='resend_activation'),
    path('vendor/activate/<uidb64>/<token>/', views.vendor_activate, name='vendor_activate'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('vendor/forgot-password/', views.vendor_forgot_password, name='vendor_forgot_password'),
    path('vendor/reset-password/<uidb64>/<token>/', views.vendor_reset_password, name='vendor_reset_password'),
]