from django.shortcuts import render


def recently_viewed(request):
    return render(request, 'recently_viewed.html')