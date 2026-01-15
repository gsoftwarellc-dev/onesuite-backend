from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/hierarchy/', include('hierarchy.urls')),
    path('api/commissions/', include('commissions.urls')),
    path('api/approvals/', include('approvals.urls')),
    path('api/payouts/', include('payouts.urls')),
]
