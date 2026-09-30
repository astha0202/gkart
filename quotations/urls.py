from django.urls import path

from . import views

urlpatterns = [
    path('', views.quote_list_buyer, name='quote_list_buyer'),
    path('vendor/', views.quote_list_vendor, name='quote_list_vendor'),

    path('new/', views.quote_request_page, name='quote_request_page'),
    path('request/<slug:slug>/', views.quote_request_create, name='quote_request_create'),

    path('upload/', views.quote_upload, name='quote_upload'),
    path('upload/clear/', views.quote_upload_clear, name='quote_upload_clear'),
    path('upload/template.csv', views.quote_upload_template, name='quote_upload_template'),

    # Public target of the QR code on an approved quotation.
    path('m/<uuid:token>/', views.quote_mobile, name='quote_mobile'),

    path(
        'compare/<uuid:request_group>/',
        views.quote_compare,
        name='quote_compare'
    ),
    path(
        'compare/<uuid:request_group>/details/',
        views.quote_compare_detail,
        name='quote_compare_detail'
    ),

    path('vendor/<str:quote_number>/send/', views.quote_send, name='quote_send'),

    path('invoice/<str:pi_number>/download/', views.pi_download, name='pi_download'),

    path('<str:quote_number>/', views.quote_detail, name='quote_detail'),
    path('<str:quote_number>/accept/', views.quote_accept, name='quote_accept'),
    path('<str:quote_number>/reject/', views.quote_reject, name='quote_reject'),
    path('<str:quote_number>/cancel/', views.quote_cancel, name='quote_cancel'),

    path('<str:quote_number>/payment/', views.quote_mark_paid, name='quote_mark_paid'),
    path('<str:quote_number>/payment/ack/', views.quote_ack_payment, name='quote_ack_payment'),
    path(
        '<str:quote_number>/tax-invoice/issue/',
        views.quote_issue_tax_invoice,
        name='quote_issue_tax_invoice'
    ),
    path(
        '<str:quote_number>/tax-invoice/download/',
        views.tax_invoice_download,
        name='tax_invoice_download'
    ),
    path(
        '<str:quote_number>/invoice/<str:kind>/',
        views.invoice_view,
        name='invoice_view'
    ),
]
