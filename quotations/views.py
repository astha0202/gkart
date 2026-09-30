import csv
import uuid
from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.utils import buyer_required, get_vendor, vendor_required
from cart.models import Cart
from notifications.models import Notification
from notifications.utils import notify
from store.models import Product

from .comparison import comparison_matrix, compare_quotes, item_rate_matrix
from .forms import (
    BulkUploadForm,
    QuoteItemPriceFormSet,
    QuoteRequestForm,
    QuoteVendorResponseForm,
)
from .models import (
    ProformaInvoice,
    PurchaseOrder,
    Quote,
    QuoteHistory,
    QuoteItem,
    default_tax_rate_for,
)
from .signals import next_tax_invoice_number
from .utils import (
    UploadError,
    amount_in_words,
    build_invoice_pdf,
    generate_proforma_pdf,
    match_catalog_products,
    parse_product_sheet,
    qr_svg,
    send_quote_email,
)


UPLOAD_SESSION_KEY = 'quote_upload'


def _is_vendor_for(request, quote):
    vendor = get_vendor(request)
    return vendor is not None and vendor.id == quote.vendor_id


def _log_status_change(quote, user, from_status, to_status, comment):
    QuoteHistory.objects.create(
        quote=quote,
        changed_by=user,
        from_status=from_status,
        to_status=to_status,
        comment=comment,
    )


def _report_form_errors(request, form, prefix='Could not send the request.'):
    """Surface every validation error as a visible message.

    Without this a failed submit looks like the form silently cleared itself.
    """
    parts = []

    for field_name, field_errors in form.errors.items():
        if field_name == '__all__':
            label = ''
        else:
            label = f'{form.fields[field_name].label or field_name}: '

        for error in field_errors:
            parts.append(f'{label}{error}')

    messages.error(request, f'{prefix} ' + ' '.join(parts))


def _mobile_url(request, quote):
    return request.build_absolute_uri(
        reverse('quote_mobile', args=[quote.public_token])
    )


def _create_quote(request, vendor, lines, form, request_group):
    """Create one Quote (with its items) for a single vendor.

    `lines` are (product, quantity, supporting_link) tuples.
    """
    values = form.quote_field_values()

    quote = Quote.objects.create(
        request_group=request_group,
        buyer=request.user,
        vendor=vendor,
        status=Quote.STATUS_PENDING,
        tax_rate=default_tax_rate_for([product for product, _, _ in lines]),
        **values
    )

    for product, quantity, link in lines:
        QuoteItem.objects.create(
            quote=quote,
            product=product,
            quantity=quantity,
            listed_price=product.price,
            supporting_link=link,
        )

    # Price the request off the listed prices straight away so the buyer sees
    # a real estimate instead of a zero total while waiting for the vendor.
    quote.recalculate_totals()

    _log_status_change(
        quote, request.user, '', Quote.STATUS_PENDING,
        'Quotation requested by buyer.'
    )

    notify(
        recipient=vendor.account,
        message=f'New quotation request {quote.quote_number}.',
        link=reverse('quote_detail', args=[quote.quote_number]),
    )

    return quote


# =========================================================
# BUYER: REQUEST A QUOTATION FROM THE PRODUCT PAGE
# =========================================================

@buyer_required
def quote_request_create(request, slug):
    """The full quotation form for a single product."""
    product = get_object_or_404(Product, slug=slug, is_available=True)

    if not product.vendor:
        messages.error(
            request,
            'This product has no vendor assigned, so it cannot be quoted.'
        )
        return redirect('product_detail', slug=product.slug)

    def page(form, quantity):
        try:
            quantity = max(int(quantity), 1)
        except (TypeError, ValueError):
            quantity = 1

        return render(
            request,
            'quotations/quote_request.html',
            {
                'form': form,
                'checkout_items': [{
                    'product': product,
                    'quantity': quantity,
                    'link': '',
                    'subtotal': product.price * quantity,
                }],
                'total': product.price * quantity,
                'single_product': product,
                'vendors': [product.vendor],
                'vendor_count': 1,
            }
        )

    if request.method != 'POST':
        return page(
            QuoteRequestForm(
                account=request.user,
                initial={'quantity': request.GET.get('quantity') or 1},
            ),
            request.GET.get('quantity') or 1,
        )

    form = QuoteRequestForm(request.POST, account=request.user)

    if not form.is_valid():
        _report_form_errors(
            request,
            form,
            'Your quotation request was not sent, so nothing has been cleared '
            '- please correct the highlighted fields.'
        )
        return page(form, request.POST.get('quantity') or 1)

    quote = _create_quote(
        request,
        product.vendor,
        [(product, form.cleaned_data['quantity'], '')],
        form,
        uuid.uuid4(),
    )

    messages.success(
        request,
        f'Quotation request {quote.quote_number} was sent to '
        f'{product.vendor.business_name}.'
    )
    return redirect('quote_detail', quote_number=quote.quote_number)


