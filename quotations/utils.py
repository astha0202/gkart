import csv
import io
import re
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.core.validators import URLValidator
from django.utils import timezone

from reportlab.graphics import renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def send_quote_email(quote):
    """Email the buyer once the vendor has priced and sent the quotation."""
    subject = f"Your quotation {quote.quote_number} is ready"

    lines = [
        f"Dear {quote.buyer.full_name or quote.buyer.username},",
        "",
        "Your quotation request has been priced by the vendor:",
        "",
    ]

    for item in quote.items.select_related('product'):
        lines.append(
            f"- {item.product.product_name} x {item.quantity} "
            f"@ Rs.{item.quoted_price} = Rs.{item.line_total()}"
        )

    lines += [
        "",
        f"Subtotal: Rs.{quote.subtotal}",
        f"GST ({quote.tax_rate}%): Rs.{quote.tax}",
        f"Total: Rs.{quote.total}",
        f"Valid until: {quote.valid_until or 'N/A'}",
        "",
        "Please log in to your account to accept or reject this quotation.",
        "",
        f"Regards,\n{quote.vendor.business_name}",
    ]

    email = EmailMessage(
        subject,
        "\n".join(lines),
        settings.DEFAULT_FROM_EMAIL,
        [quote.buyer.email],
    )
    email.send(fail_silently=True)


# =========================================================
# QR CODES
# =========================================================

def _qr_drawing(data, size):
    widget = QrCodeWidget(data, barLevel='M')
    x1, y1, x2, y2 = widget.getBounds()

    drawing = Drawing(
        size,
        size,
        transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0],
    )
    drawing.add(widget)
    return drawing


def qr_svg(data, size=150):
    """An inline <svg> QR code for `data` (no XML prologue, safe to embed)."""
    svg = renderSVG.drawToString(_qr_drawing(data, size))
    return svg[svg.index('<svg'):]


# =========================================================
# BULK UPLOAD: EXCEL / CSV PRODUCT LISTS
# =========================================================

MAX_UPLOAD_ROWS = 500

# Accepted spellings for each column, compared after lower-casing and
# collapsing punctuation/whitespace.
COLUMN_ALIASES = {
    'name': {
        'product name', 'product', 'item name', 'item', 'name',
        'component', 'component name', 'product description',
    },
    'quantity': {'quantity', 'qty', 'qnty', 'units', 'no of units', 'nos'},
    'link': {
        'supporting link', 'link', 'url', 'supporting url', 'reference',
        'reference link', 'datasheet', 'product link',
    },
}


class UploadError(Exception):
    """The file could not be read as a product list at all."""


def _normalise_header(value):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).split())


