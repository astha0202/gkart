from django.contrib import admin

from .models import ProformaInvoice, PurchaseOrder, Quote, QuoteHistory, QuoteItem


class QuoteItemInline(admin.TabularInline):
    model = QuoteItem
    extra = 0


class QuoteHistoryInline(admin.TabularInline):
    model = QuoteHistory
    extra = 0
    can_delete = False
    readonly_fields = ('changed_by', 'from_status', 'to_status', 'comment', 'changed_at')


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ('quote_number', 'buyer', 'vendor', 'status', 'total', 'created_at')
    list_filter = ('status', 'vendor')
    search_fields = (
        'quote_number',
        'buyer__username',
        'buyer__email',
        'vendor__business_name',
    )
    inlines = [QuoteItemInline, QuoteHistoryInline]


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('po_number', 'quote', 'buyer', 'vendor', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('po_number', 'quote__quote_number')


@admin.register(ProformaInvoice)
class ProformaInvoiceAdmin(admin.ModelAdmin):
    list_display = ('pi_number', 'po', 'created_at')
    search_fields = ('pi_number', 'po__po_number')