# =========================================================
# BUYER: REQUEST A QUOTATION FOR AN UPLOADED LIST / CART / BUY-NOW ITEM
# =========================================================

def _quotation_lines(request):
    """The (product, quantity, link) lines the quotation page is raised for,
    and where they came from: 'upload', 'buy_now' or 'cart'.

    An uploaded product list wins, then a pending "buy now" item (mirroring
    the checkout page), otherwise the contents of the cart.
    """
    uploaded = request.session.get(UPLOAD_SESSION_KEY)

    if uploaded:
        products = Product.objects.filter(
            id__in=[row['product_id'] for row in uploaded],
            is_available=True,
        ).select_related('vendor').in_bulk()

        lines = [
            (products[row['product_id']], row['quantity'], row.get('link', ''))
            for row in uploaded
            if row['product_id'] in products
        ]

        return lines, 'upload'

    buy_now_data = request.session.get('buy_now')

    if buy_now_data:
        product = Product.objects.filter(id=buy_now_data['product_id']).first()
        lines = [(product, buy_now_data['quantity'], '')] if product else []
        return lines, 'buy_now'

    cart_items = Cart.objects.filter(
        account=request.user
    ).select_related('product', 'product__vendor')

    return [(item.product, item.quantity, '') for item in cart_items], 'cart'


def _apply_posted_lines(request, lines):
    """Apply the quantity / link edits (and row removals) from the form.

    The products table on the request page is editable, so what gets quoted
    is what the buyer sees there - not whatever was in the cart before.
    Returns (lines, errors). Without posted rows the lines are unchanged.
    """
    posted_ids = request.POST.getlist('line_product')

    if not posted_ids:
        return lines, []

    quantities = request.POST.getlist('line_quantity')
    links = request.POST.getlist('line_link')

    by_id = {str(product.id): product for product, _, _ in lines}

    result = []
    errors = []

    for index, product_id in enumerate(posted_ids):
        product = by_id.get(product_id)

        if product is None:
            continue

        raw_quantity = quantities[index] if index < len(quantities) else ''

        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            quantity = 0

        if quantity < 1:
            errors.append(f'{product.product_name}: quantity must be at least 1.')
            continue

        link = (links[index] if index < len(links) else '').strip()[:500]

        if link and not link.lower().startswith(('http://', 'https://')):
            link = f'https://{link}'

        result.append((product, quantity, link))

    return result, errors


def _checkout_rows(lines):
    return [
        {
            'product': product,
            'quantity': quantity,
            'link': link,
            'subtotal': product.price * quantity,
        }
        for product, quantity, link in lines
    ]


