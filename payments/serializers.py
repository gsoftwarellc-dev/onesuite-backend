from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db.models import Sum

from .models import (
    PaymentMethod,
    PaymentTransaction,
    W9Information,
    TaxDocument,
    PaymentReconciliation,
    PaymentAuditLog
)
from .encryption import EncryptionService

User = get_user_model()


class UserMinimalSerializer(serializers.Serializer):
    """Minimal user info for responses"""
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()


# ============================================================================
# Payment Method Serializers
# ============================================================================

class PaymentMethodListSerializer(serializers.ModelSerializer):
    """
    List view of payment methods.
    Sensitive fields are masked.
    """
    account_number_masked = serializers.SerializerMethodField()
    
    class Meta:
        model = PaymentMethod
        fields = [
            'id', 'method_type', 'status', 'is_default',
            'account_holder_name', 'bank_name', 'account_number_masked',
            'account_type', 'verified_at', 'created_at'
        ]
        read_only_fields = fields
    
    def get_account_number_masked(self, obj):
        """Return masked account number"""
        return EncryptionService.mask_account_number(obj.account_number)


class PaymentMethodCreateSerializer(serializers.Serializer):
    """
    Input serializer for creating payment methods.
    Validates format only, encryption handled by service.
    """
    method_type = serializers.ChoiceField(choices=PaymentMethod.MethodType.choices)
    account_holder_name = serializers.CharField(max_length=255)
    bank_name = serializers.CharField(max_length=255)
    routing_number = serializers.RegexField(r'^\d{9}$', error_messages={'invalid': 'Must be 9 digits'})
    account_number = serializers.CharField(max_length=17)
    account_type = serializers.ChoiceField(choices=PaymentMethod.AccountType.choices)
    swift_code = serializers.CharField(max_length=11, required=False, allow_blank=True)
    iban = serializers.CharField(max_length=34, required=False, allow_blank=True)


class PaymentMethodUpdateSerializer(serializers.Serializer):
    """
    Input serializer for updating payment methods.
    Consultants can only update limited fields.
    """
    account_holder_name = serializers.CharField(max_length=255, required=False)
    bank_name = serializers.CharField(max_length=255, required=False)


# ============================================================================
# Payment Transaction Serializers
# ============================================================================

class PaymentTransactionListSerializer(serializers.ModelSerializer):
    """
    List view of payment transactions.
    """
    batch_reference = serializers.CharField(source='batch.reference_number', read_only=True)
    
    class Meta:
        model = PaymentTransaction
        fields = [
            'id', 'batch_reference', 'status', 'processor_type',
            'total_amount', 'external_reference', 'confirmed_at', 'created_at'
        ]
        read_only_fields = fields


class PaymentTransactionDetailSerializer(serializers.ModelSerializer):
    """
    Detailed view of payment transaction.
    """
    batch = serializers.SerializerMethodField()
    initiated_by_user = UserMinimalSerializer(source='initiated_by', read_only=True)
    confirmed_by_user = UserMinimalSerializer(source='confirmed_by', read_only=True)
    
    class Meta:
        model = PaymentTransaction
        fields = [
            'id', 'batch', 'status', 'processor_type', 'total_amount', 'currency',
            'external_reference', 'confirmation_code',
            'initiated_by_user', 'initiated_at',
            'confirmed_by_user', 'confirmed_at', 'completed_at', 'failed_at',
            'failure_reason', 'retry_count', 'parent_transaction', 'notes'
        ]
        read_only_fields = fields
    
    def get_batch(self, obj):
        return {
            'id': obj.batch.id,
            'reference_number': obj.batch.reference_number,
            'total_amount': str(obj.batch.payouts.aggregate(total=Sum('net_amount'))['total'] or 0)
        }


class PaymentConfirmSerializer(serializers.Serializer):
    """Input for confirming payment"""
    external_reference = serializers.CharField(max_length=255)
    confirmation_code = serializers.CharField(max_length=100, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class PaymentFailSerializer(serializers.Serializer):
    """Input for marking payment failed"""
    failure_reason = serializers.CharField()


class PaymentRetrySerializer(serializers.Serializer):
    """Input for retrying payment"""
    payment_method_id = serializers.IntegerField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class PaymentCancelSerializer(serializers.Serializer):
    """Input for cancelling payment"""
    reason = serializers.CharField(required=False, allow_blank=True)


# ============================================================================
# W-9 Serializers
# ============================================================================

class W9InformationSerializer(serializers.ModelSerializer):
    """
    W-9 information with masked TIN.
    """
    consultant = UserMinimalSerializer(read_only=True)
    tin_masked = serializers.SerializerMethodField()
    
    class Meta:
        model = W9Information
        fields = [
            'id', 'consultant', 'status', 'legal_name', 'business_name',
            'entity_type', 'tax_classification', 'tin_type', 'tin_masked',
            'address_line1', 'address_line2', 'city', 'state', 'zip_code', 'country',
            'exempt_from_backup_withholding', 'submitted_at', 'reviewed_at'
        ]
        read_only_fields = fields
    
    def get_tin_masked(self, obj):
        """Return masked TIN"""
        return EncryptionService.mask_tin(obj.tin)


class W9SubmitSerializer(serializers.Serializer):
    """
    Input serializer for submitting W-9.
    TIN will be encrypted by service.
    """
    legal_name = serializers.CharField(max_length=255)
    business_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    entity_type = serializers.ChoiceField(choices=W9Information.EntityType.choices)
    tax_classification = serializers.ChoiceField(
        choices=W9Information.TaxClassification.choices,
        required=False,
        allow_blank=True
    )
    tin_type = serializers.ChoiceField(choices=W9Information.TINType.choices)
    tin = serializers.RegexField(
        r'^\d{3}-\d{2}-\d{4}$|^\d{2}-\d{7}$',
        error_messages={'invalid': 'Must be SSN (XXX-XX-XXXX) or EIN (XX-XXXXXXX) format'}
    )
    address_line1 = serializers.CharField(max_length=255)
    address_line2 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=2)
    zip_code = serializers.CharField(max_length=10)
    country = serializers.CharField(max_length=2, default='US')
    exempt_from_backup_withholding = serializers.BooleanField(default=False)


