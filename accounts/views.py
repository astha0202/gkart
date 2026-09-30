from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404
from django.contrib import messages
from django.contrib.auth import authenticate, login as django_login, logout as django_logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Avg, Count
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.utils.text import slugify

from orders.models import Order
from quotations.models import ProformaInvoice, PurchaseOrder, Quote
from reviews.models import Review
from notifications.models import Notification
from store.models import DEFAULT_GST_RATE, GST_SLAB_CHOICES, Category, Product
from .forms import PROFILE_SECTIONS, VendorBusinessForm
from .models import Account, UserProfile, Address, VendorProfile
from .utils import buyer_required, get_vendor, vendor_required


def _gst_rate_from_post(request, default=DEFAULT_GST_RATE):
    """The GST slab picked on a product form, or `default` if it is not a real slab."""
    posted = request.POST.get('gst_rate', '')

    for value, _label in GST_SLAB_CHOICES:
        if posted == str(value) or posted == str(int(value)):
            return value

    return default


# =========================================================
# ACTIVATION LINK HELPERS
# =========================================================

def build_activation_link(request, account, url_name):
    uid = urlsafe_base64_encode(force_bytes(account.pk))
    token = default_token_generator.make_token(account)

    return request.build_absolute_uri(
        reverse(url_name, kwargs={'uidb64': uid, 'token': token})
    )


def remember_activation_link(request, account, link, is_vendor=False):
    """Keep the activation link in the session so it can be shown inline.

    Email delivery is unreliable in this setup, so the link is also rendered
    at the top of every page until the account has been activated.
    """
    request.session['pending_activation'] = {
        'email': account.email,
        'link': link,
        'is_vendor': is_vendor,
    }


def clear_activation_link(request):
    request.session.pop('pending_activation', None)


BUSINESS_TYPES = [
    ('dealer', 'Dealer'),
    ('manufacturer', 'Manufacturer'),
    ('supplier', 'Supplier'),
    ('retailer', 'Retailer'),
    ('other', 'Other'),
]


# =========================================================
# CUSTOMER REGISTER
# =========================================================
def register(request):

    if request.user.is_authenticated:
        return redirect('details')

    if request.method == 'POST':

        full_name = request.POST.get('full_name', '').strip()
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip().lower()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        entered = {
            'full_name': full_name,
            'username': username,
            'email': email,
            'phone': phone,
        }

        def reject(reason):
            messages.error(request, reason)
            return render(request, 'register.html', {'entered': entered})

        # -----------------------------
        # REQUIRED FIELDS
        # -----------------------------
        if not all([
            full_name,
            username,
            email,
            phone,
            password,
            confirm_password
        ]):
            return reject('Please fill all fields.')

        # -----------------------------
        # PASSWORD MATCH
        # -----------------------------
        if password != confirm_password:
            return reject('Passwords do not match.')

        # -----------------------------
        # EMAIL CHECK
        # -----------------------------
        if Account.objects.filter(email=email).exists():
            return reject('Email already registered.')

        # -----------------------------
        # USERNAME CHECK
        # -----------------------------
        if Account.objects.filter(username=username).exists():
            return reject('Username already exists.')

        # -----------------------------
        # CREATE ACCOUNT
        # -----------------------------
        account = Account.objects.create_user(
            username=username,
            email=email,
            password=password,
            full_name=full_name,
            phone=phone,
            is_verified=False,
            is_active=True
        )

        # -----------------------------
        # CREATE ACTIVATION LINK
        # -----------------------------
        activation_link = build_activation_link(
            request,
            account,
            'activate_account'
        )

        remember_activation_link(request, account, activation_link)

        # -----------------------------
        # SEND ACTIVATION EMAIL
        # -----------------------------
        try:
            send_mail(
                subject='Greatkart - Activate Your Account',
                message=(
                    f'Hello {full_name},\n\n'
                    f'Thank you for registering with Greatkart.\n\n'
                    f'Please click the link below to activate your account:\n\n'
                    f'{activation_link}\n\n'
                    f'After activation, you can login to your account.\n\n'
                    f'If you did not create this account, please ignore this email.'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False
            )

            messages.success(
                request,
                'Account created. We have emailed you an activation link - '
                'it is also shown on this page.'
            )

        except Exception as e:
            # The account exists either way, so the user gets the link here
            # rather than being bounced back to an empty registration form.
            messages.warning(
                request,
                f'Your account was created, but the activation email could '
                f'not be sent ({e}). Use the activation link shown on this '
                f'page instead.'
            )

        return redirect('activation_sent')

    # -----------------------------
    # GET REQUEST
    # -----------------------------
    return render(
        request,
        'register.html'
    )


# =========================================================
# ACTIVATION LINK PAGES
# =========================================================

def activation_sent(request):
    pending = request.session.get('pending_activation')

    if not pending:
        messages.info(
            request,
            'There is no activation pending. Please register or login.'
        )
        return redirect('login')

    return render(request, 'activation_sent.html', {'pending': pending})


def vendor_activation_sent(request):
    pending = request.session.get('pending_activation')

    if not pending:
        messages.info(
            request,
            'There is no activation pending. Please register or login.'
        )
        return redirect('vendor_login')

    return render(request, 'vendor_activation_sent.html', {'pending': pending})
# =========================================================
# CUSTOMER ACCOUNT ACTIVATION
# =========================================================

def activate_account(request, uidb64, token):

    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        account = Account.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, Account.DoesNotExist):
        account = None

    if account is None:
        messages.error(
            request,
            'Invalid activation link.'
        )
        return redirect('login')

    if account.is_verified:
        messages.info(
            request,
            'Your account is already activated.'
        )
        return redirect('login')

    if not default_token_generator.check_token(
        account,
        token
    ):
        messages.error(
            request,
            'This activation link is invalid or has expired.'
        )
        return redirect('login')

    account.is_verified = True
    account.save(update_fields=['is_verified'])

    clear_activation_link(request)

    messages.success(
        request,
        'Your email has been verified and your account is now active. '
        'You can login.'
    )

    return redirect('login')


