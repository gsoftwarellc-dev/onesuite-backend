from django.urls import path, include
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
# router.register(r'approvals', ApprovalViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