class W9ApproveSerializer(serializers.Serializer):
    """Input for approving W-9"""
    notes = serializers.CharField(required=False, allow_blank=True)


class W9RejectSerializer(serializers.Serializer):
    """Input for rejecting W-9"""
    reason = serializers.CharField()


# ============================================================================
# Tax Document Serializers
# ============================================================================

class TaxDocumentListSerializer(serializers.ModelSerializer):
    """
    List view of tax documents.
    """
    consultant_name = serializers.CharField(source='consultant.username', read_only=True)
    download_url = serializers.SerializerMethodField()
    
    class Meta:
        model = TaxDocument
        fields = [
            'id', 'consultant_name', 'tax_year', 'document_type', 'total_amount',
            'generated_at', 'sent_to_consultant', 'filed_with_irs', 'download_url'
        ]
        read_only_fields = fields
    
    def get_download_url(self, obj):
        """Return download URL"""
        return f"/api/payments/tax-documents/{obj.id}/download/"


class TaxDocumentDetailSerializer(serializers.ModelSerializer):
    """
    Detailed view of tax document.
    """
    consultant = UserMinimalSerializer(read_only=True)
    generated_by_user = UserMinimalSerializer(source='generated_by', read_only=True)
    
    class Meta:
        model = TaxDocument
        fields = [
            'id', 'consultant', 'tax_year', 'document_type', 'total_amount',
            'file_path', 'file_hash', 'generated_by_user', 'generated_at',
            'sent_to_consultant', 'sent_at', 'filed_with_irs', 'filed_at',
            'corrects_document', 'notes'
        ]
        read_only_fields = fields


class TaxDocumentGenerateSerializer(serializers.Serializer):
    """Input for generating 1099-NEC"""
    tax_year = serializers.IntegerField()
    consultant_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False
    )


class TaxDocumentMarkFiledSerializer(serializers.Serializer):
    """Input for marking 1099 as filed"""
    filing_confirmation = serializers.CharField(required=False, allow_blank=True)


# ============================================================================
# Reconciliation Serializers
# ============================================================================

class PaymentReconciliationListSerializer(serializers.ModelSerializer):
    """
    List view of reconciliations.
    """
    batch_reference = serializers.CharField(source='batch.reference_number', read_only=True)
    reconciled_by_user = serializers.CharField(source='reconciled_by.username', read_only=True)
    
    class Meta:
        model = PaymentReconciliation
        fields = [
            'id', 'batch_reference', 'status', 'expected_amount', 'actual_amount',
            'discrepancy_amount', 'reconciliation_date', 'reconciled_by_user'
        ]
        read_only_fields = fields


class PaymentReconciliationDetailSerializer(serializers.ModelSerializer):
    """
    Detailed view of reconciliation.
    """
    batch = serializers.SerializerMethodField()
    reconciled_by_user = UserMinimalSerializer(source='reconciled_by', read_only=True)
    
    class Meta:
        model = PaymentReconciliation
        fields = [
            'id', 'batch', 'transaction', 'reconciliation_date', 'reconciled_by_user',
            'status', 'expected_amount', 'actual_amount', 'discrepancy_amount',
            'discrepancy_reason', 'resolution_notes', 'resolved_at', 'notes'
        ]
        read_only_fields = fields
    
    def get_batch(self, obj):
        return {
            'id': obj.batch.id,
            'reference_number': obj.batch.reference_number
        }


class ReconciliationCreateSerializer(serializers.Serializer):
    """Input for creating reconciliation"""
    batch_id = serializers.IntegerField()
    transaction_id = serializers.IntegerField(required=False)
    reconciliation_date = serializers.DateField()
    actual_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True)


class ReconciliationResolveSerializer(serializers.Serializer):
    """Input for resolving discrepancy"""
    resolution_notes = serializers.CharField()


# ============================================================================
# Audit Log Serializer
# ============================================================================

class PaymentAuditLogSerializer(serializers.ModelSerializer):
    """
    Audit log entries (read-only).
    """
    actor_name = serializers.CharField(source='actor.username', read_only=True)
    
    class Meta:
        model = PaymentAuditLog
        fields = [
            'id', 'action_type', 'actor_name', 'target_model', 'target_id',
            'old_values', 'new_values', 'notes', 'timestamp'
        ]
        read_only_fields = fields
