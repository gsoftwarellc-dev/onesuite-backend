from rest_framework import serializers
from django.contrib.auth import get_user_model
from hierarchy.models import ReportingLine

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    is_manager = serializers.SerializerMethodField()

    def get_is_manager(self, obj):
        if getattr(obj, 'is_manager', False):
            return True
        return ReportingLine.objects.filter(manager=obj, is_active=True).exists()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_manager', 'role']