# =========================================================
# RESEND CUSTOMER ACTIVATION LINK
# =========================================================

def resend_activation(request):

    if request.method != 'POST':
        return redirect('login')

    email = request.POST.get(
        'email',
        ''
    ).strip().lower()

    if not email:
        messages.error(
            request,
            'Please enter your email.'
        )
        return redirect('login')

    try:
        account = Account.objects.get(
            email=email
        )
    except Account.DoesNotExist:
        messages.error(
            request,
            'No account found with this email.'
        )
        return redirect('login')

    if account.is_verified:
        messages.info(
            request,
            'Your account is already activated.'
        )
        return redirect('login')

    activation_link = build_activation_link(
        request,
        account,
        'activate_account'
    )

    remember_activation_link(request, account, activation_link)

    try:
        send_mail(
            subject='Greatkart - Account Activation Link',
            message=(
                f'Hello {account.full_name},\n\n'
                f'Click the link below to activate your account:\n\n'
                f'{activation_link}\n\n'
                f'If you did not request this link, ignore this email.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[account.email],
            fail_silently=False
        )

        messages.success(
            request,
            'A new activation link has been sent to your email. '
            'It is also shown at the top of this page.'
        )

    except Exception as e:
        messages.warning(
            request,
            f'We could not send the activation email ({e}). '
            f'Use the activation link shown at the top of this page.'
        )

    return redirect('login')


# =========================================================
# CUSTOMER LOGIN
# =========================================================

def login(request):

    if request.user.is_authenticated:
        return redirect('details')

    if request.method == 'POST':

        email = request.POST.get(
            'email',
            ''
        ).strip().lower()

        password = request.POST.get(
            'password'
        )

        try:
            account = Account.objects.get(
                email=email
            )
        except Account.DoesNotExist:
            messages.error(
                request,
                'Invalid email or password.'
            )
            return redirect('login')

        if not account.is_verified:
            # Show the activation link inline so the user does not have to go
            # hunting through their inbox.
            remember_activation_link(
                request,
                account,
                build_activation_link(request, account, 'activate_account')
            )

            messages.warning(
                request,
                'Your email address is not verified yet. Use the activation '
                'link shown at the top of this page, then login again.'
            )
            return redirect('login')

        user = authenticate(
            request,
            username=account.username,
            password=password
        )

        if user is not None:

            django_login(
                request,
                user
            )

            request.session['account_id'] = account.id

            clear_activation_link(request)

            if VendorProfile.objects.filter(account=account).exists():
                messages.success(
                    request,
                    f'Welcome back, {account.full_name}.'
                )
                return redirect('vendor_dashboard')

            messages.success(
                request,
                f'Welcome, {account.full_name}!'
            )

            return redirect('details')

        messages.error(
            request,
            'Invalid email or password.'
        )

    return render(
        request,
        'login.html'
    )


# =========================================================
# CUSTOMER LOGOUT
# =========================================================

def logout(request):

    django_logout(request)

    request.session.flush()

    messages.success(
        request,
        'You have been logged out successfully.'
    )

    return redirect('login')


# =========================================================
# CUSTOMER ACCOUNT
# =========================================================
def account(request):
    """The signed-out account hub.

    Once someone is logged in there is nothing to choose here any more, so
    they go straight to their own profile - a vendor to the vendor side, a
    buyer to the buyer side.
    """
    if request.user.is_authenticated:
        if get_vendor(request) is not None:
            return redirect('vendor_details')

        return redirect('details')

    return render(request, 'account.html', {'account': None})
# =========================================================
# CUSTOMER DETAILS
# =========================================================

@login_required(login_url='login')
def details(request):

    # A vendor never sees the buyer profile UI.
    if get_vendor(request) is not None:
        return redirect('vendor_details')

    account = request.user

    return render(
        request,
        'details.html',
        {
            'account': account
        }
    )


# =========================================================
# VENDOR DETAILS / PROFILE
# =========================================================

@vendor_required
def vendor_details(request):

    vendor = request.vendor
    account = vendor.account

    context = {
        'vendor': vendor,
        'account': account,
        'profile_sections': _profile_sections(vendor),
        'product_count': Product.objects.filter(vendor=vendor).count(),
        'quotation_count': Quote.objects.filter(vendor=vendor).count(),
        'order_count': PurchaseOrder.objects.filter(vendor=vendor).count(),
    }

    return render(request, 'vendor_details.html', context)


# =========================================================
# BUYER DASHBOARD (Orders, Quotes, POs, PIs, Reviews, Profile)
# =========================================================

@buyer_required
def buyer_dashboard(request):

    account = request.user

    context = {
        'account': account,
        'order_count': Order.objects.filter(account=account).count(),
        'quote_count': Quote.objects.filter(buyer=account).count(),
        'po_count': PurchaseOrder.objects.filter(buyer=account).count(),
        'pi_count': ProformaInvoice.objects.filter(po__buyer=account).count(),
        'review_count': Review.objects.filter(user=account).count(),
        'unread_notifications': Notification.objects.filter(
            recipient=account,
            is_read=False
        ).count(),
    }

    return render(request, 'dashboard.html', context)


# =========================================================
# ADDRESS
# =========================================================

@buyer_required
def address(request):

    account = request.user

    if request.method == 'POST':

        address_line_1 = request.POST.get(
            'address_line_1'
        )

        address_line_2 = request.POST.get(
            'address_line_2'
        )

        city = request.POST.get(
            'city'
        )

        state = request.POST.get(
            'state'
        )

        country = request.POST.get(
            'country'
        )

        pincode = request.POST.get(
            'pincode'
        )

        is_default = (
            request.POST.get('is_default') == 'on'
        )

        required = {
            'Address line 1': address_line_1,
            'City': city,
            'State': state,
            'Pincode': pincode,
        }

        missing = [label for label, value in required.items() if not value]

        if missing:
            messages.error(
                request,
                'Address not saved - please fill in: '
                + ', '.join(missing) + '.'
            )

            return render(
                request,
                'address.html',
                {
                    'account': account,
                    'addresses': Address.objects.filter(account=account),
                    'entered': request.POST,
                }
            )

        if is_default:

            Address.objects.filter(
                account=account,
                is_default=True
            ).update(
                is_default=False
            )

        Address.objects.create(
            account=account,
            address_line_1=address_line_1,
            address_line_2=address_line_2,
            city=city,
            state=state,
            country=country,
            pincode=pincode,
            is_default=is_default
        )

        messages.success(
            request,
            'Address added successfully!'
        )

        return redirect('address')

    addresses = Address.objects.filter(
        account=account
    )

    return render(
        request,
        'address.html',
        {
            'account': account,
            'addresses': addresses
        }
    )


# =========================================================
# EDIT ADDRESS
# =========================================================

@buyer_required
def edit_address(request, address_id):

    account = request.user

    address = get_object_or_404(
        Address,
        id=address_id,
        account=account
    )

    if request.method == 'POST':

        address.address_line_1 = request.POST.get(
            'address_line_1'
        )

        address.address_line_2 = request.POST.get(
            'address_line_2'
        )

        address.city = request.POST.get(
            'city'
        )

        address.state = request.POST.get(
            'state'
        )

        address.country = request.POST.get(
            'country'
        )

        address.pincode = request.POST.get(
            'pincode'
        )

        is_default = (
            request.POST.get('is_default') == 'on'
        )

        if is_default:

            Address.objects.filter(
                account=account,
                is_default=True
            ).exclude(
                id=address.id
            ).update(
                is_default=False
            )

        address.is_default = is_default

        address.save()

        messages.success(
            request,
            'Address updated successfully!'
        )

        return redirect('address')

    return render(
        request,
        'edit_address.html',
        {
            'account': account,
            'address': address
        }
    )


# =========================================================
# DELETE ADDRESS
# =========================================================

@buyer_required
def delete_address(request, address_id):

    account = request.user

    address = get_object_or_404(
        Address,
        id=address_id,
        account=account
    )

    address.delete()

    messages.success(
        request,
        'Address deleted successfully!'
    )

    return redirect('address')


# =========================================================
# VENDOR REGISTER
# =========================================================

def vendor_register(request):

    if request.user.is_authenticated:
        return redirect('vendor_dashboard')

    if request.method == 'POST':

        business_name = request.POST.get(
            'business_name',
            ''
        ).strip()

        full_name = request.POST.get(
            'full_name',
            ''
        ).strip()

        username = request.POST.get(
            'username',
            ''
        ).strip()

        email = request.POST.get(
            'email',
            ''
        ).strip().lower()

        phone = request.POST.get(
            'phone',
            ''
        ).strip()

        business_type = request.POST.get(
            'business_type',
            ''
        ).strip()

        business_address = request.POST.get(
            'business_address',
            ''
        ).strip()

        # The sign-up form collects the type and address separately; both are
        # kept on the profile's description.
        business_description = ' - '.join(
            part for part in (
                dict(BUSINESS_TYPES).get(business_type, business_type),
                business_address,
            ) if part
        )

        password = request.POST.get(
            'password'
        )

        confirm_password = request.POST.get(
            'confirm_password'
        )

        entered = {
            'business_name': business_name,
            'business_type': business_type,
            'business_address': business_address,
            'full_name': full_name,
            'username': username,
            'email': email,
            'phone': phone,
        }

        def reject(reason):
            messages.error(request, reason)
            return render(
                request,
                'vendor_register.html',
                {'entered': entered, 'business_types': BUSINESS_TYPES}
            )

        if not all([
            business_name,
            full_name,
            username,
            email,
            phone,
            password,
            confirm_password
        ]):
            return reject('Please fill all required fields.')

        if password != confirm_password:
            return reject('Passwords do not match.')

        if Account.objects.filter(
            email=email
        ).exists():

            return reject('Email already registered.')

        if Account.objects.filter(
            username=username
        ).exists():

            return reject('Username already exists.')

        account = Account.objects.create_user(
            username=username,
            email=email,
            password=password,
            full_name=full_name,
            phone=phone,
            is_verified=False,
            is_active=True
        )

        VendorProfile.objects.create(
            account=account,
            business_name=business_name,
            business_description=business_description,
            phone_number=phone,
            is_approved=True
        )

        activation_link = build_activation_link(
            request,
            account,
            'vendor_activate'
        )

        remember_activation_link(
            request,
            account,
            activation_link,
            is_vendor=True
        )

        try:
            send_mail(
                subject='Greatkart - Activate Your Vendor Account',
                message=(
                    f'Hello {full_name},\n\n'
                    f'Your vendor account has been created successfully.\n\n'
                    f'Please activate your account using the link below:\n\n'
                    f'{activation_link}\n\n'
                    f'After activation, you can login to your vendor dashboard.'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False
            )

            messages.success(
                request,
                'Vendor registration successful. We have emailed you an '
                'activation link - it is also shown on this page.'
            )

        except Exception as e:
            messages.warning(
                request,
                f'Your vendor account was created, but the activation email '
                f'could not be sent ({e}). Use the activation link shown on '
                f'this page instead.'
            )

        return redirect('vendor_activation_sent')

    return render(
        request,
        'vendor_register.html',
        {'business_types': BUSINESS_TYPES}
    )


# =========================================================
# VENDOR ACTIVATION
# =========================================================

def vendor_activate(request, uidb64, token):

    try:
        uid = urlsafe_base64_decode(
            uidb64
        ).decode()

        account = Account.objects.get(
            pk=uid
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
        Account.DoesNotExist
    ):
        account = None

    if account is None:

        messages.error(
            request,
            'Invalid vendor activation link.'
        )

        return redirect('vendor_login')

    if account.is_verified:

        messages.info(
            request,
            'Vendor account is already activated.'
        )

        return redirect('vendor_login')

    if not VendorProfile.objects.filter(
        account=account
    ).exists():

        messages.error(
            request,
            'Vendor account not found.'
        )

        return redirect('vendor_login')

    if not default_token_generator.check_token(
        account,
        token
    ):

        messages.error(
            request,
            'This activation link is invalid or has expired.'
        )

        return redirect('vendor_login')

    account.is_verified = True

    account.save(
        update_fields=[
            'is_verified'
        ]
    )

    clear_activation_link(request)

    messages.success(
        request,
        'Your vendor email has been verified and the account is now active. '
        'You can login.'
    )

    return redirect('vendor_login')


# =========================================================
# VENDOR LOGIN
# =========================================================

def vendor_login(request):

    if request.user.is_authenticated:

        if VendorProfile.objects.filter(
            account=request.user
        ).exists():

            return redirect(
                'vendor_dashboard'
            )

        # Merely opening this page used to sign a customer out, which threw
        # away their session and rotated the CSRF token mid-browse. Send them
        # to their own area and let them sign out deliberately instead.
        messages.info(
            request,
            'You are signed in as a customer. Sign out from your profile '
            'first if you want to use a vendor account.'
        )

        return redirect('details')

    if request.method == 'POST':

        email = request.POST.get(
            'email',
            ''
        ).strip().lower()

        password = request.POST.get(
            'password'
        )

        try:

            account = Account.objects.get(
                email=email
            )

        except Account.DoesNotExist:

            messages.error(
                request,
                'Invalid email or password.'
            )

            return redirect(
                'vendor_login'
            )

        try:

            vendor = VendorProfile.objects.get(
                account=account
            )

        except VendorProfile.DoesNotExist:

            messages.error(
                request,
                'This account is not registered as a vendor.'
            )

            return redirect(
                'vendor_login'
            )

        if not account.is_verified:

            remember_activation_link(
                request,
                account,
                build_activation_link(request, account, 'vendor_activate'),
                is_vendor=True
            )

            messages.warning(
                request,
                'Your vendor email address is not verified yet. Use the '
                'activation link shown at the top of this page, then login '
                'again.'
            )

            return redirect(
                'vendor_login'
            )

        if not vendor.is_approved:

            messages.warning(
                request,
                'Your vendor account is waiting for approval.'
            )

            return redirect(
                'vendor_login'
            )

        user = authenticate(
            request,
            username=account.username,
            password=password
        )

        if user is not None:

            django_login(
                request,
                user
            )

            request.session[
                'account_id'
            ] = account.id

            clear_activation_link(request)

            messages.success(
                request,
                f'Welcome back, {vendor.business_name}.'
            )

            return redirect(
                'vendor_dashboard'
            )

        messages.error(
            request,
            'Invalid email or password.'
        )

    return render(
        request,
        'vendor_login.html'
    )


# =========================================================
# VENDOR LOGOUT
# =========================================================

def vendor_logout(request):

    django_logout(request)

    request.session.flush()

    messages.success(
        request,
        'Vendor logged out successfully.'
    )

    return redirect(
        'vendor_login'
    )


# =========================================================
# VENDOR DASHBOARD
# =========================================================

@vendor_required
def vendor_dashboard(request):

    vendor = request.vendor

    products = Product.objects.filter(
        vendor=vendor
    )

    store_rating = Review.objects.filter(
        product__vendor=vendor
    ).aggregate(
        avg_rating=Avg('rating'),
        review_count=Count('id'),
    )

    context = {
        'vendor': vendor,
        'products': products,
        'pending_quotes_count': Quote.objects.filter(
            vendor=vendor,
            status=Quote.STATUS_PENDING
        ).count(),
        'sent_quotes_count': Quote.objects.filter(
            vendor=vendor
        ).exclude(
            status=Quote.STATUS_PENDING
        ).count(),
        'po_count': PurchaseOrder.objects.filter(vendor=vendor).count(),
        'store_avg_rating': store_rating['avg_rating'],
        'store_review_count': store_rating['review_count'],
    }

    return render(
        request,
        'vendor_dashboard.html',
        context
    )


# =========================================================
# VENDOR PRODUCTS
# =========================================================

@vendor_required
def vendor_products(request):

    vendor = request.vendor

    products = Product.objects.filter(
        vendor=vendor
    ).order_by(
        '-created_at'
    )

    return render(
        request,
        'vendor_products.html',
        {
            'vendor': vendor,
            'products': products
        }
    )


# =========================================================
# VENDOR ADD PRODUCT
# =========================================================

@vendor_required
def vendor_add_product(request):

    vendor = request.vendor

    if request.method == 'POST':

        product_name = request.POST.get(
            'product_name'
        )

        description = request.POST.get(
            'description'
        )

        price = request.POST.get(
            'price'
        )

        stock = request.POST.get(
            'stock'
        )

        image = request.FILES.get(
            'images'
        )

        if not product_name:

            messages.error(
                request,
                'Product name is required.'
            )

            return redirect(
                'vendor_add_product'
            )

        if not price:

            messages.error(
                request,
                'Price is required.'
            )

            return redirect(
                'vendor_add_product'
            )

        if not stock:

            messages.error(
                request,
                'Stock is required.'
            )

            return redirect(
                'vendor_add_product'
            )

        if not image:

            messages.error(
                request,
                'Product image is required.'
            )

            return redirect(
                'vendor_add_product'
            )

        slug = slugify(
            product_name
        )

        original_slug = slug
        counter = 1

        while Product.objects.filter(
            slug=slug
        ).exists():

            slug = f'{original_slug}-{counter}'
            counter += 1

        Product.objects.create(
            product_name=product_name,
            slug=slug,
            description=description,
            price=price,
            images=image,
            stock=stock,
            gst_rate=_gst_rate_from_post(request),
            vendor=vendor
        )

        messages.success(
            request,
            'Product added successfully.'
        )

        return redirect(
            'vendor_products'
        )

    return render(
        request,
        'vendor_add_product.html',
        {
            'vendor': vendor,
            'gst_choices': GST_SLAB_CHOICES,
            'default_gst_rate': DEFAULT_GST_RATE,
        }
    )


# =========================================================
# VENDOR PROFILE
# =========================================================

def _profile_sections(vendor):
    """The three profile boxes, each with its (label, value) rows."""
    sections = []

    for key, section in PROFILE_SECTIONS.items():
        rows = [
            (VendorProfile._meta.get_field(name).verbose_name, getattr(vendor, name))
            for name in section['fields']
        ]

        sections.append({
            'key': key,
            'title': section['title'],
            'rows': rows,
            'is_empty': not any(value for _, value in rows),
        })

    return sections


@vendor_required
def vendor_profile(request):

    vendor = request.vendor
    account = vendor.account

    # The organization / bank / terms block is only bound when it was part of
    # the submission, so a basic-details save can never blank it out.
    business_submitted = request.method == 'POST' and any(
        name in request.POST for name in VendorBusinessForm.Meta.fields
    )

    business_form = VendorBusinessForm(
        request.POST if business_submitted else None,
        instance=vendor,
    )

    if request.method == 'POST':

        business_name = request.POST.get('business_name', '').strip()
        full_name = request.POST.get('full_name', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        business_description = request.POST.get(
            'business_description', ''
        ).strip()

        errors = []

        if not business_name:
            errors.append('Business name is required.')

        if not full_name:
            errors.append('Owner name is required.')

        if not phone_number:
            errors.append('Phone number is required.')

        elif not phone_number.isdigit() or not 7 <= len(phone_number) <= 15:
            errors.append('Phone number must be 7-15 digits.')

        if business_submitted and not business_form.is_valid():
            errors.append('Please correct the highlighted business details below.')

        if errors:
            # Keep what was typed on the page and say exactly what is wrong,
            # instead of silently discarding the submission.
            messages.error(
                request,
                'Your profile was not saved. ' + ' '.join(errors)
            )

            return render(
                request,
                'vendor_profile.html',
                {
                    'vendor': vendor,
                    'account': account,
                    'business_form': business_form,
                    'form_data': {
                        'business_name': business_name,
                        'full_name': full_name,
                        'phone_number': phone_number,
                        'business_description': business_description,
                    },
                }
            )

        if business_submitted:
            # Writes the organization / bank / terms fields onto `vendor`.
            vendor = business_form.save(commit=False)

        vendor.business_name = business_name
        vendor.phone_number = phone_number
        vendor.business_description = business_description
        vendor.save()

        account.full_name = full_name
        account.phone = phone_number
        account.save(update_fields=['full_name', 'phone'])

        messages.success(request, 'Your vendor profile has been updated.')

        return redirect('vendor_details')

    return render(
        request,
        'vendor_profile.html',
        {
            'vendor': vendor,
            'account': account,
            'business_form': business_form,
        }
    )


@vendor_required
def vendor_profile_section_clear(request, section):
    """The Delete action on one profile box: blank out just that section."""
    if section not in PROFILE_SECTIONS:
        raise Http404('Unknown profile section.')

    if request.method != 'POST':
        return redirect('vendor_details')

    vendor = request.vendor
    fields = PROFILE_SECTIONS[section]['fields']

    for name in fields:
        setattr(vendor, name, '')

    vendor.save(update_fields=fields)

    messages.success(
        request,
        f'{PROFILE_SECTIONS[section]["title"]} were cleared from your profile.'
    )

    return redirect('vendor_details')


# =========================================================
# VENDOR EDIT PRODUCT
# =========================================================

@vendor_required
def vendor_edit_product(
    request,
    product_id
):

    vendor = request.vendor

    product = get_object_or_404(
        Product,
        id=product_id,
        vendor=vendor
    )

    if request.method == 'POST':

        product_name = request.POST.get(
            'product_name',
            ''
        ).strip()

        description = request.POST.get(
            'description',
            ''
        ).strip()

        price = request.POST.get(
            'price'
        )

        stock = request.POST.get(
            'stock'
        )

        category_id = request.POST.get(
            'category'
        )

        new_image = request.FILES.get(
            'images'
        )

        if not product_name:

            messages.error(
                request,
                'Product name is required.'
            )

            return redirect(
                'vendor_edit_product',
                product_id=product.id
            )

        if not description:

            messages.error(
                request,
                'Description is required.'
            )

            return redirect(
                'vendor_edit_product',
                product_id=product.id
            )

        if not price:

            messages.error(
                request,
                'Price is required.'
            )

            return redirect(
                'vendor_edit_product',
                product_id=product.id
            )

        if not stock:

            messages.error(
                request,
                'Stock is required.'
            )

            return redirect(
                'vendor_edit_product',
                product_id=product.id
            )

        product.product_name = product_name
        product.description = description
        product.price = price
        product.stock = stock
        product.gst_rate = _gst_rate_from_post(request, product.gst_rate)

        if category_id:

            try:

                category = Category.objects.get(
                    id=category_id
                )

                product.category = category

            except Category.DoesNotExist:

                messages.error(
                    request,
                    'Invalid category selected.'
                )

                return redirect(
                    'vendor_edit_product',
                    product_id=product.id
                )

        else:

            product.category = None

        if new_image:
            product.images = new_image

        new_slug = slugify(
            product_name
        )

        original_slug = new_slug
        counter = 1

        while Product.objects.filter(
            slug=new_slug
        ).exclude(
            id=product.id
        ).exists():

            new_slug = (
                f'{original_slug}-{counter}'
            )

            counter += 1

        product.slug = new_slug

        product.save()

        messages.success(
            request,
            'Product updated successfully.'
        )

        return redirect(
            'vendor_products'
        )

    categories = Category.objects.all()

    return render(
        request,
        'vendor_edit_product.html',
        {
            'vendor': vendor,
            'product': product,
            'categories': categories,
            'gst_choices': GST_SLAB_CHOICES,
        }
    )


# =========================================================
# VENDOR DELETE PRODUCT
# =========================================================

@vendor_required
def vendor_delete_product(
    request,
    product_id
):

    vendor = request.vendor

    product = get_object_or_404(
        Product,
        id=product_id,
        vendor=vendor
    )

    if request.method != 'POST':

        messages.error(
            request,
            'Invalid request.'
        )

        return redirect(
            'vendor_products'
        )

    if product.images:
        product.images.delete(
            save=False
        )

    product.delete()

    messages.success(
        request,
        'Product deleted successfully.'
    )

    return redirect(
        'vendor_products'
    )


# =========================================================
# FORGOT PASSWORD
# =========================================================

def forgot_password(request):

    if request.method == 'POST':

        email = request.POST.get(
            'email',
            ''
        ).strip().lower()

        try:

            account = Account.objects.get(
                email=email
            )

        except Account.DoesNotExist:

            messages.error(
                request,
                'No account found with this email.'
            )

            return redirect(
                'forgot_password'
            )

        uid = urlsafe_base64_encode(
            force_bytes(account.pk)
        )

        token = default_token_generator.make_token(
            account
        )

        reset_link = request.build_absolute_uri(
            reverse(
                'reset_password',
                kwargs={
                    'uidb64': uid,
                    'token': token
                }
            )
        )

        send_mail(
            subject='Greatkart - Reset Your Password',
            message=(
                f'Hello {account.full_name},\n\n'
                f'You requested to reset your password.\n\n'
                f'Click the link below to create a new password:\n\n'
                f'{reset_link}\n\n'
                f'If you did not request a password reset, ignore this email.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[account.email],
            fail_silently=False
        )

        messages.success(
            request,
            'Password reset link has been sent to your Gmail.'
        )

        return redirect(
            'forgot_password'
        )

    return render(
        request,
        'forgot-password.html'
    )


# =========================================================
# RESET PASSWORD
# =========================================================

def reset_password(
    request,
    uidb64,
    token
):

    try:

        uid = urlsafe_base64_decode(
            uidb64
        ).decode()

        account = Account.objects.get(
            pk=uid
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
        Account.DoesNotExist
    ):

        account = None

    if account is None:

        messages.error(
            request,
            'Invalid password reset link.'
        )

        return redirect(
            'forgot_password'
        )

    if not default_token_generator.check_token(
        account,
        token
    ):

        messages.error(
            request,
            'This password reset link is invalid or has expired.'
        )

        return redirect(
            'forgot_password'
        )

    if request.method == 'POST':

        password = request.POST.get(
            'password'
        )

        confirm_password = request.POST.get(
            'confirm_password'
        )

        if not password or not confirm_password:

            messages.error(
                request,
                'Please fill both password fields.'
            )

            return redirect(
                request.path
            )

        if password != confirm_password:

            messages.error(
                request,
                'Passwords do not match.'
            )

            return redirect(
                request.path
            )

        account.set_password(
            password
        )

        account.save()

        messages.success(
            request,
            'Password changed successfully. You can now login.'
        )

        return redirect(
            'login'
        )

    return render(
        request,
        'reset_password.html'
    )
def vendor_forgot_password(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()

        try:
            account = Account.objects.get(email=email)
            VendorProfile.objects.get(account=account)
        except (Account.DoesNotExist, VendorProfile.DoesNotExist):
            messages.error(request, 'No vendor account found with this email.')
            return redirect('vendor_forgot_password')

        uid = urlsafe_base64_encode(force_bytes(account.pk))
        token = default_token_generator.make_token(account)

        reset_link = request.build_absolute_uri(
            reverse(
                'vendor_reset_password',
                kwargs={
                    'uidb64': uid,
                    'token': token
                }
            )
        )

        send_mail(
            subject='Greatkart - Vendor Password Reset',
            message=f'''Hello {account.full_name},

You requested to reset your vendor account password.

Click the link below to create a new password:

{reset_link}

If you did not request this, please ignore this email.
''',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[account.email],
            fail_silently=False
        )

        messages.success(
            request,
            'Password reset link has been sent to your Gmail.'
        )

        return redirect('vendor_forgot_password')

    return render(request, 'vendor_forgot_password.html')


def vendor_reset_password(request, uidb64, token):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        account = Account.objects.get(pk=uid)
        VendorProfile.objects.get(account=account)
    except (TypeError, ValueError, OverflowError, Account.DoesNotExist, VendorProfile.DoesNotExist):
        account = None

    if account is None:
        messages.error(request, 'Invalid vendor password reset link.')
        return redirect('vendor_forgot_password')

    if not default_token_generator.check_token(account, token):
        messages.error(
            request,
            'This password reset link is invalid or has expired.'
        )
        return redirect('vendor_forgot_password')

    if request.method == 'POST':
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if not password or not confirm_password:
            messages.error(request, 'Please fill both password fields.')
            return redirect(request.path)

        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return redirect(request.path)

        account.set_password(password)
        account.save()

        messages.success(
            request,
            'Vendor password changed successfully. You can now login.'
        )

        return redirect('vendor_login')

    return render(
        request,
        'vendor_reset_password.html'
    )