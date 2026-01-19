from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'methods', views.PaymentMethodViewSet, basename='paymentmethod')
router.register(r'w9', views.W9ViewSet, basename='w9')
router.register(r'transactions', views.PaymentTransactionViewSet, basename='paymenttransaction')
router.register(r'tax-documents', views.TaxDocumentViewSet, basename='taxdocument')
router.register(r'reconciliations', views.ReconciliationViewSet, basename='reconciliation')

urlpatterns = [
    path('', include(router.urls)),
]
