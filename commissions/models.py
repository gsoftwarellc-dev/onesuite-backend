from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q

User = get_user_model()


class Commission(models.Model):
    """
    Unified model for base commissions, manager overrides, and adjustments.
    
    Business Rules:
    - Base commissions have consultant but no manager
    - Override commissions have both consultant and manager
    - Adjustments reference original commission via adjustment_for
    - State transitions are validated (draft → submitted → approved → paid)
    - Once paid, commission is immutable (corrections via adjustments)
    """
    
    COMMISSION_TYPE_CHOICES = [
        ('base', 'Base Commission'),
        ('override', 'Manager Override'),
        ('adjustment', 'Adjustment'),
    ]
    
    STATE_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('rejected', 'Rejected'),
    ]
    
    # Core fields
    commission_type = models.CharField(
        max_length=20,
        choices=COMMISSION_TYPE_CHOICES,
        db_index=True,
        help_text="Type of commission"
    )
    
    consultant = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='commissions_earned',
        help_text="User who earned this commission"
    )
    
    manager = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='override_commissions',
        null=True,
        blank=True,
        help_text="For overrides: manager at time of transaction (denormalized for immutability)"
    )
    
    # Transaction details
    transaction_date = models.DateField(
        help_text="When the sale/transaction occurred"
    )
    
    sale_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Sale value excluding GST"
    )
    
    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="GST percentage at transaction time (e.g., 10.00)"
    )
    
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Commission percentage applied (e.g., 7.00 for 7%)"
    )
    
    calculated_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Final commission amount (immutable once approved)"
    )
    
    # State and workflow
    state = models.CharField(
        max_length=20,
        choices=STATE_CHOICES,
        default='draft',
        db_index=True,
        help_text="Current state in lifecycle"
    )
    
    reference_number = models.CharField(
        max_length=50,
        unique=True,
        help_text="External transaction reference (e.g., invoice number)"
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Additional notes or context"
    )

    client_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name of the client/customer"
    )
    
    # Future: Product support
    # product = models.ForeignKey('products.Product', null=True, blank=True, on_delete=models.SET_NULL)
    
    # Override-specific fields
    override_level = models.IntegerField(
        null=True,
        blank=True,
        help_text="For overrides: 1=direct manager, 2=senior manager, etc."
    )
    
    parent_commission = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='related_commissions',
        help_text="For overrides: links to base commission"
    )
    
    # Adjustment-specific fields
    adjustment_for = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='adjustments',
        help_text="For adjustments: original commission being corrected"
    )
    
    # Future: Payout support (Phase 4)
    # payout_batch = models.ForeignKey('payouts.PayoutBatch', null=True, blank=True, on_delete=models.PROTECT)
    
    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='commissions_created',
        help_text="Who created this commission"
    )
    
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='commissions_approved',
        help_text="Admin who approved this commission"
    )
    
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When approved"
    )
    
    paid_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When payment was processed"
    )
    
    rejection_reason = models.TextField(
        blank=True,
        help_text="Reason for rejection (if state=rejected)"
    )
    
    class Meta:
        db_table = 'commissions_commission'
        ordering = ['-transaction_date', '-created_at']
        indexes = [
            models.Index(fields=['consultant', 'state']),
            models.Index(fields=['manager', 'state', 'commission_type']),
            models.Index(fields=['transaction_date', 'state']),
            models.Index(fields=['state', 'created_at']),
        ]
        constraints = [
            # Base commissions should not have manager
            models.CheckConstraint(
                check=(
                    Q(commission_type='base', manager__isnull=True) |
                    ~Q(commission_type='base')
                ),
                name='base_no_manager'
            ),
            # Override must have manager
            models.CheckConstraint(
                check=(
                    Q(commission_type='override', manager__isnull=False) |
                    ~Q(commission_type='override')
                ),
                name='override_has_manager'
            ),
            # Adjustment must reference original
            models.CheckConstraint(
                check=(
                    Q(commission_type='adjustment', adjustment_for__isnull=False) |
                    ~Q(commission_type='adjustment')
                ),
                name='adjustment_has_reference'
            ),
            # Cannot approve own commission
            models.CheckConstraint(
                check=~Q(consultant=models.F('approved_by')),
                name='cannot_approve_own'
            ),
        ]
    
    def __str__(self):
        type_label = dict(self.COMMISSION_TYPE_CHOICES).get(self.commission_type, self.commission_type)
        return f"{type_label} - {self.consultant.username} - ${self.calculated_amount} ({self.state})"
    
    def clean(self):
        """Validate business rules"""
        # Base commission validation
        if self.commission_type == 'base' and self.manager is not None:
            raise ValidationError("Base commissions should not have a manager assigned.")
        
        # Override validation
        if self.commission_type == 'override' and self.manager is None:
            raise ValidationError("Override commissions must have a manager assigned.")
        
        # Adjustment validation
        if self.commission_type == 'adjustment' and self.adjustment_for is None:
            raise ValidationError("Adjustment commissions must reference the original commission.")
        
        # State validation for paid commissions
        if self.pk and self.state == 'paid':
            # Check if state changed from paid (not allowed)
            old_instance = Commission.objects.get(pk=self.pk)
            if old_instance.state == 'paid' and self.state != 'paid':
                raise ValidationError("Cannot modify a commission that has been paid.")
        
        # Cannot approve own commission
        if self.approved_by and self.consultant == self.approved_by:
            raise ValidationError("A user cannot approve their own commission.")
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class CommissionApproval(models.Model):
    """
    Manages the current state of the approval workflow for a commission.
    
    Preserves the assigned approver to handle hierarchy changes gracefully.
    """
    ROLE_CHOICES = [
        ('MANAGER', 'Manager'),
        ('ADMIN', 'Admin/Director'),
    ]
    
    commission = models.OneToOneField(
        Commission,
        on_delete=models.CASCADE,
        related_name='approval',
        help_text="The commission this approval workflow belongs to"
    )
    
    assigned_approver = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='assigned_approvals',
        null=True,  # Initially null for drafts, set on submission
        blank=True,
        help_text="The user specialized for this approval step (manager/admin)"
    )
    
    assigned_role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='MANAGER',
        help_text="Required role level for this approval"
    )
    
    is_auto_approved = models.BooleanField(
        default=False,
        help_text="Whether this was approved by a system rule"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'commissions_approval'
        verbose_name = 'Commission Approval'
        verbose_name_plural = 'Commission Approvals'
    
    def __str__(self):
        return f"Approval for {self.commission.reference_number} ({self.commission.state})"


class ApprovalHistory(models.Model):
    """
    Immutable audit log for all approval actions taken on a commission.
    """
    ACTION_CHOICES = [
        ('SUBMIT', 'Submitted'),
        ('APPROVE', 'Approved'),
        ('REJECT', 'Rejected'),
        ('PAID', 'Marked as Paid'),
    ]
    
    approval_record = models.ForeignKey(
        CommissionApproval,
        on_delete=models.CASCADE,
        related_name='history',
        help_text="The parent approval workflow record"
    )
    
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        help_text="The action taken (Submit, Approve, Reject, Paid)"
    )
    
    actor = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='approval_actions',
        help_text="The user who performed the action"
    )
    
    from_state = models.CharField(
        max_length=20,
        help_text="State before action"
    )
    
    to_state = models.CharField(
        max_length=20,
        help_text="State after action"
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Notes or rejection reasons"
    )
    
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'commissions_approval_history'
        verbose_name = 'Approval History'
        verbose_name_plural = 'Approval Histories'
        ordering = ['timestamp']
    
    def __str__(self):
        return f"{self.action} by {self.actor.username} at {self.timestamp}"
