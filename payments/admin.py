from django.contrib import admin
from .models import (
    PaymentMethod,
    PaymentTransaction,
    W9Information,
    TaxDocument,
    PaymentReconciliation,
    PaymentAuditLog
)


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ['id', 'consultant', 'method_type', 'status', 'is_default', 'verified_at', 'created_at']
    list_filter = ['status', 'method_type', 'is_default']
    search_fields = ['consultant__username', 'consultant__email', 'account_holder_name', 'bank_name']
    readonly_fields = ['created_at', 'updated_at', 'verified_at', 'verified_by']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('consultant', 'method_type', 'status', 'is_default')
        }),
        ('Bank Details', {
            'fields': ('account_holder_name', 'bank_name', 'routing_number', 'account_number', 'account_type')
        }),
        ('International (Future)', {
            'fields': ('swift_code', 'iban', 'currency'),
            'classes': ('collapse',)
        }),
        ('Verification', {
            'fields': ('verified_by', 'verified_at', 'notes')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'batch', 'status', 'processor_type', 'total_amount', 'confirmed_at', 'created_at']
    list_filter = ['status', 'processor_type']
    search_fields = ['batch__reference_number', 'external_reference']
    readonly_fields = ['created_at', 'updated_at', 'initiated_at', 'confirmed_at', 'completed_at', 'failed_at']
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('batch', 'payment_method', 'status', 'processor_type')
        }),
        ('Financial', {
            'fields': ('total_amount', 'currency')
        }),
        ('External References', {
            'fields': ('external_reference', 'confirmation_code')
        }),
        ('Processing', {
            'fields': ('initiated_by', 'initiated_at', 'confirmed_by', 'confirmed_at', 'completed_at', 'failed_at')
        }),
        ('Retry Logic', {
            'fields': ('retry_count', 'parent_transaction', 'failure_reason'),
            'classes': ('collapse',)
        }),
        ('Additional', {
            'fields': ('notes', 'metadata'),
            'classes': ('collapse',)
        }),
    )


@admin.register(W9Information)
class W9InformationAdmin(admin.ModelAdmin):
    list_display = ['id', 'consultant', 'legal_name', 'status', 'entity_type', 'submitted_at', 'reviewed_at']
    list_filter = ['status', 'entity_type', 'tin_type']
    search_fields = ['consultant__username', 'legal_name', 'business_name']
    readonly_fields = ['submitted_at', 'reviewed_at', 'reviewed_by', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Consultant', {
            'fields': ('consultant', 'status')
        }),
        ('Personal/Business Info', {
            'fields': ('legal_name', 'business_name', 'entity_type', 'tax_classification')
        }),
        ('Tax ID', {
            'fields': ('tin_type', 'tin', 'exempt_from_backup_withholding')
        }),
        ('Address', {
            'fields': ('address_line1', 'address_line2', 'city', 'state', 'zip_code', 'country')
        }),
        ('Review', {
            'fields': ('submitted_at', 'reviewed_by', 'reviewed_at', 'approval_notes')
        }),
    )


@admin.register(TaxDocument)
class TaxDocumentAdmin(admin.ModelAdmin):
    list_display = ['id', 'consultant', 'tax_year', 'document_type', 'total_amount', 'generated_at', 'sent_to_consultant', 'filed_with_irs']
    list_filter = ['document_type', 'tax_year', 'sent_to_consultant', 'filed_with_irs']
    search_fields = ['consultant__username', 'consultant__email']
    readonly_fields = ['generated_at', 'generated_by', 'sent_at', 'filed_at', 'file_hash', 'created_at']
    
    fieldsets = (
        ('Document Info', {
            'fields': ('consultant', 'tax_year', 'document_type', 'total_amount')
        }),
        ('File', {
            'fields': ('file_path', 'file_hash')
        }),
        ('Generation', {
            'fields': ('generated_by', 'generated_at')
        }),
        ('Distribution', {
            'fields': ('sent_to_consultant', 'sent_at', 'filed_with_irs', 'filed_at')
        }),
        ('Corrections', {
            'fields': ('corrects_document', 'notes'),
            'classes': ('collapse',)
        }),
    )


@admin.register(PaymentReconciliation)
class PaymentReconciliationAdmin(admin.ModelAdmin):
    list_display = ['id', 'batch', 'status', 'expected_amount', 'actual_amount', 'discrepancy_amount', 'reconciliation_date', 'reconciled_by']
    list_filter = ['status', 'reconciliation_date']
    search_fields = ['batch__reference_number']
    readonly_fields = ['created_at', 'updated_at', 'resolved_at']
    
    fieldsets = (
        ('Reconciliation', {
            'fields': ('batch', 'transaction', 'reconciliation_date', 'reconciled_by', 'status')
        }),
        ('Amounts', {
            'fields': ('expected_amount', 'actual_amount', 'discrepancy_amount')
        }),
        ('Discrepancy Resolution', {
            'fields': ('discrepancy_reason', 'resolution_notes', 'resolved_at'),
            'classes': ('collapse',)
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )


@admin.register(PaymentAuditLog)
class PaymentAuditLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'action_type', 'actor', 'target_model', 'target_id', 'timestamp']
    list_filter = ['action_type', 'target_model', 'timestamp']
    search_fields = ['actor__username', 'notes']
    readonly_fields = ['timestamp']
    
    fieldsets = (
        ('Action', {
            'fields': ('action_type', 'actor', 'timestamp')
        }),
        ('Target', {
            'fields': ('target_model', 'target_id')
        }),
        ('Changes', {
            'fields': ('old_values', 'new_values')
        }),
        ('Request Metadata', {
            'fields': ('ip_address', 'user_agent', 'notes'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        return False  # Audit logs are created programmatically only
    
    def has_delete_permission(self, request, obj=None):
        return False  # Audit logs are immutable