@buyer_required
def quote_request_page(request):
    lines, source = _quotation_lines(request)
    line_errors = []

    if request.method == 'POST':
        lines, line_errors = _apply_posted_lines(request, lines)

    checkout_items = _checkout_rows(lines)
    total = sum((row['subtotal'] for row in checkout_items), 0)

    vendors = OrderedDict()

    for product, quantity, link in lines:
        if product.vendor_id:
            vendors.setdefault(product.vendor, []).append((product, quantity, link))

    unassigned = [
        product for product, _, _ in lines if not product.vendor_id
    ]

    if request.method == 'POST':
        form = QuoteRequestForm(
            request.POST,
            account=request.user,
            include_quantity=False,
        )

        if not lines and not line_errors:
            messages.error(
                request,
                'There is nothing to request a quotation for. '
                'Add products to your cart or upload a product list first.'
            )
            return redirect('cart' if source == 'cart' else 'quotation')

        if line_errors:
            messages.error(
                request,
                'Your quotation request was not sent. ' + ' '.join(line_errors)
            )

        elif not vendors:
            messages.error(
                request,
                'None of these products has a vendor assigned, '
                'so no quotation can be requested.'
            )

        elif form.is_valid():
            request_group = uuid.uuid4()
            created = []

            with transaction.atomic():
                for vendor, vendor_lines in vendors.items():
                    created.append(
                        _create_quote(
                            request, vendor, vendor_lines, form, request_group
                        )
                    )

            request.session.pop(UPLOAD_SESSION_KEY, None)

            if unassigned:
                messages.warning(
                    request,
                    f'{len(unassigned)} product(s) have no vendor assigned and '
                    f'were left out of the request.'
                )

            if len(created) == 1:
                messages.success(
                    request,
                    f'Quotation request {created[0].quote_number} was sent to '
                    f'{created[0].vendor.business_name}.'
                )
                return redirect(
                    'quote_detail', quote_number=created[0].quote_number
                )

            messages.success(
                request,
                f'Your quotation request was sent to {len(created)} vendors. '
                f'Their responses will appear here side by side.'
            )
            return redirect('quote_compare', request_group=request_group)

        else:
            _report_form_errors(
                request,
                form,
                'Your quotation request was not sent, so nothing has been '
                'cleared - please correct the highlighted fields.'
            )

    else:
        form = QuoteRequestForm(account=request.user, include_quantity=False)

    return render(
        request,
        'quotations/quote_request.html',
        {
            'form': form,
            'upload_form': BulkUploadForm(),
            'line_source': source,
            'editable_lines': True,
            'checkout_items': checkout_items,
            'total': total,
            'vendor_count': len(vendors),
            'vendors': list(vendors.keys()),
            'unassigned': unassigned,
        }
    )


# =========================================================
# BUYER: BULK UPLOAD AN EXCEL / CSV PRODUCT LIST
# =========================================================

@buyer_required
@require_POST
def quote_upload(request):
    """Parse an uploaded product list and use it to fill the request form."""
    form = BulkUploadForm(request.POST, request.FILES)

    if not form.is_valid():
        _report_form_errors(request, form, 'The file was not uploaded.')
        return redirect('quotation')

    try:
        rows, problems = parse_product_sheet(form.cleaned_data['file'])
    except UploadError as exc:
        messages.error(request, f'The file was not uploaded. {exc}')
        return redirect('quotation')

    catalogue = Product.objects.filter(
        is_available=True,
        vendor__isnull=False,
    ).select_related('vendor')

    lines, unmatched = match_catalog_products(rows, catalogue)

    if not lines:
        messages.error(
            request,
            'None of the products in the file matched the catalogue, so the '
            'form was left unchanged. Check the Product Name column.'
        )

        for problem in problems[:10]:
            messages.warning(request, problem)

        return redirect('quotation')

    request.session[UPLOAD_SESSION_KEY] = [
        {
            'product_id': line['product'].id,
            'quantity': line['quantity'],
            'link': line['link'],
        }
        for line in lines
    ]

    matched_rows = len(rows) - len(unmatched)
    vendor_count = len({line['product'].vendor_id for line in lines})

    messages.success(
        request,
        f'{matched_rows} of {len(rows)} product(s) from the file were added '
        f'({len(lines)} line(s) across {vendor_count} vendor(s)). Review the '
        f'quantities below and send the request.'
    )

    approximate = sorted({
        f'"{line["source_name"]}" -> {line["product"].product_name}'
        for line in lines if not line['exact']
    })

    if approximate:
        messages.info(
            request,
            'Matched by partial name, please double-check: ' + '; '.join(approximate[:10])
        )

    if unmatched:
        names = ', '.join(f'"{row["name"]}" (row {row["row"]})' for row in unmatched[:10])
        more = f' and {len(unmatched) - 10} more' if len(unmatched) > 10 else ''

        messages.warning(
            request,
            f'Not found in the catalogue, left out: {names}{more}.'
        )

    for problem in problems[:10]:
        messages.warning(request, problem)

    return redirect('quotation')


@buyer_required
@require_POST
def quote_upload_clear(request):
    request.session.pop(UPLOAD_SESSION_KEY, None)
    messages.info(request, 'The uploaded product list was cleared.')
    return redirect('quotation')


