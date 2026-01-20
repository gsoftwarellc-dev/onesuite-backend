from django.contrib import admin
from .models import (
    CommissionMetric,
    PayoutSummary,
    TaxSummary,
    ReconciliationSummary,
    ExportLog
)


class ReadOnlyAdminMixin:
    """Mixin to make admin read-only (no add/change/delete)."""
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CommissionMetric)
class CommissionMetricAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ['window', 'period_start', 'period_end', 'scope', 'scope_id', 
                   'total_count', 'total_amount', 'computed_at']
    list_filter = ['window', 'scope']
    search_fields = ['scope_id__username']
    ordering = ['-period_start']
    date_hierarchy = 'period_start'


@admin.register(PayoutSummary)
class PayoutSummaryAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ['window', 'period_start', 'period_end', 'scope', 'scope_id',
                   'payout_count', 'total_amount', 'success_rate', 'computed_at']
    list_filter = ['window', 'scope']
    search_fields = ['scope_id__username']
    ordering = ['-period_start']
    date_hierarchy = 'period_start'


@admin.register(TaxSummary)
class TaxSummaryAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ['window', 'tax_year', 'quarter', 'scope', 'scope_id',
                   'total_payments', 'above_threshold_count', 'forms_generated_count']
    list_filter = ['window', 'tax_year', 'scope']
    search_fields = ['scope_id__username']
    ordering = ['-tax_year', '-quarter']


@admin.register(ReconciliationSummary)
class ReconciliationSummaryAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ['window', 'period_start', 'period_end', 'total_batches',
                   'matched_count', 'pending_count', 'discrepancy_count', 'total_discrepancy']
    list_filter = ['window']
    ordering = ['-period_start']
    date_hierarchy = 'period_start'


@admin.register(ExportLog)
class ExportLogAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ['user', 'report_type', 'export_format', 'status',
                   'row_count', 'started_at', 'completed_at']
    list_filter = ['report_type', 'export_format', 'status']
    search_fields = ['user__username']
    ordering = ['-started_at']
    date_hierarchy = 'started_at'
