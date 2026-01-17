from django.contrib import admin
from .models import Commission


@admin.register(Commission)
class CommissionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'commission_type', 'consultant', 'manager',
        'calculated_amount', 'state', 'transaction_date', 'created_at'
    ]
    list_filter = ['commission_type', 'state', 'transaction_date', 'created_at']
    search_fields = [
        'consultant__username', 'manager__username',
        'reference_number', 'notes'
    ]
    readonly_fields = [
        'created_at', 'updated_at', 'created_by',
        'approved_by', 'approved_at', 'paid_at'
    ]
    
    fieldsets = (
        ('Commission Information', {
            'fields': (
                'commission_type', 'consultant', 'manager',
                'reference_number', 'state', 'notes'
            )
        }),
        ('Financial Details', {
            'fields': (
                'transaction_date', 'sale_amount', 'gst_rate',
                'commission_rate', 'calculated_amount'
            )
        }),
        ('Relationships', {
            'fields': ('parent_commission', 'adjustment_for', 'override_level'),
            'classes': ('collapse',)
        }),
        ('Workflow', {
            'fields': ('rejection_reason',)
        }),
        ('Audit Trail', {
            'fields': (
                'created_at', 'updated_at', 'created_by',
                'approved_by', 'approved_at', 'paid_at'
            ),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:  # If creating new
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'consultant', 'manager', 'created_by', 'approved_by'
        )