@buyer_required
def quote_upload_template(request):
    """A ready-to-fill CSV with the three columns the parser understands."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="quotation-upload-template.csv"'

    writer = csv.writer(response)
    writer.writerow(['Product Name', 'Quantity', 'Supporting Link'])

    example = Product.objects.filter(is_available=True, vendor__isnull=False).first()
    writer.writerow([
        example.product_name if example else 'Cisco 24-port Managed Switch',
        6,
        'https://example.com/datasheet.pdf',
    ])

    return response


# =========================================================
# LISTS
# =========================================================

@buyer_required
def quote_list_buyer(request):
    quotes = Quote.objects.filter(
        buyer=request.user
    ).select_related('vendor', 'purchase_order__proforma_invoice').prefetch_related(
        'items__product'
    )

    # Group by the request they came from, so a request sent to several
    # vendors is shown as one card with all its responses, ranked.
    groups = OrderedDict()

    for quote in quotes:
        groups.setdefault(quote.request_group, []).append(quote)

    grouped = []

    for request_group, group_quotes in groups.items():
        comparison = compare_quotes(group_quotes)
        priced_rows = comparison['priced_rows']

        savings = None

        if len(priced_rows) > 1:
            savings = (
                max(row['quote'].total for row in priced_rows)
                - comparison['best']['quote'].total
            )

        grouped.append({
            'request_group': request_group,
            # Ranked best deal first, then the vendors still to respond.
            'rows': comparison['rows'],
            'created_at': group_quotes[0].created_at,
            'items': group_quotes[0].items.all(),
            'vendor_count': len(group_quotes),
            'responded': len(priced_rows),
            'best': comparison['best'],
            'savings': savings,
        })

    sort = request.GET.get('sort', 'best')

    if sort == 'newest':
        grouped.sort(key=lambda group: group['created_at'], reverse=True)
    else:
        sort = 'best'
        # Requests with a priced best deal first (biggest saving on top),
        # then the ones still waiting on vendors - newest first within each.
        grouped.sort(key=lambda group: group['created_at'], reverse=True)
        grouped.sort(key=lambda group: (
            group['best'] is None,
            -(group['savings'] or 0),
        ))

    return render(
        request,
        'quotations/quote_list_buyer.html',
        {
            'quotes': quotes,
            'grouped_quotes': grouped,
            'sort': sort,
        }
    )


@vendor_required
def quote_list_vendor(request):
    vendor = request.vendor

    quotes = Quote.objects.filter(
        vendor=vendor
    ).select_related('buyer').prefetch_related('items')

    context = {
        'vendor': vendor,
        'pending_quotes': quotes.filter(status=Quote.STATUS_PENDING),
        'sent_quotes': quotes.exclude(status=Quote.STATUS_PENDING),
    }

    return render(request, 'quotations/quote_list_vendor.html', context)


# =========================================================
# BUYER: COMPARE EVERY VENDOR RESPONSE TO ONE REQUEST
# =========================================================

def _group_quotes_or_404(request, request_group):
    quotes = list(
        Quote.objects.filter(
            buyer=request.user,
            request_group=request_group,
        ).select_related('vendor').prefetch_related('items__product')
    )

    if not quotes:
        raise Http404('Quotation request not found.')

    return quotes


def _requested_items(quotes):
    """Every item in the request, across all vendors' quotations."""
    return [item for quote in quotes for item in quote.items.all()]


@buyer_required
def quote_compare(request, request_group):
    quotes = _group_quotes_or_404(request, request_group)
    comparison = compare_quotes(quotes)
    rows = comparison['rows']

    return render(
        request,
        'quotations/quote_compare.html',
        {
            'request_group': request_group,
            'quotes': quotes,
            'rows': rows,
            'priced_rows': comparison['priced_rows'],
            'best': comparison['best'],
            'awaiting': comparison['awaiting'],
            'items': _requested_items(quotes),
            'item_matrix': item_rate_matrix(rows),
        }
    )


@buyer_required
def quote_compare_detail(request, request_group):
    quotes = _group_quotes_or_404(request, request_group)
    comparison = compare_quotes(quotes)

    rows = comparison['rows']

    return render(
        request,
        'quotations/quote_compare_detail.html',
        {
            'request_group': request_group,
            'rows': rows,
            'best': comparison['best'],
            'matrix': comparison_matrix(rows),
            'item_matrix': item_rate_matrix(rows),
            'items': _requested_items(quotes),
        }
    )


# =========================================================
# DETAIL (shared by buyer & vendor)
# =========================================================

def _quote_for_party_or_404(request, quote_number):
    """The quote, plus (is_buyer, is_vendor); 404 for anyone else."""
    quote = get_object_or_404(
        Quote.objects.select_related(
            'buyer', 'vendor', 'vendor__account', 'purchase_order__proforma_invoice'
        ).prefetch_related('items__product', 'history__changed_by'),
        quote_number=quote_number
    )

    is_buyer = quote.buyer_id == request.user.id
    is_vendor = _is_vendor_for(request, quote)

    if not is_buyer and not is_vendor:
        raise Http404('Quotation not found.')

    return quote, is_buyer, is_vendor


