from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PayoutBatchViewSet, PayoutViewSet

router = DefaultRouter()
router.register(r'batches', PayoutBatchViewSet, basename='payout-batch')
router.register(r'', PayoutViewSet, basename='payout')

urlpatterns = [
    path('', include(router.urls)),
]
