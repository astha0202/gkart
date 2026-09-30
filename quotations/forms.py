import re
from decimal import Decimal

from django import forms

from .models import Quote, QuoteItem


GSTIN_RE = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$')
PAN_RE = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]$')
IFSC_RE = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
ACCOUNT_RE = re.compile(r'^[0-9]{6,20}$')


def _text(placeholder='', **extra):
    attrs = {'class': 'form-control', 'placeholder': placeholder}
    attrs.update(extra)
    return forms.TextInput(attrs=attrs)


class BankDetailsMixin:
    """Shared bank / tax validation for the buyer and vendor sides of a quote."""

    bank_prefix = ''

    def _f(self, name):
        return f'{self.bank_prefix}{name}'

    def clean_gst(self, value):
        value = (value or '').strip().upper()

        if value and not GSTIN_RE.match(value):
            raise forms.ValidationError(
                'Enter a valid 15-character GST number, e.g. 22AAAAA0000A1Z5.'
            )

        return value

    def _validate_bank_block(self, cleaned_data, required=False):
        """Bank details are all-or-nothing: a half-filled block is rejected."""
        names = {
            key: self._f(key)
            for key in (
                'bank_account_name',
                'bank_account_number',
                'bank_ifsc',
                'bank_name',
            )
        }

        values = {
            key: (cleaned_data.get(field) or '').strip()
            for key, field in names.items()
        }

        if not any(values.values()) and not required:
            return cleaned_data

        labels = {
            'bank_account_name': 'account holder name',
            'bank_account_number': 'account number',
            'bank_ifsc': 'IFSC code',
            'bank_name': 'bank name',
        }

        for key, field in names.items():
            if not values[key]:
                self.add_error(
                    field,
                    f'Please enter the {labels[key]} - bank details must be '
                    f'filled in completely.'
                )

        account_number = values['bank_account_number']

        if account_number and not ACCOUNT_RE.match(account_number):
            self.add_error(
                names['bank_account_number'],
                'Account number must be 6-20 digits.'
            )

        ifsc = values['bank_ifsc'].upper()

        if ifsc:
            cleaned_data[names['bank_ifsc']] = ifsc

            if not IFSC_RE.match(ifsc):
                self.add_error(
                    names['bank_ifsc'],
                    'Enter a valid 11-character IFSC code, e.g. HDFC0001234.'
                )

        return cleaned_data


class QuoteRequestForm(BankDetailsMixin, forms.Form):
    """Everything a buyer sends along with a quotation request.

    The customer is not asked for bank details: nothing in the quotation flow
    pays money *to* the buyer, so the section was noise on their side.
    """

    quantity = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '1'})
    )

    contact_name = forms.CharField(
        label='Full name',
        max_length=100,
        widget=_text('Enter your full name')
    )

    contact_email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email'
        })
    )

    contact_phone = forms.CharField(
        label='Phone number',
        max_length=15,
        widget=_text('Enter your phone number')
    )

    billing_address = forms.CharField(
        label='Billing address',
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Enter your complete billing address'
        })
    )

    buyer_gst_number = forms.CharField(
        label='GST number',
        required=False,
        max_length=20,
        widget=_text('22AAAAA0000A1Z5', style='text-transform:uppercase')
    )

    buyer_pan_number = forms.CharField(
        label='PAN',
        required=False,
        max_length=15,
        widget=_text('ABCDE1234F', style='text-transform:uppercase')
    )

    validity_days = forms.TypedChoiceField(
        label='Quotation validity',
        coerce=int,
        initial=15,
        choices=[(7, '7 Days'), (15, '15 Days'), (30, '30 Days')],
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    requested_delivery_date = forms.DateField(
        required=False,
        label='Requested delivery date',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )

    buyer_notes = forms.CharField(
        required=False,
        label='Remarks / message to vendor',
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Any special requirements, packaging, customisation, etc.'
        })
    )

    def __init__(self, *args, account=None, include_quantity=True, **kwargs):
        super().__init__(*args, **kwargs)

        self.account = account

        if not include_quantity:
            del self.fields['quantity']

        if account is not None and account.is_authenticated:
            # A logged-in buyer's email is the verified address on their
            # account, so it is pre-filled and cannot be edited here.
            # A disabled field ignores POSTed data and always uses `initial`.
            self.fields['contact_email'].disabled = True
            self.fields['contact_email'].initial = account.email
            self.fields['contact_email'].widget.attrs['readonly'] = 'readonly'

            if not self.fields['contact_name'].initial:
                self.fields['contact_name'].initial = account.full_name

            if not self.fields['contact_phone'].initial:
                self.fields['contact_phone'].initial = account.phone

    def clean_buyer_gst_number(self):
        return self.clean_gst(self.cleaned_data.get('buyer_gst_number'))

    def clean_buyer_pan_number(self):
        value = (self.cleaned_data.get('buyer_pan_number') or '').strip().upper()

        if value and not PAN_RE.match(value):
            raise forms.ValidationError(
                'Enter a valid 10-character PAN, e.g. ABCDE1234F.'
            )

        return value

    def quote_field_values(self):
        """The cleaned values that map straight onto Quote model fields."""
        data = dict(self.cleaned_data)
        data.pop('quantity', None)
        return data


