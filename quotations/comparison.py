"""Side-by-side comparison of every vendor response to one buyer request.

A buyer request that goes out to several vendors produces one Quote per
vendor, all sharing a `request_group`. This module turns those quotes into a
ranked comparison with a "best for you" recommendation and a plain-English
reason for it.
"""

from decimal import Decimal


# How much each dimension contributes to the overall score.
WEIGHT_PRICE = Decimal('0.60')
WEIGHT_DELIVERY = Decimal('0.25')
WEIGHT_TERMS = Decimal('0.15')

# Label for each position in the ranking; anything below the last is "Average".
RANK_LABELS = ['Best Deal', 'Second Best Deal', 'Good']
RANK_FALLBACK = 'Average'


def rank_label(rank):
    """'Best Deal', 'Second Best Deal', 'Good', then 'Average' (rank is 1-based)."""
    if rank is None:
        return 'Awaiting quote'

    if rank <= len(RANK_LABELS):
        return RANK_LABELS[rank - 1]

    return RANK_FALLBACK


def _normalised(value, best, worst):
    """1.0 for the best value in the group, 0.0 for the worst."""
    if value is None:
        return Decimal('0.00')

    if best == worst:
        return Decimal('1.00')

    return (Decimal(worst) - Decimal(value)) / (Decimal(worst) - Decimal(best))


def _terms_score(quote):
    """Credit for the soft terms a buyer cares about beyond price and speed."""
    score = Decimal('0.00')

    if quote.warranty_terms:
        score += Decimal('0.40')

    if quote.payment_terms:
        score += Decimal('0.30')

    if quote.valid_until:
        score += Decimal('0.15')

    if quote.discount and quote.discount > 0:
        score += Decimal('0.15')

    return min(score, Decimal('1.00'))


def compare_quotes(quotes):
    """Rank `quotes` and pick a recommendation.

    Returns a dict with:
      rows            - one entry per quote, ranked best first
      priced_rows     - only the rows a vendor has actually priced
      best            - the recommended row (or None)
      awaiting        - quotes still waiting on a vendor response
    """
    quotes = list(quotes)

    priced = [q for q in quotes if q.is_priced and q.status not in (
        q.STATUS_CANCELLED, q.STATUS_REJECTED
    )]

    awaiting = [q for q in quotes if q not in priced]

    rows = []

    if priced:
        totals = [q.total for q in priced]
        best_total, worst_total = min(totals), max(totals)

        delivery_values = [
            q.delivery_days for q in priced if q.delivery_days is not None
        ]

        if delivery_values:
            best_delivery = min(delivery_values)
            worst_delivery = max(delivery_values)
        else:
            best_delivery = worst_delivery = None

        for quote in priced:
            price_score = _normalised(quote.total, best_total, worst_total)

            if best_delivery is None or quote.delivery_days is None:
                delivery_score = Decimal('0.00')
            else:
                delivery_score = _normalised(
                    quote.delivery_days, best_delivery, worst_delivery
                )

            terms_score = _terms_score(quote)

            badges = []

            if quote.total == best_total:
                badges.append('Lowest price')

            if (
                best_delivery is not None
                and quote.delivery_days == best_delivery
                and worst_delivery != best_delivery
            ):
                badges.append('Fastest delivery')

            if terms_score == max(_terms_score(q) for q in priced) and len(priced) > 1:
                badges.append('Best terms')

            rows.append({
                'quote': quote,
                'score': (
                    WEIGHT_PRICE * price_score
                    + WEIGHT_DELIVERY * delivery_score
                    + WEIGHT_TERMS * terms_score
                ),
                'price_score': price_score,
                'delivery_score': delivery_score,
                'terms_score': terms_score,
                'badges': badges,
                'is_best': False,
                'reason': '',
            })

        rows.sort(key=lambda row: (-row['score'], row['quote'].total))

        for rank, row in enumerate(rows, start=1):
            row['rank'] = rank
            row['rank_label'] = rank_label(rank)

        best_row = rows[0]
        best_row['is_best'] = True
        best_row['reason'] = _reason_for(best_row, rows)

    for quote in awaiting:
        rows.append({
            'quote': quote,
            'score': None,
            'price_score': None,
            'delivery_score': None,
            'terms_score': None,
            'badges': [],
            'is_best': False,
            'reason': '',
            'rank': None,
            'rank_label': rank_label(None),
        })

    priced_rows = [row for row in rows if row['score'] is not None]

    return {
        'rows': rows,
        'priced_rows': priced_rows,
        'best': priced_rows[0] if priced_rows else None,
        'awaiting': awaiting,
    }