@login_required(login_url='login')
def quote_detail(request, quote_number):
    quote, is_buyer, is_vendor = _quote_for_party_or_404(request, quote_number)

    # Opening the quotation is reading its updates: clear the notifications
    # that point here so the navbar's Quotations badge counts down.
    Notification.objects.filter(
        recipient=request.user,
        is_read=False,
        link__in=[
            reverse('quote_detail', args=[quote.quote_number]),
            reverse('quote_send', args=[quote.quote_number]),
        ],
    ).update(is_read=True)

    purchase_order = getattr(quote, 'purchase_order', None)
    proforma_invoice = getattr(purchase_order, 'proforma_invoice', None) if purchase_order else None

    sibling_count = Quote.objects.filter(
        buyer_id=quote.buyer_id,
        request_group=quote.request_group,
    ).count()

    mobile_url = _mobile_url(request, quote) if quote.is_approved else ''

    context = {
        'quote': quote,
        'is_buyer': is_buyer,
        'is_vendor': is_vendor,
        'purchase_order': purchase_order,
        'proforma_invoice': proforma_invoice,
        'sibling_count': sibling_count,
        'steps': quote.lifecycle_steps(),
        'mobile_url': mobile_url,
        'qr_code': qr_svg(mobile_url) if mobile_url else '',
    }

    return render(request, 'quotations/quote_detail.html', context)


# =========================================================
# PUBLIC: MOBILE STATUS PAGE (target of the QR code)
# =========================================================

def quote_mobile(request, token):
    """Read-only, mobile-friendly status of one quotation.

    Reached by scanning the QR code, so it needs no login - the unguessable
    token is the credential. It deliberately leaves out bank details and the
    buyer's tax/contact information.
    """
    quote = get_object_or_404(
        Quote.objects.select_related(
            'vendor', 'purchase_order__proforma_invoice'
        ).prefetch_related('items__product'),
        public_token=token,
    )

    purchase_order = getattr(quote, 'purchase_order', None)

    return render(
        request,
        'quotations/quote_mobile.html',
        {
            'quote': quote,
            'steps': quote.lifecycle_steps(),
            'purchase_order': purchase_order,
            'proforma_invoice': getattr(purchase_order, 'proforma_invoice', None)
            if purchase_order else None,
        }
    )


# =========================================================
# VENDOR: PRICE & SEND A PENDING QUOTATION
# =========================================================

@vendor_required
def quote_send(request, quote_number):
    vendor = request.vendor
    quote = get_object_or_404(Quote, quote_number=quote_number, vendor=vendor)

    if quote.status != Quote.STATUS_PENDING:
        messages.error(request, 'Only pending quotations can be priced.')
        return redirect('quote_detail', quote_number=quote.quote_number)

    item_queryset = quote.items.select_related('product').order_by('id')

    if request.method == 'POST':
        notes_form = QuoteVendorResponseForm(request.POST, instance=quote)
        formset = QuoteItemPriceFormSet(request.POST, queryset=item_queryset)

        formset_valid = formset.is_valid()
        notes_valid = notes_form.is_valid()

        missing_price = False

        if formset_valid:
            missing_price = any(
                form.cleaned_data.get('quoted_price') in (None, '')
                for form in formset.forms
            )

        if notes_valid and formset_valid and not missing_price:

            with transaction.atomic():
                notes_form.save()
                formset.save()

                quote.refresh_from_db()

                from_status = quote.status

                quote.recalculate_totals()

                quote.status = Quote.STATUS_QUOTED
                quote.save(update_fields=['status'])

                _log_status_change(
                    quote, request.user, from_status, Quote.STATUS_QUOTED,
                    'Vendor priced and sent the quotation.'
                )

            send_quote_email(quote)
            notify(
                recipient=quote.buyer,
                message=f'Your quotation {quote.quote_number} has been priced by the vendor.',
                link=reverse('quote_detail', args=[quote.quote_number]),
            )

            messages.success(request, f'Quotation {quote.quote_number} sent to the buyer.')
            return redirect('quote_detail', quote_number=quote.quote_number)

        if missing_price:
            messages.error(
                request,
                'Nothing was sent: please enter a quoted price for every item.'
            )

        if not notes_valid:
            _report_form_errors(
                request,
                notes_form,
                'The quotation was not sent.'
            )
        elif not formset_valid:
            messages.error(
                request,
                'The quotation was not sent: please correct the prices below.'
            )
    else:
        notes_form = QuoteVendorResponseForm(instance=quote)
        formset = QuoteItemPriceFormSet(queryset=item_queryset)

    context = {
        'quote': quote,
        'notes_form': notes_form,
        'formset': formset,
    }

    return render(request, 'quotations/quote_send.html', context)


