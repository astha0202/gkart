from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Account, UserProfile, Address, VendorProfile
@admin.register(Account)
class AccountAdmin(UserAdmin):
    list_display = (
        'username',
        'email',
        'first_name',
        'last_name',
        'is_staff',
        'is_active',
    )
    search_fields = (
        'username',
        'email',
        'first_name',
        'last_name',
    )

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        'account',
        'phone_number',
    )
@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = (
        'account',
        'city',
        'state',
        'pincode',
        'is_default',
    )
    list_filter = (
        'state',
        'city',
        'is_default',
    )
@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    list_display = (
        'account',
        'business_name',
        'phone_number',
        'is_approved',
    )
    list_filter = (
        'is_approved',
    )
    search_fields = (
        'business_name',
        'account__username',
        'account__email',
    )