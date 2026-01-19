from django.db import models
from django.conf import settings
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

class PaymentMethod(models.Model):
    """
    Consultant payment preferences (bank accounts, etc.)
    Sensitive fields are encrypted at rest.
    """
    class MethodType(models.TextChoices):
        ACH = 'ACH', _('ACH/Direct Deposit')
        WIRE = 'WIRE', _('Wire Transfer')
        CHECK = 'CHECK', _('Paper Check')
        INTERNATIONAL = 'INTERNATIONAL', _('International Transfer')
    
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending Verification')
        VERIFIED = 'VERIFIED', _('Verified')
        INACTIVE = 'INACTIVE', _('Inactive')
    
    class AccountType(models.TextChoices):
        CHECKING = 'CHECKING', _('Checking Account')
        SAVINGS = 'SAVINGS', _('Savings Account')
    
    consultant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='payment_methods'
    )
    method_type = models.CharField(max_length=20, choices=MethodType.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    is_default = models.BooleanField(default=False)
    
    # Bank account details
    account_holder_name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255)
    routing_number = models.CharField(
        max_length=9,
        validators=[RegexValidator(r'^\d{9}$', 'Must be 9 digits')]
    )
    account_number = models.CharField(max_length=17)
    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    
    # International fields (future)
    swift_code = models.CharField(max_length=11, blank=True, null=True)
    iban = models.CharField(max_length=34, blank=True, null=True)
    currency = models.CharField(max_length=3, default='USD')
    
    # Verification
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_payment_methods'
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'payments_paymentmethod'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['consultant', 'status']),
            models.Index(fields=['consultant', 'is_default']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['consultant', 'account_number'],
                name='unique_consultant_account'
            ),
        ]
    
    def __str__(self):
        return f"{self.consultant.username} - {self.method_type} ({self.status})"
    
    @property
    def account_number_masked(self):
        """Return masked account number (last 4 digits)"""
        if self.account_number:
            return f"****{self.account_number[-4:]}"
        return "****"


class PaymentTransaction(models.Model):
    """
    Tracks payment execution for payout batches.
    OneToOne with PayoutBatch (Phase 4).
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        PROCESSING = 'PROCESSING', _('Processing')
        COMPLETED = 'COMPLETED', _('Completed')
        FAILED = 'FAILED', _('Failed')
        CANCELLED = 'CANCELLED', _('Cancelled')
    
    class ProcessorType(models.TextChoices):
        MANUAL = 'MANUAL', _('Manual Confirmation')
        ACH = 'ACH', _('ACH Processor')
        WIRE = 'WIRE', _('Wire Transfer')
        STRIPE = 'STRIPE', _('Stripe')
        WISE = 'WISE', _('Wise')
    
    batch = models.OneToOneField(
        'payouts.PayoutBatch',
        on_delete=models.PROTECT,
        related_name='payment_transaction'
    )
    payment_method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    processor_type = models.CharField(
        max_length=50,
        choices=ProcessorType.choices,
        default=ProcessorType.MANUAL
    )
    
    # Financial details
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    
    # External references
    external_reference = models.CharField(max_length=255, unique=True, null=True, blank=True)
    confirmation_code = models.CharField(max_length=100, blank=True)
    
    # Actors and timestamps
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='initiated_transactions'
    )
    initiated_at = models.DateTimeField(auto_now_add=True)
    
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_transactions'
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    
    failure_reason = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    parent_transaction = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='retries'
    )
    
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'payments_paymenttransaction'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['external_reference']),
            models.Index(fields=['confirmed_at']),
        ]
    
    def __str__(self):
        return f"Transaction {self.id} - {self.batch.reference_number} ({self.status})"


class W9Information(models.Model):
    """
    Consultant tax information (W-9 form data).
    OneToOne with User. TIN is encrypted.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending Review')
        APPROVED = 'APPROVED', _('Approved')
        REJECTED = 'REJECTED', _('Rejected')
    
    class EntityType(models.TextChoices):
        INDIVIDUAL = 'INDIVIDUAL', _('Individual/Sole Proprietor')
        LLC = 'LLC', _('Limited Liability Company')
        C_CORP = 'C_CORP', _('C Corporation')
        S_CORP = 'S_CORP', _('S Corporation')
        PARTNERSHIP = 'PARTNERSHIP', _('Partnership')
        TRUST = 'TRUST', _('Trust/Estate')
    
    class TaxClassification(models.TextChoices):
        C = 'C', _('C Corporation')
        S = 'S', _('S Corporation')
        P = 'P', _('Partnership')
    
    class TINType(models.TextChoices):
        SSN = 'SSN', _('Social Security Number')
        EIN = 'EIN', _('Employer Identification Number')
    
    consultant = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='w9_information'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    
    # Personal/Business info
    legal_name = models.CharField(max_length=255)
    business_name = models.CharField(max_length=255, blank=True)
    entity_type = models.CharField(max_length=50, choices=EntityType.choices)
    tax_classification = models.CharField(
        max_length=50,
        choices=TaxClassification.choices,
        blank=True
    )
    
    # Tax ID (encrypted)
    tin_type = models.CharField(max_length=10, choices=TINType.choices)
    tin = models.CharField(max_length=11, unique=True)  # XXX-XX-XXXX or XX-XXXXXXX (encrypted at app layer)
    
    # Address
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)  # US state code
    zip_code = models.CharField(max_length=10)
    country = models.CharField(max_length=2, default='US')
    
    exempt_from_backup_withholding = models.BooleanField(default=False)
    
    # Review
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_w9s'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approval_notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'payments_w9information'
        verbose_name = 'W-9 Information'
        verbose_name_plural = 'W-9 Information'
        indexes = [
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"W-9: {self.legal_name} ({self.status})"
    
    @property
    def tin_masked(self):
        """Return masked TIN (last 4 digits)"""
        if self.tin:
            return f"***-**-{self.tin[-4:]}"
        return "***-**-****"


class TaxDocument(models.Model):
    """
    Generated 1099-NEC forms and other tax documents.
    Immutable once generated.
    """
    class DocumentType(models.TextChoices):
        FORM_1099_NEC = '1099-NEC', _('1099-NEC (Nonemployee Compensation)')
        FORM_1099_C = '1099-C', _('1099-C (Corrected)')
    
    consultant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='tax_documents'
    )
    tax_year = models.IntegerField()
    document_type = models.CharField(max_length=20, choices=DocumentType.choices)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    # File storage
    file_path = models.CharField(max_length=500)
    file_hash = models.CharField(max_length=64)  # SHA-256
    
    # Generation
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='generated_tax_documents'
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    
    # Distribution
    sent_to_consultant = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    filed_with_irs = models.BooleanField(default=False)
    filed_at = models.DateTimeField(null=True, blank=True)
    
    # Corrections
    corrects_document = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='corrections'
    )
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'payments_taxdocument'
        ordering = ['-tax_year', '-generated_at']
        indexes = [
            models.Index(fields=['consultant', 'tax_year']),
            models.Index(fields=['tax_year', 'generated_at']),
            models.Index(fields=['filed_with_irs', 'tax_year']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['consultant', 'tax_year', 'document_type'],
                name='unique_consultant_tax_year_type'
            ),
        ]
    
    def __str__(self):
        return f"{self.document_type} - {self.consultant.username} - {self.tax_year}"


