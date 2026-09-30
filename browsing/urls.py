from django.urls import path
from . import views


urlpatterns = [
    path('', views.recently_viewed, name='recently_viewed'),
]