# =========================================================
# BUYER: ACCEPT -> CREATES PURCHASE ORDER + PROFORMA INVOICE
# =========================================================

@buyer_required
def quote_accept(request, quote_number):
    quote = get_object_or_404(Quote, quote_number=quote_number, buyer=request.user)

    if request.method != 'POST':
        return redirect('quote_detail', quote_number=quote.quote_number)

    if quote.status != Quote.STATUS_QUOTED:
        messages.error(request, 'Only quoted quotations can be accepted.')
        return redirect('quote_detail', quote_number=quote.quote_number)

    with transaction.atomic():
        from_status = quote.status
        quote.status = Quote.STATUS_ACCEPTED
        quote.save(update_fields=['status'])

        _log_status_change(
            quote, request.user, from_status, Quote.STATUS_ACCEPTED,
            'Buyer accepted the quotation.'
        )

        purchase_order = PurchaseOrder.objects.create(
            quote=quote,
            buyer=quote.buyer,
            vendor=quote.vendor,
            status=PurchaseOrder.STATUS_OPEN,
        )

        proforma_invoice = ProformaInvoice.objects.create(po=purchase_order)
        generate_proforma_pdf(proforma_invoice, qr_url=_mobile_url(request, quote))

        from_status = quote.status
        quote.status = Quote.STATUS_CONVERTED
        quote.save(update_fields=['status'])

        _log_status_change(
            quote, request.user, from_status, Quote.STATUS_CONVERTED,
            f'Converted to Purchase Order {purchase_order.po_number}.'
        )

    notify(
        recipient=quote.vendor.account,
        message=f'Quotation {quote.quote_number} accepted. PO {purchase_order.po_number} created.',
        link=reverse('quote_detail', args=[quote.quote_number]),
    )

    messages.success(
        request,
        f'Quotation accepted. Purchase Order {purchase_order.po_number} and '
        f'Proforma Invoice {proforma_invoice.pi_number} have been generated.'
    )
    return redirect('quote_detail', quote_number=quote.quote_number)


# =========================================================
# BUYER: REJECT A QUOTED QUOTATION
# =========================================================

@buyer_required
def quote_reject(request, quote_number):
    quote = get_object_or_404(Quote, quote_number=quote_number, buyer=request.user)

    if request.method != 'POST':
        return redirect('quote_detail', quote_number=quote.quote_number)

    if quote.status != Quote.STATUS_QUOTED:
        messages.error(request, 'Only quoted quotations can be rejected.')
        return redirect('quote_detail', quote_number=quote.quote_number)

    from_status = quote.status
    quote.status = Quote.STATUS_REJECTED
    quote.save(update_fields=['status'])

    _log_status_change(
        quote, request.user, from_status, Quote.STATUS_REJECTED,
        request.POST.get('comment', 'Buyer rejected the quotation.')
    )

    notify(
        recipient=quote.vendor.account,
        message=f'Quotation {quote.quote_number} was rejected by the buyer.',
        link=reverse('quote_detail', args=[quote.quote_number]),
    )

    messages.success(request, 'Quotation rejected.')
    return redirect('quote_detail', quote_number=quote.quote_number)


# =========================================================
# BUYER OR VENDOR: CANCEL A PENDING/QUOTED QUOTATION
# =========================================================