def _read_rows(upload):
    name = (upload.name or '').lower()

    if name.endswith('.csv'):
        raw = upload.read()

        for encoding in ('utf-8-sig', 'cp1252', 'latin-1'):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

        return list(csv.reader(io.StringIO(text)))

    # .xlsx / .xlsm
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(upload, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises a variety of zip/xml errors
        raise UploadError(
            'That Excel file could not be opened. Save it as .xlsx and try again.'
        ) from exc

    try:
        sheet = workbook.active
        return [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def _find_columns(rows):
    """(header_row_index, {'name': col, 'quantity': col, 'link': col})."""
    for index, row in enumerate(rows[:10]):
        headers = [_normalise_header(cell) for cell in row]
        columns = {}

        for key, aliases in COLUMN_ALIASES.items():
            for col, header in enumerate(headers):
                if header in aliases:
                    columns[key] = col
                    break

        if 'name' in columns:
            return index, columns

    raise UploadError(
        'No "Product Name" column was found. The first row should be a header '
        'with Product Name, Quantity and Supporting Link.'
    )


def _parse_quantity(value):
    if value is None or str(value).strip() == '':
        return 1

    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
    else:
        match = re.search(r'\d+(\.\d+)?', str(value))

        if not match:
            return None

        number = Decimal(match.group())

    if number != number.to_integral_value() or number < 1:
        return None

    return int(number)


_url_validator = URLValidator(schemes=['http', 'https'])


def _parse_link(value):
    link = str(value or '').strip()

    if not link:
        return '', None

    if not re.match(r'^https?://', link, re.I):
        link = f'https://{link}'

    try:
        _url_validator(link)
    except ValidationError:
        return '', f'"{value}" is not a valid link and was ignored'

    return link[:500], None


def parse_product_sheet(upload):
    """Read an Excel/CSV product list.

    Returns (rows, problems): rows are dicts {'row', 'name', 'quantity',
    'link'}; problems are human-readable notes about rows that were skipped
    or partly ignored. Raises UploadError if the file is unusable.
    """
    rows = _read_rows(upload)

    if not rows:
        raise UploadError('The file is empty.')

    header_index, columns = _find_columns(rows)

    parsed = []
    problems = []

    def cell(row, key):
        col = columns.get(key)
        return row[col] if col is not None and col < len(row) else None

    for offset, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(str(value or '').strip() for value in row):
            continue

        if len(parsed) >= MAX_UPLOAD_ROWS:
            problems.append(f'Only the first {MAX_UPLOAD_ROWS} rows were read.')
            break

        name = ' '.join(str(cell(row, 'name') or '').split())

        if not name:
            problems.append(f'Row {offset}: no product name, skipped.')
            continue

        quantity = _parse_quantity(cell(row, 'quantity'))

        if quantity is None:
            problems.append(
                f'Row {offset} ({name}): quantity "{cell(row, "quantity")}" '
                f'is not a whole number, skipped.'
            )
            continue

        link, link_problem = _parse_link(cell(row, 'link'))

        if link_problem:
            problems.append(f'Row {offset} ({name}): {link_problem}.')

        parsed.append({
            'row': offset,
            'name': name,
            'quantity': quantity,
            'link': link,
        })

    if not parsed and not problems:
        raise UploadError('The file has a header row but no products under it.')

    return parsed, problems


def _normalise_name(value):
    return ' '.join(str(value).lower().split())


def match_catalog_products(rows, products):
    """Match parsed upload rows to catalogue products.

    A name can match one product per vendor - that is what lets one uploaded
    list go out to every vendor selling the item, for side-by-side
    comparison. Exact (case-insensitive) name matches win; otherwise a
    product whose name contains the uploaded text is accepted.

    Returns (lines, unmatched): lines are dicts {'product', 'quantity',
    'link', 'source_name', 'exact'}; unmatched are the rows with no match.
    """
    products = list(products)
    by_name = {}

    for product in products:
        by_name.setdefault(_normalise_name(product.product_name), []).append(product)

    lines = []
    unmatched = []

    for row in rows:
        wanted = _normalise_name(row['name'])
        matches = by_name.get(wanted)
        exact = bool(matches)

        if not matches and len(wanted) >= 3:
            matches = [
                p for p in products
                if wanted in _normalise_name(p.product_name)
            ]

        if not matches:
            unmatched.append(row)
            continue

        # One product per vendor: the closest-named one.
        per_vendor = {}

        for product in sorted(matches, key=lambda p: len(p.product_name)):
            per_vendor.setdefault(product.vendor_id, product)

        for product in per_vendor.values():
            lines.append({
                'product': product,
                'quantity': row['quantity'],
                'link': row['link'],
                'source_name': row['name'],
                'exact': exact,
            })

    return lines, unmatched


# =========================================================
# INVOICE PDF (proforma + tax invoice share one layout)
# =========================================================

INK = colors.HexColor('#0f172a')
NAVY = colors.HexColor('#1e293b')
ACCENT = colors.HexColor('#f59e0b')
MUTED = colors.HexColor('#64748b')
LINE = colors.HexColor('#e2e8f0')
SOFT = colors.HexColor('#f8fafc')
HEAD = colors.HexColor('#eef2f7')

_ONES = [
    '', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
    'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
    'Seventeen', 'Eighteen', 'Nineteen',
]
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def _two_digits(n):
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + ' ' + _ONES[n % 10]).strip()


def _three_digits(n):
    hundred, rest = divmod(n, 100)
    words = []

    if hundred:
        words.append(f'{_ONES[hundred]} Hundred')
    if rest:
        words.append(_two_digits(rest))

    return ' '.join(words)


def amount_in_words(amount):
    """Indian-system amount in words, e.g. 'Rupees One Lakh Twenty Only'."""
    amount = Decimal(amount).quantize(Decimal('0.01'))
    rupees = int(amount)
    paise = int((amount - rupees) * 100)

    if rupees == 0:
        words = 'Zero'
    else:
        parts = []
        crore, rupees = divmod(rupees, 10_000_000)
        lakh, rupees = divmod(rupees, 100_000)
        thousand, rupees = divmod(rupees, 1000)

        if crore:
            parts.append(f'{_three_digits(crore) if crore < 1000 else crore} Crore')
        if lakh:
            parts.append(f'{_two_digits(lakh)} Lakh')
        if thousand:
            parts.append(f'{_two_digits(thousand)} Thousand')
        if rupees:
            parts.append(_three_digits(rupees))

        words = ' '.join(parts)

    text = f'Rupees {words}'

    if paise:
        text += f' and {_two_digits(paise)} Paise'

    return text + ' Only'


def _money(value):
    return f'Rs. {Decimal(value or 0):,.2f}'


def build_invoice_pdf(quote, title, number, issued_on, qr_url=None):
    """Render a professional A4 invoice for `quote` and return the PDF bytes.

    Used for both the Proforma Invoice (step 5) and the Tax Invoice (step 8).
    """
    vendor = quote.vendor
    purchase_order = getattr(quote, 'purchase_order', None)

    buffer = BytesIO()
    width, height = A4
    margin = 16 * mm

    styles = {
        'label': ParagraphStyle('label', fontName='Helvetica-Bold', fontSize=7.5,
                                textColor=MUTED, leading=10, spaceAfter=2),
        'body': ParagraphStyle('body', fontName='Helvetica', fontSize=8.8,
                               textColor=INK, leading=12),
        'bold': ParagraphStyle('bold', fontName='Helvetica-Bold', fontSize=10,
                               textColor=INK, leading=13),
        'small': ParagraphStyle('small', fontName='Helvetica', fontSize=7.5,
                                textColor=MUTED, leading=10),
        'section': ParagraphStyle('section', fontName='Helvetica-Bold', fontSize=9.5,
                                  textColor=NAVY, leading=12, spaceBefore=4, spaceAfter=4),
        'right': ParagraphStyle('right', fontName='Helvetica', fontSize=8.8,
                                textColor=INK, leading=12, alignment=TA_RIGHT),
    }

    def header(canvas, doc):
        canvas.saveState()

        band = 30 * mm
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - band, width, band, stroke=0, fill=1)
        canvas.setFillColor(ACCENT)
        canvas.rect(0, height - band - 1.4 * mm, width, 1.4 * mm, stroke=0, fill=1)

        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica-Bold', 17)
        canvas.drawString(margin, height - 13 * mm, title.upper())
        canvas.setFont('Helvetica', 9)
        canvas.drawString(margin, height - 19.5 * mm, vendor.business_name)

        right = width - margin
        canvas.setFont('Helvetica-Bold', 10)
        canvas.drawRightString(right, height - 11 * mm, number)
        canvas.setFont('Helvetica', 8.5)
        canvas.drawRightString(right, height - 16.5 * mm, f'Date: {issued_on:%d %b %Y}')

        refs = f'Quotation: {quote.quote_number}'
        if purchase_order:
            refs = f'PO: {purchase_order.po_number}   ·   ' + refs
        canvas.drawRightString(right, height - 21.5 * mm, refs)

        canvas.setFillColor(MUTED)
        canvas.setFont('Helvetica', 7.5)
        canvas.drawString(
            margin, 9 * mm,
            'This is a computer-generated document and does not require a physical signature.'
        )
        canvas.drawRightString(width - margin, 9 * mm, f'Page {doc.page}')

        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=38 * mm,
        bottomMargin=18 * mm,
        title=f'{title} {number}',
        author=vendor.business_name,
    )

    content_width = width - 2 * margin
    story = []

    # ----- parties + QR -----
    def party(label, lines):
        cells = [Paragraph(label, styles['label'])]

        for index, text in enumerate(line for line in lines if line):
            cells.append(Paragraph(text, styles['bold'] if index == 0 else styles['body']))

        return cells

    seller = party('SELLER', [
        vendor.business_name,
        (vendor.business_address or '').replace('\n', '<br/>'),
        f'GSTIN: {quote.vendor_gst_number or vendor.gst_number}'
        if (quote.vendor_gst_number or vendor.gst_number) else '',
        f'PAN: {vendor.pan_number}' if vendor.pan_number else '',
        vendor.business_email or vendor.account.email,
        vendor.phone_number,
    ])

    buyer = party('BILL TO', [
        quote.contact_name or quote.buyer.full_name or quote.buyer.username,
        (quote.billing_address or '').replace('\n', '<br/>'),
        f'GSTIN: {quote.buyer_gst_number}' if quote.buyer_gst_number else '',
        f'PAN: {quote.buyer_pan_number}' if quote.buyer_pan_number else '',
        quote.contact_email or quote.buyer.email,
        quote.contact_phone or quote.buyer.phone,
    ])

    qr_cell = ''
    qr_size = 27 * mm

    if qr_url:
        qr_cell = [
            _qr_drawing(qr_url, qr_size),
            Paragraph('Scan for live status', styles['small']),
        ]

    party_table = Table(
        [[seller, buyer, qr_cell]],
        colWidths=[content_width * 0.4, content_width * 0.4, content_width * 0.2],
    )
    party_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (1, 0), 0.6, LINE),
        ('LINEAFTER', (0, 0), (0, 0), 0.6, LINE),
        ('BACKGROUND', (0, 0), (1, 0), SOFT),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('ALIGN', (2, 0), (2, 0), 'CENTER'),
    ]))
    story += [party_table, Spacer(1, 7 * mm)]

    # ----- items -----
    story.append(Paragraph('ITEMS', styles['section']))

    data = [['#', 'Item', 'Qty', 'Unit price', 'Amount']]

    for index, item in enumerate(quote.items.select_related('product'), start=1):
        data.append([
            str(index),
            Paragraph(item.product.product_name, styles['body']),
            str(item.quantity),
            _money(item.effective_price),
            _money(item.line_total()),
        ])

    items_table = Table(
        data,
        colWidths=[
            content_width * 0.06, content_width * 0.50, content_width * 0.10,
            content_width * 0.17, content_width * 0.17,
        ],
        repeatRows=1,
    )

    item_style = [
        ('BACKGROUND', (0, 0), (-1, 0), HEAD),
        ('TEXTCOLOR', (0, 0), (-1, 0), NAVY),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8.8),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, LINE),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]

    for row in range(2, len(data), 2):
        item_style.append(('BACKGROUND', (0, row), (-1, row), SOFT))

    items_table.setStyle(TableStyle(item_style))
    story += [items_table, Spacer(1, 5 * mm)]

    # ----- totals -----
    totals = [
        ['Subtotal', _money(quote.subtotal)],
    ]

    if quote.discount:
        totals.append(['Discount', f'- {_money(quote.discount)}'])

    totals += [
        ['Taxable amount', _money(quote.taxable_amount)],
        [f'GST @ {quote.tax_rate.normalize():f}%', _money(quote.tax)],
    ]

    if quote.shipping_charges:
        totals.append(['Delivery / freight', _money(quote.shipping_charges)])

    if quote.packaging_charges:
        totals.append(['Packaging & handling', _money(quote.packaging_charges)])

    totals.append(['GRAND TOTAL', _money(quote.total)])

    totals_table = Table(totals, colWidths=[content_width * 0.22, content_width * 0.18])
    totals_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 8.8),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('TEXTCOLOR', (0, 0), (0, -2), MUTED),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND', (0, -1), (-1, -1), NAVY),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.white),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 10),
        ('TOPPADDING', (0, -1), (-1, -1), 7),
        ('BOTTOMPADDING', (0, -1), (-1, -1), 7),
    ]))

    words = [
        Paragraph('AMOUNT IN WORDS', styles['label']),
        Paragraph(amount_in_words(quote.total), styles['body']),
    ]

    summary = Table(
        [[words, totals_table]],
        colWidths=[content_width * 0.6, content_width * 0.4],
    )
    summary.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story += [KeepTogether(summary), Spacer(1, 7 * mm)]

    # ----- payment + terms -----
    bank_lines = [
        ('Bank', quote.vendor_bank_name or vendor.bank_name),
        ('A/C holder', quote.vendor_bank_account_name or vendor.bank_account_name),
        ('A/C number', quote.vendor_bank_account_number or vendor.bank_account_number),
        ('IFSC', quote.vendor_bank_ifsc or vendor.bank_ifsc),
        ('Branch', vendor.bank_branch),
    ]

    term_lines = [
        ('Payment', quote.payment_terms or vendor.terms_payment),
        ('Delivery', f'{quote.delivery_days} days from confirmed PO'
            if quote.delivery_days is not None else vendor.terms_delivery),
        ('Validity', f'Until {quote.valid_until:%d %b %Y}'
            if quote.valid_until else vendor.terms_validity),
        ('Warranty', quote.warranty_terms),
    ]

    def detail_block(label, pairs):
        cells = [Paragraph(label, styles['label'])]

        for key, value in pairs:
            if value:
                cells.append(Paragraph(f'<font color="#64748b">{key}:</font> {value}', styles['body']))

        return cells

    blocks = Table(
        [[
            detail_block('PAYMENT DETAILS', bank_lines),
            detail_block('TERMS & CONDITIONS', term_lines),
        ]],
        colWidths=[content_width * 0.5, content_width * 0.5],
    )
    blocks.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (-1, -1), 0.6, LINE),
        ('LINEAFTER', (0, 0), (0, 0), 0.6, LINE),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story += [KeepTogether(blocks), Spacer(1, 6 * mm)]

    notes = quote.vendor_notes or vendor.terms_remarks

    if notes:
        story += [
            Paragraph('NOTES', styles['label']),
            Paragraph(notes.replace('\n', '<br/>'), styles['body']),
            Spacer(1, 6 * mm),
        ]

    signature = Table(
        [[
            '',
            [
                Paragraph(f'For {vendor.business_name}', styles['bold']),
                Spacer(1, 12 * mm),
                Paragraph('Authorised Signatory', styles['small']),
            ],
        ]],
        colWidths=[content_width * 0.6, content_width * 0.4],
    )
    story.append(KeepTogether(signature))

    doc.build(story, onFirstPage=header, onLaterPages=header)

    return buffer.getvalue()


def generate_proforma_pdf(proforma_invoice, qr_url=None):
    """Render the Proforma Invoice PDF and attach it to the instance."""
    quote = proforma_invoice.po.quote

    pdf = build_invoice_pdf(
        quote,
        title='Proforma Invoice',
        number=proforma_invoice.pi_number,
        issued_on=timezone.localtime(proforma_invoice.created_at or timezone.now()),
        qr_url=qr_url,
    )

    proforma_invoice.pdf_file.save(
        f"{proforma_invoice.pi_number}.pdf",
        ContentFile(pdf),
        save=True,
    )