def _reason_for(row, rows):
    """A short, concrete explanation of why this quote is the recommendation."""
    quote = row['quote']
    others = [r for r in rows if r is not row]

    if not others:
        return (
            f'{quote.vendor.business_name} is the only vendor who has priced '
            f'this request so far.'
        )

    reasons = []

    cheapest = min(r['quote'].total for r in rows)
    dearest = max(r['quote'].total for r in rows)

    if quote.total == cheapest and cheapest != dearest:
        saving = dearest - cheapest
        reasons.append(
            f'lowest total at Rs.{quote.total} '
            f'(Rs.{saving} less than the highest offer)'
        )
    elif quote.total == cheapest:
        reasons.append(f'lowest total at Rs.{quote.total}')

    delivery_values = [
        r['quote'].delivery_days for r in rows
        if r['quote'].delivery_days is not None
    ]

    if (
        quote.delivery_days is not None
        and delivery_values
        and quote.delivery_days == min(delivery_values)
        and min(delivery_values) != max(delivery_values)
    ):
        reasons.append(f'fastest delivery at {quote.delivery_days} days')

    if row['terms_score'] >= max(r['terms_score'] for r in others):
        term_bits = []

        if quote.warranty_terms:
            term_bits.append(f'warranty: {quote.warranty_terms}')

        if quote.payment_terms:
            term_bits.append(f'payment: {quote.payment_terms}')

        if term_bits:
            reasons.append('best terms (' + '; '.join(term_bits) + ')')

    if not reasons:
        reasons.append(
            f'the best overall balance of price (Rs.{quote.total}), '
            f'delivery and terms'
        )

    return (
        f'{quote.vendor.business_name} offers '
        + ', and '.join(reasons)
        + '.'
    )


COMPARISON_FIELDS = [
    ('Quotation number', 'quote_number'),
    ('Status', 'status_display'),
    ('Subtotal', 'subtotal'),
    ('Discount', 'discount'),
    ('Tax rate', 'tax_rate_display'),
    ('Tax', 'tax'),
    ('Delivery / freight', 'shipping_charges'),
    ('Packaging & handling', 'packaging_charges'),
    ('Total', 'total'),
    ('Delivery lead time', 'delivery_display'),
    ('Requested delivery date', 'requested_delivery_date'),
    ('Valid until', 'valid_until'),
    ('Payment terms', 'payment_terms'),
    ('Warranty / support', 'warranty_terms'),
    ('Vendor notes', 'vendor_notes'),
    ('Vendor GST number', 'vendor_gst_number'),
    ('Bank - account holder', 'vendor_bank_account_name'),
    ('Bank - account number', 'vendor_bank_account_number'),
    ('Bank - IFSC', 'vendor_bank_ifsc'),
    ('Bank - name', 'vendor_bank_name'),
]


def comparison_matrix(rows):
    """Field-by-field rows for the detailed side-by-side table."""
    matrix = []

    for label, attr in COMPARISON_FIELDS:
        values = []

        for row in rows:
            quote = row['quote']

            if attr == 'status_display':
                value = quote.get_status_display()
            elif attr == 'delivery_display':
                value = (
                    f'{quote.delivery_days} days'
                    if quote.delivery_days is not None else ''
                )
            elif attr == 'tax_rate_display':
                value = f'{quote.tax_rate}%'
            else:
                value = getattr(quote, attr, '')

            values.append({'value': value, 'is_best': row['is_best']})

        matrix.append({'label': label, 'values': values})

    return matrix


def _item_key(item):
    """Items from different vendors are the "same item" when their names match.

    Each vendor quotes on its own catalogue products, so product ids never
    line up across vendors - the product name is what the buyer compares.
    """
    return ' '.join(item.product.product_name.lower().split())


def item_rate_matrix(rows):
    """Item-by-item unit rates across every vendor, with the best rate marked.

    Returns a list of lines, one per distinct item:
      {'name', 'quantity', 'cells': [one per row: None or
        {'unit_price', 'line_total', 'quantity', 'is_estimate', 'is_best_rate'}],
       'best_rate'}

    Only vendor-priced rates compete for "best rate"; list-price estimates
    are shown but never highlighted.
    """
    lines = {}

    for column, row in enumerate(rows):
        quote = row['quote']
        priced = row['score'] is not None

        for item in quote.items.all():
            key = _item_key(item)

            line = lines.setdefault(key, {
                'name': item.product.product_name,
                'quantity': item.quantity,
                'cells': [None] * len(rows),
                'best_rate': None,
            })

            line['cells'][column] = {
                'unit_price': item.effective_price,
                'line_total': item.line_total(),
                'quantity': item.quantity,
                'is_estimate': not priced,
                'is_best_rate': False,
            }

    for line in lines.values():
        priced_cells = [
            cell for cell in line['cells']
            if cell is not None and not cell['is_estimate']
        ]

        if not priced_cells:
            continue

        best = min(cell['unit_price'] for cell in priced_cells)
        line['best_rate'] = best

        for cell in priced_cells:
            cell['is_best_rate'] = cell['unit_price'] == best

    return list(lines.values())