@login_required(login_url='login')
def quote_cancel(request, quote_number):
    quote = get_object_or_404(Quote, quote_number=quote_number)

    is_buyer = quote.buyer_id == request.user.id
    is_vendor = _is_vendor_for(request, quote)

    if not is_buyer and not is_vendor:
        raise Http404('Quotation not found.')

    if request.method != 'POST':
        return redirect('quote_detail', quote_number=quote.quote_number)

    if quote.status not in (Quote.STATUS_PENDING, Quote.STATUS_QUOTED):
        messages.error(request, 'This quotation can no longer be cancelled.')
        return redirect('quote_detail', quote_number=quote.quote_number)

    from_status = quote.status
    quote.status = Quote.STATUS_CANCELLED
    quote.save(update_fields=['status'])

    _log_status_change(
        quote, request.user, from_status, Quote.STATUS_CANCELLED,
        'Quotation cancelled.'
    )

    notify(
        recipient=quote.vendor.account if is_buyer else quote.buyer,
        message=f'Quotation {quote.quote_number} was cancelled.',
        link=reverse('quote_detail', args=[quote.quote_number]),
    )

    messages.success(request, 'Quotation cancelled.')
    return redirect('quote_list_buyer' if is_buyer else 'quote_list_vendor')


# =========================================================
# LIFECYCLE STEPS 6-8: PAYMENT -> ACKNOWLEDGEMENT -> TAX INVOICE
# =========================================================

def _purchase_order_or_redirect(request, quote):
    purchase_order = getattr(quote, 'purchase_order', None)

    if purchase_order is None or not hasattr(purchase_order, 'proforma_invoice'):
        messages.error(request, 'This quotation has no proforma invoice yet.')
        return None

    return purchase_order


@buyer_required
@require_POST
def quote_mark_paid(request, quote_number):
    """Step 6: the buyer records that they have paid against the PI."""
    quote = get_object_or_404(Quote, quote_number=quote_number, buyer=request.user)
    purchase_order = _purchase_order_or_redirect(request, quote)

    if purchase_order is None:
        return redirect('quote_detail', quote_number=quote.quote_number)

    if purchase_order.payment_marked_at:
        messages.info(request, 'The payment has already been recorded.')
        return redirect('quote_detail', quote_number=quote.quote_number)

    reference = request.POST.get('payment_reference', '').strip()[:100]

    if not reference:
        messages.error(
            request,
            'Enter the payment reference (UTR / transaction ID) so the vendor '
            'can match your payment.'
        )
        return redirect('quote_detail', quote_number=quote.quote_number)

    purchase_order.payment_reference = reference
    purchase_order.payment_marked_at = timezone.now()
    purchase_order.save(update_fields=['payment_reference', 'payment_marked_at', 'updated_at'])

    _log_status_change(
        quote, request.user, quote.status, quote.status,
        f'Buyer recorded payment (ref {reference}).'
    )

    notify(
        recipient=quote.vendor.account,
        message=f'Payment recorded for {purchase_order.po_number} (ref {reference}). Please acknowledge.',
        link=reverse('quote_detail', args=[quote.quote_number]),
    )

    messages.success(request, 'Payment recorded. The vendor has been asked to acknowledge it.')
    return redirect('quote_detail', quote_number=quote.quote_number)


@vendor_required
@require_POST
def quote_ack_payment(request, quote_number):
    """Step 7: the vendor confirms the payment reached them."""
    quote = get_object_or_404(Quote, quote_number=quote_number, vendor=request.vendor)
    purchase_order = _purchase_order_or_redirect(request, quote)

    if purchase_order is None:
        return redirect('quote_detail', quote_number=quote.quote_number)

    if not purchase_order.payment_marked_at:
        messages.error(request, 'The buyer has not recorded a payment yet.')
        return redirect('quote_detail', quote_number=quote.quote_number)

    if purchase_order.payment_acknowledged_at:
        messages.info(request, 'The payment has already been acknowledged.')
        return redirect('quote_detail', quote_number=quote.quote_number)

    purchase_order.payment_acknowledged_at = timezone.now()
    purchase_order.save(update_fields=['payment_acknowledged_at', 'updated_at'])

    _log_status_change(
        quote, request.user, quote.status, quote.status,
        'Vendor acknowledged the payment.'
    )

    notify(
        recipient=quote.buyer,
        message=f'{quote.vendor.business_name} acknowledged your payment for {purchase_order.po_number}.',
        link=reverse('quote_detail', args=[quote.quote_number]),
    )

    messages.success(request, 'Payment acknowledged. You can now issue the tax invoice.')
    return redirect('quote_detail', quote_number=quote.quote_number)


