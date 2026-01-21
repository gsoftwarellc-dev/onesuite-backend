from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User

from .forms import CustomUserCreationForm, CustomUserChangeForm

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Custom User Admin with role field support"""
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    
    fieldsets = BaseUserAdmin.fieldsets + (
        ('OneSuite Fields', {'fields': ('role', 'is_manager')}),
    )
    
    # Override add_fieldsets to include email and role
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'role', 'is_manager'),
        }),
    )
    list_display = ['username', 'email', 'role', 'is_manager', 'is_staff', 'is_active']
    list_filter = BaseUserAdmin.list_filter + ('role',)
