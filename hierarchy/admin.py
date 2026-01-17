from django.contrib import admin
from .models import ReportingLine


@admin.register(ReportingLine)
class ReportingLineAdmin(admin.ModelAdmin):
    """Admin interface for managing reporting lines"""
    
    list_display = [
        'id',
        'consultant',
        'manager',
        'start_date',
        'end_date',
        'is_active',
        'created_at'
    ]
    
    list_filter = [
        'is_active',
        'start_date',
        'created_at'
    ]
    
    search_fields = [
        'consultant__username',
        'consultant__first_name',
        'consultant__last_name',
        'manager__username',
        'manager__first_name',
        'manager__last_name',
    ]
    
    readonly_fields = [
        'created_at',
        'updated_at',
        'created_by'
    ]
    
    fieldsets = (
        ('Relationship', {
            'fields': ('consultant', 'manager')
        }),
        ('Timeline', {
            'fields': ('start_date', 'end_date', 'is_active')
        }),
        ('Details', {
            'fields': ('notes',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        """Set created_by on creation"""
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        """Optimize queries"""
        return super().get_queryset(request).select_related(
            'consultant',
            'manager',
            'created_by'
        )
