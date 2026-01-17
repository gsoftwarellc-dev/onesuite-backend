from django.urls import path
from . import views

urlpatterns = [
    # Commission creation
    path('create/', views.create_commission, name='create-commission'),
    path('bulk-create/', views.bulk_create_commissions, name='bulk-create-commissions'),
    
    # Commission queries
    path('my-commissions/', views.my_commissions, name='my-commissions'),
    path('my-team/', views.my_team_commissions, name='my-team-commissions'),
    path('', views.all_commissions, name='all-commissions'),  # Admin only
    path('<int:pk>/', views.commission_detail, name='commission-detail'),
    
    # State transitions
    path('<int:pk>/submit/', views.submit_commission, name='submit-commission'),
    path('<int:pk>/approve/', views.approve_commission, name='approve-commission'),
    path('<int:pk>/reject/', views.reject_commission, name='reject-commission'),
    path('<int:pk>/mark-paid/', views.mark_paid, name='mark-paid'),
    
    # Adjustments
    path('<int:pk>/adjust/', views.create_adjustment, name='create-adjustment'),
    path('<int:pk>/history/', views.commission_history, name='commission-history'),
    
    # Summary/Dashboard
    path('summary/', views.commission_summary, name='commission-summary'),
]
