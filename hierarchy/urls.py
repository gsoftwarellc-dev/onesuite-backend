from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'reporting-lines', views.ReportingLineViewSet, basename='reporting-line')

urlpatterns = [
    # User endpoints
    path('my-manager/', views.my_manager, name='my-manager'),
    path('my-team/', views.my_team, name='my-team'),
    path('my-team/full/', views.my_team_full, name='my-team-full'),
    
    # Admin endpoints
    path('assign/', views.assign_manager, name='assign-manager'),
    path('change-manager/', views.change_manager, name='change-manager'),
    path('<int:pk>/deactivate/', views.deactivate_reporting_line, name='deactivate-reporting-line'),
    path('historical/', views.historical_hierarchy, name='historical-hierarchy'),
    path('user/<int:user_id>/history/', views.user_manager_history, name='user-manager-history'),
    
    # Router URLs (for reporting-lines list/detail)
    path('', include(router.urls)),
]