class QuoteVendorResponseForm(BankDetailsMixin, forms.ModelForm):
    """The commercial terms a vendor attaches when sending a quotation back."""

    bank_prefix = 'vendor_'

    class Meta:
        model = Quote
        fields = [
            'vendor_notes',
            'valid_until',
            'delivery_days',
            'payment_terms',
            'warranty_terms',
            'shipping_charges',
            'packaging_charges',
            'discount',
            'tax_rate',
            'vendor_gst_number',
            'vendor_bank_account_name',
            'vendor_bank_account_number',
            'vendor_bank_ifsc',
            'vendor_bank_name',
        ]

        labels = {
            'delivery_days': 'Delivery lead time (days)',
            'payment_terms': 'Payment terms',
            'warranty_terms': 'Warranty / support terms',
            'shipping_charges': 'Delivery / freight charges (₹)',
            'packaging_charges': 'Packaging & handling (₹)',
            'discount': 'Discount on subtotal (₹)',
            'tax_rate': 'GST percentage slab',
            'vendor_gst_number': 'GST number',
            'vendor_bank_account_name': 'Account holder name',
            'vendor_bank_account_number': 'Account number',
            'vendor_bank_ifsc': 'IFSC code',
            'vendor_bank_name': 'Bank name',
        }

        widgets = {
            'vendor_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'valid_until': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'delivery_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'payment_terms': _text('e.g. 50% advance, balance on delivery'),
            'warranty_terms': _text('e.g. 12 months manufacturer warranty'),
            'shipping_charges': forms.NumberInput(
                attrs={'class': 'form-control', 'step': '0.01', 'min': '0',
                       'data-calc': 'shipping'}
            ),
            'packaging_charges': forms.NumberInput(
                attrs={'class': 'form-control', 'step': '0.01', 'min': '0',
                       'data-calc': 'packaging'}
            ),
            'discount': forms.NumberInput(
                attrs={'class': 'form-control', 'step': '0.01', 'min': '0',
                       'data-calc': 'discount'}
            ),
            'tax_rate': forms.Select(
                attrs={'class': 'form-control', 'data-calc': 'tax_rate'}
            ),
            'vendor_gst_number': _text('22AAAAA0000A1Z5', style='text-transform:uppercase'),
            'vendor_bank_account_name': _text('Name as per bank records'),
            'vendor_bank_account_number': _text('Enter account number'),
            'vendor_bank_ifsc': _text('HDFC0001234', style='text-transform:uppercase'),
            'vendor_bank_name': _text('Enter bank name'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # The buyer needs all of these to compare offers and to pay, so they
        # are mandatory on the vendor's response.
        for name in (
            'delivery_days',
            'payment_terms',
            'vendor_gst_number',
            'vendor_bank_account_name',
            'vendor_bank_account_number',
            'vendor_bank_ifsc',
            'vendor_bank_name',
        ):
            self.fields[name].required = True

        # Most quotations have no packaging charge; blank means zero.
        self.fields['packaging_charges'].required = False

        vendor = getattr(self.instance, 'vendor', None)

        if vendor is not None:
            # Pre-fill from the vendor's saved business profile so they don't
            # retype their GSTIN, bank account and standard terms every time.
            defaults = {
                'vendor_gst_number': vendor.gst_number,
                'vendor_bank_account_name': vendor.bank_account_name or vendor.business_name,
                'vendor_bank_account_number': vendor.bank_account_number,
                'vendor_bank_ifsc': vendor.bank_ifsc,
                'vendor_bank_name': vendor.bank_name,
                'payment_terms': vendor.terms_payment,
            }

            # `initial` already holds the instance's (blank) values, so only
            # fill the ones the quote itself doesn't have yet.
            for name, value in defaults.items():
                if value and not getattr(self.instance, name):
                    self.initial[name] = value

    def clean_vendor_gst_number(self):
        return self.clean_gst(self.cleaned_data.get('vendor_gst_number'))

    def clean_packaging_charges(self):
        value = self.cleaned_data.get('packaging_charges')
        return Decimal('0.00') if value is None else value

    def clean(self):
        cleaned_data = super().clean()
        return self._validate_bank_block(cleaned_data, required=True)


QuoteItemPriceFormSet = forms.modelformset_factory(
    QuoteItem,
    fields=['quoted_price'],
    extra=0,
    widgets={
        'quoted_price': forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0',
            'data-calc': 'unit_price',
        }),
    }
)


class BulkUploadForm(forms.Form):
    """An Excel/CSV list of products to request a quotation for."""

    MAX_BYTES = 2 * 1024 * 1024
    EXTENSIONS = ('.csv', '.xlsx', '.xlsm')

    file = forms.FileField(
        label='Product list (Excel or CSV)',
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control-file',
            'accept': '.csv,.xlsx,.xlsm',
        })
    )

    def clean_file(self):
        upload = self.cleaned_data['file']
        name = (upload.name or '').lower()

        if not name.endswith(self.EXTENSIONS):
            raise forms.ValidationError(
                'Upload a .xlsx or .csv file (old .xls files: re-save as .xlsx).'
            )

        if upload.size > self.MAX_BYTES:
            raise forms.ValidationError('The file is larger than 2 MB.')

        return upload
