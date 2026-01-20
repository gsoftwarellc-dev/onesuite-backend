from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Custom User Admin with role field support"""
    fieldsets = BaseUserAdmin.fieldsets + (
        ('OneSuite Fields', {'fields': ('role', 'is_manager')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('OneSuite Fields', {'fields': ('role', 'is_manager')}),
    )
    list_display = ['username', 'email', 'role', 'is_manager', 'is_staff', 'is_active']
    list_filter = BaseUserAdmin.list_filter + ('role',)
