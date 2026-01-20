"""
Analytics URL Configuration
All 17 endpoints under /api/analytics/
"""
from django.urls import path
from .views import (
    # Dashboards
    FinanceDashboardView,
    ManagerDashboardView,
    ConsultantDashboardView,
    # Analytics
    CommissionMetricsView,
    PayoutMetricsView,
    TaxMetricsView,
    ReconciliationMetricsView,
    TopPerformersView,
    CommissionTrendView,
    PayoutTrendView,
    PendingCountView,
    # Reports/Exports
    CommissionDetailExportView,
    PayoutHistoryExportView,
    TaxYearSummaryExportView,
    ReconciliationExportView,
    MyEarningsExportView,
    ExportLogView,
)

urlpatterns = [
    # Dashboards (3)
    path('dashboards/finance/', FinanceDashboardView.as_view(), name='dashboard-finance'),
    path('dashboards/manager/', ManagerDashboardView.as_view(), name='dashboard-manager'),
    path('dashboards/consultant/', ConsultantDashboardView.as_view(), name='dashboard-consultant'),
    
    # Analytics - Metrics (4)
    path('commissions/metrics/', CommissionMetricsView.as_view(), name='commission-metrics'),
    path('payouts/metrics/', PayoutMetricsView.as_view(), name='payout-metrics'),
    path('tax/metrics/', TaxMetricsView.as_view(), name='tax-metrics'),
    path('reconciliation/metrics/', ReconciliationMetricsView.as_view(), name='reconciliation-metrics'),
    
    # Analytics - Other (4)
    path('commissions/top-performers/', TopPerformersView.as_view(), name='top-performers'),
    path('commissions/trend/', CommissionTrendView.as_view(), name='commission-trend'),
    path('payouts/trend/', PayoutTrendView.as_view(), name='payout-trend'),
    path('commissions/pending-count/', PendingCountView.as_view(), name='pending-count'),
    
    # Reports/Exports (6)
    path('reports/commission-detail/', CommissionDetailExportView.as_view(), name='export-commission-detail'),
    path('reports/payout-history/', PayoutHistoryExportView.as_view(), name='export-payout-history'),
    path('reports/tax-year-summary/<int:year>/', TaxYearSummaryExportView.as_view(), name='export-tax-summary'),
    path('reports/reconciliation/', ReconciliationExportView.as_view(), name='export-reconciliation'),
    path('reports/my-earnings/', MyEarningsExportView.as_view(), name='export-my-earnings'),
    path('exports/', ExportLogView.as_view(), name='export-logs'),
]