class PaymentReconciliation(models.Model):
    """
    Manual reconciliation tracking for payment batches.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending Reconciliation')
        RECONCILED = 'RECONCILED', _('Reconciled (No Issues)')
        DISCREPANCY = 'DISCREPANCY', _('Discrepancy Found')
    
    batch = models.ForeignKey(
        'payouts.PayoutBatch',
        on_delete=models.PROTECT,
        related_name='reconciliations'
    )
    transaction = models.ForeignKey(
        PaymentTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reconciliations'
    )
    
    reconciliation_date = models.DateField()
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='reconciliations'
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    
    # Amounts
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2)
    actual_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    discrepancy_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    # Discrepancy handling
    discrepancy_reason = models.TextField(blank=True)
    resolution_notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'payments_paymentreconciliation'
        ordering = ['-reconciliation_date']
        indexes = [
            models.Index(fields=['batch']),
            models.Index(fields=['status', 'reconciliation_date']),
            models.Index(fields=['reconciled_by', 'reconciliation_date']),
        ]
    
    def __str__(self):
        return f"Reconciliation: {self.batch.reference_number} ({self.status})"


class PaymentAuditLog(models.Model):
    """
    Immutable audit trail for all payment-related actions.
    """
    class ActionType(models.TextChoices):
        PAYMENT_METHOD_CREATED = 'PAYMENT_METHOD_CREATED', _('Payment Method Created')
        PAYMENT_METHOD_VERIFIED = 'PAYMENT_METHOD_VERIFIED', _('Payment Method Verified')
        PAYMENT_METHOD_INACTIVATED = 'PAYMENT_METHOD_INACTIVATED', _('Payment Method Inactivated')
        PAYMENT_INITIATED = 'PAYMENT_INITIATED', _('Payment Initiated')
        PAYMENT_CONFIRMED = 'PAYMENT_CONFIRMED', _('Payment Confirmed')
        PAYMENT_FAILED = 'PAYMENT_FAILED', _('Payment Failed')
        PAYMENT_CANCELLED = 'PAYMENT_CANCELLED', _('Payment Cancelled')
        W9_SUBMITTED = 'W9_SUBMITTED', _('W-9 Submitted')
        W9_APPROVED = 'W9_APPROVED', _('W-9 Approved')
        W9_REJECTED = 'W9_REJECTED', _('W-9 Rejected')
        TAX_DOCUMENT_GENERATED = 'TAX_DOCUMENT_GENERATED', _('1099 Generated')
        TAX_DOCUMENT_SENT = 'TAX_DOCUMENT_SENT', _('1099 Sent to Consultant')
        TAX_DOCUMENT_FILED = 'TAX_DOCUMENT_FILED', _('1099 Filed with IRS')
        RECONCILIATION_COMPLETED = 'RECONCILIATION_COMPLETED', _('Reconciliation Completed')
    
    action_type = models.CharField(max_length=50, choices=ActionType.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='payment_audit_logs'
    )
    
    # Target reference
    target_model = models.CharField(max_length=50)
    target_id = models.IntegerField()
    
    # Change tracking
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    
    # Request metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    
    notes = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'payments_paymentauditlog'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['target_model', 'target_id', 'timestamp']),
            models.Index(fields=['actor', 'timestamp']),
            models.Index(fields=['action_type', 'timestamp']),
        ]
    
    def __str__(self):
        return f"{self.action_type} by {self.actor} at {self.timestamp}"
