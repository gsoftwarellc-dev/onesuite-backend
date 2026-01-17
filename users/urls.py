from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet, LoginView, RefreshView, logout_view, me_view

router = DefaultRouter()
router.register(r'', UserViewSet)

urlpatterns = [
    # JWT Authentication Endpoints
    path('auth/login/', LoginView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', RefreshView.as_view(), name='token_refresh'),
    path('auth/logout/', logout_view, name='logout'),
    path('auth/me/', me_view, name='me'),
    # Users API
    path('', include(router.urls)),
]
