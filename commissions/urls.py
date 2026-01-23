from django.urls import path, include
from . import views
from .approvals import views as approval_views

urlpatterns = [
    # Commission creation
    path('create/', views.create_commission, name='create-commission'),
    path('bulk-create/', views.bulk_create_commissions, name='bulk-create-commissions'),
    
    # Commission queries
    path('my-commissions/', views.my_commissions, name='my-commissions'),
    path('my-team/', views.my_team_commissions, name='my-team-commissions'),
    path('my-payslips/', views.my_payslips, name='my-payslips'),
    path('', views.all_commissions, name='all-commissions'),  # Admin only
    path('<int:pk>/', views.commission_detail, name='commission-detail'),
    
    # Approval Workflows (Phase 3)
    path('approvals/pending/', approval_views.PendingApprovalsListView.as_view(), name='approvals-pending'),
    path('<int:pk>/approval/', approval_views.CommissionApprovalDetailView.as_view(), name='commission-approval-detail'),
    path('<int:pk>/submit/', approval_views.CommissionSubmitView.as_view(), name='commission-submit'),
    path('<int:pk>/approve/', approval_views.CommissionApproveView.as_view(), name='commission-approve'),
    path('<int:pk>/reject/', approval_views.CommissionRejectView.as_view(), name='commission-reject'),
    path('<int:pk>/mark-paid/', approval_views.CommissionPayView.as_view(), name='commission-mark-paid'),
    path('<int:pk>/timeline/', approval_views.CommissionTimelineView.as_view(), name='commission-timeline'),
    
    # Adjustments (Phase 2 legacy history replaced by timeline above, but keeping for now if needed)
    path('<int:pk>/adjust/', views.create_adjustment, name='create-adjustment'),
    path('<int:pk>/history/', views.commission_history, name='commission-history'), # Legacy, consider removal
    
    # Summary/Dashboard
    path('summary/', views.commission_summary, name='commission-summary'),
]
