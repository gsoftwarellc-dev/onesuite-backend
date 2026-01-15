from django.urls import path, include
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
# router.register(r'hierarchy', HierarchyViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
