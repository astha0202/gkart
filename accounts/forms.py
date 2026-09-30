import re

from django import forms

from .models import VendorProfile


GSTIN_RE = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$')
PAN_RE = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]$')
IFSC_RE = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
ACCOUNT_RE = re.compile(r'^[0-9]{6,20}$')


# The three boxes on the vendor profile, in display order.
PROFILE_SECTIONS = {
    'organization': {
        'title': 'Organization Details',
        'fields': [
            'gst_number', 'pan_number', 'cin_number',
            'business_email', 'website', 'business_address',
        ],
    },
    'bank': {
        'title': 'Bank Details',
        'fields': [
            'bank_name', 'bank_account_name', 'bank_account_number',
            'bank_ifsc', 'bank_branch',
        ],
    },
    'terms': {
        'title': 'Terms & Conditions',
        'fields': [
            'terms_validity', 'terms_delivery', 'terms_payment', 'terms_remarks',
        ],
    },
}


def _input(placeholder='', **extra):
    attrs = {'class': 'form-control', 'placeholder': placeholder}
    attrs.update(extra)
    return forms.TextInput(attrs=attrs)


class VendorBusinessForm(forms.ModelForm):
    """Organization, bank and default terms for a vendor's business profile."""

    class Meta:
        model = VendorProfile
        fields = [
            name
            for section in PROFILE_SECTIONS.values()
            for name in section['fields']
        ]

        widgets = {
            'gst_number': _input('22AAAAA0000A1Z5', style='text-transform:uppercase'),
            'pan_number': _input('ABCDE1234F', style='text-transform:uppercase'),
            'cin_number': _input('U12345MH2020PTC123456', style='text-transform:uppercase'),
            'business_email': forms.EmailInput(attrs={
                'class': 'form-control', 'placeholder': 'accounts@yourcompany.com',
            }),
            'website': forms.URLInput(attrs={
                'class': 'form-control', 'placeholder': 'https://yourcompany.com',
            }),
            'business_address': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3, 'placeholder': 'Registered business address',
            }),
            'bank_name': _input('e.g. HDFC Bank'),
            'bank_account_name': _input('Name as per bank records'),
            'bank_account_number': _input('Account number'),
            'bank_ifsc': _input('HDFC0001234', style='text-transform:uppercase'),
            'bank_branch': _input('Branch name'),
            'terms_validity': _input('e.g. 15 days from date of issue'),
            'terms_delivery': _input('e.g. Ex-works, freight extra. Dispatch in 7-10 days of PO.'),
            'terms_payment': _input('e.g. 50% advance, balance before dispatch'),
            'terms_remarks': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3,
                'placeholder': 'Anything else printed on every quotation',
            }),
        }

    def _upper(self, name, pattern, message):
        value = (self.cleaned_data.get(name) or '').strip().upper()

        if value and not pattern.match(value):
            raise forms.ValidationError(message)

        return value

    def clean_gst_number(self):
        return self._upper(
            'gst_number', GSTIN_RE,
            'Enter a valid 15-character GSTIN, e.g. 22AAAAA0000A1Z5.'
        )

    def clean_pan_number(self):
        return self._upper(
            'pan_number', PAN_RE,
            'Enter a valid 10-character PAN, e.g. ABCDE1234F.'
        )

    def clean_cin_number(self):
        return (self.cleaned_data.get('cin_number') or '').strip().upper()

    def clean_bank_ifsc(self):
        return self._upper(
            'bank_ifsc', IFSC_RE,
            'Enter a valid 11-character IFSC code, e.g. HDFC0001234.'
        )

    def clean_bank_account_number(self):
        value = (self.cleaned_data.get('bank_account_number') or '').strip()

        if value and not ACCOUNT_RE.match(value):
            raise forms.ValidationError('Account number must be 6-20 digits.')

        return value

    def clean(self):
        cleaned_data = super().clean()

        # Bank details are all-or-nothing: a half-filled block can't be paid into.
        required_bank = {
            'bank_name': 'bank name',
            'bank_account_name': 'account holder',
            'bank_account_number': 'account number',
            'bank_ifsc': 'IFSC code',
        }

        if any(cleaned_data.get(name) for name in required_bank):
            for name, label in required_bank.items():
                if not cleaned_data.get(name) and name not in self.errors:
                    self.add_error(
                        name,
                        f'Please enter the {label} - bank details must be complete.'
                    )

        return cleaned_data
