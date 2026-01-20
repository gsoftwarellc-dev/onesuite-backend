from django.contrib import admin
from django.urls import path, include

from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    from django.db import connections
    from django.db.utils import OperationalError
    try:
        db_conn = connections['default']
        db_conn.cursor()
    except OperationalError:
        return HttpResponse("DB Error", status=503)
    return HttpResponse("OK")

urlpatterns = [
    path('health/', health_check),
    path('admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/hierarchy/', include('hierarchy.urls')),
    path('api/commissions/', include('commissions.urls')),
    path('api/approvals/', include('approvals.urls')),
    path('api/payouts/', include('payouts.urls')),
    path('api/payments/', include('payments.urls')),
    path('api/analytics/', include('analytics.urls')),
]
