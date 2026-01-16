from django.contrib import admin
from django.urls import path, include

from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    return HttpResponse("OK")

urlpatterns = [
    path('health/', health_check),
    path('admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/hierarchy/', include('hierarchy.urls')),
    path('api/commissions/', include('commissions.urls')),
    path('api/approvals/', include('approvals.urls')),
    path('api/payouts/', include('payouts.urls')),
]