@vendor_required
@require_POST
def quote_issue_tax_invoice(request, quote_number):
    """Step 8: the vendor issues the final tax invoice and closes the PO."""
    quote = get_object_or_404(Quote, quote_number=quote_number, vendor=request.vendor)
    purchase_order = _purchase_order_or_redirect(request, quote)

    if purchase_order is None:
        return redirect('quote_detail', quote_number=quote.quote_number)

    if not purchase_order.payment_acknowledged_at:
        messages.error(request, 'Acknowledge the payment before issuing the tax invoice.')
        return redirect('quote_detail', quote_number=quote.quote_number)

    if purchase_order.tax_invoice_number:
        messages.info(request, 'The tax invoice has already been issued.')
        return redirect('quote_detail', quote_number=quote.quote_number)

    with transaction.atomic():
        purchase_order.tax_invoice_number = next_tax_invoice_number()
        purchase_order.tax_invoice_issued_at = timezone.now()
        purchase_order.status = PurchaseOrder.STATUS_FULFILLED
        purchase_order.save(update_fields=[
            'tax_invoice_number', 'tax_invoice_issued_at', 'status', 'updated_at',
        ])

        _log_status_change(
            quote, request.user, quote.status, quote.status,
            f'Tax invoice {purchase_order.tax_invoice_number} issued.'
        )

    notify(
        recipient=quote.buyer,
        message=f'Tax invoice {purchase_order.tax_invoice_number} issued for {purchase_order.po_number}.',
        link=reverse('quote_detail', args=[quote.quote_number]),
    )

    messages.success(request, f'Tax invoice {purchase_order.tax_invoice_number} issued.')
    return redirect('quote_detail', quote_number=quote.quote_number)


# =========================================================
# INVOICES: PRINTABLE PAGE + PDF DOWNLOADS
# =========================================================

INVOICE_KINDS = {
    'proforma': 'Proforma Invoice',
    'tax': 'Tax Invoice',
}


def _invoice_document(quote, kind):
    """(title, number, issued_at) for an invoice that exists, else None."""
    purchase_order = getattr(quote, 'purchase_order', None)

    if purchase_order is None:
        return None

    if kind == 'proforma':
        proforma_invoice = getattr(purchase_order, 'proforma_invoice', None)

        if proforma_invoice is None:
            return None

        return INVOICE_KINDS[kind], proforma_invoice.pi_number, proforma_invoice.created_at

    if kind == 'tax' and purchase_order.tax_invoice_number:
        return (
            INVOICE_KINDS[kind],
            purchase_order.tax_invoice_number,
            purchase_order.tax_invoice_issued_at,
        )

    return None


@login_required(login_url='login')
def invoice_view(request, quote_number, kind):
    """The printable HTML invoice (Print / Save as PDF from the browser)."""
    quote, is_buyer, is_vendor = _quote_for_party_or_404(request, quote_number)
    document = _invoice_document(quote, kind)

    if document is None:
        raise Http404('Invoice not found.')

    title, number, issued_at = document
    mobile_url = _mobile_url(request, quote)

    return render(
        request,
        'quotations/invoice.html',
        {
            'quote': quote,
            'kind': kind,
            'title': title,
            'number': number,
            'issued_at': issued_at,
            'purchase_order': quote.purchase_order,
            'steps': quote.lifecycle_steps(),
            'qr_code': qr_svg(mobile_url, size=120),
            'mobile_url': mobile_url,
            'amount_words': amount_in_words(quote.total),
            'is_buyer': is_buyer,
        }
    )


@login_required(login_url='login')
def tax_invoice_download(request, quote_number):
    quote, _, _ = _quote_for_party_or_404(request, quote_number)
    document = _invoice_document(quote, 'tax')

    if document is None:
        raise Http404('Tax invoice not found.')

    title, number, issued_at = document

    pdf = build_invoice_pdf(
        quote,
        title=title,
        number=number,
        issued_on=timezone.localtime(issued_at),
        qr_url=_mobile_url(request, quote),
    )

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{number}.pdf"'
    return response


@login_required(login_url='login')
def pi_download(request, pi_number):
    proforma_invoice = get_object_or_404(ProformaInvoice, pi_number=pi_number)
    quote = proforma_invoice.po.quote

    is_buyer = quote.buyer_id == request.user.id
    is_vendor = _is_vendor_for(request, quote)

    if not is_buyer and not is_vendor:
        raise Http404('Proforma invoice not found.')

    if not proforma_invoice.pdf_file:
        # Generate on demand rather than send the user away empty-handed.
        generate_proforma_pdf(proforma_invoice, qr_url=_mobile_url(request, quote))

    return FileResponse(
        proforma_invoice.pdf_file.open('rb'),
        as_attachment=True,
        filename=f'{proforma_invoice.pi_number}.pdf',
    )
