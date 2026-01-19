from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from commissions.models import Commission

class PayoutPeriod(models.Model):
    """
    Represents an accounting period (e.g., January 2026).
    """
    class Status(models.TextChoices):
        OPEN = 'OPEN', _('Open')
        CLOSED = 'CLOSED', _('Closed')

    name = models.CharField(max_length=50, help_text="e.g., 'January 2026'")
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    is_tax_year_end = models.BooleanField(default=False, help_text="Marks end of fiscal year")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']
        unique_together = ['start_date', 'end_date']

    def __str__(self):
        return self.name


class PayoutBatch(models.Model):
    """
    Represents a specific payroll run within a period.
    """
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')           # Being built
        LOCKED = 'LOCKED', _('Locked')        # Verified, no changes allowed
        RELEASED = 'RELEASED', _('Released')  # Sent to bank (Immutable)
        VOID = 'VOID', _('Void')              # Cancelled

    period = models.ForeignKey(PayoutPeriod, on_delete=models.PROTECT, related_name='batches')
    reference_number = models.CharField(max_length=50, unique=True, help_text="e.g., PAY-2026-01-A")
    run_date = models.DateField(help_text="Target payment date")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_batches')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Payout Batches"

    def __str__(self):
        return f"{self.reference_number} ({self.status})"


class Payout(models.Model):
    """
    Represents a single consultant's payment for a batch.
    """
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        PROCESSING = 'PROCESSING', _('Processing')
        PAID = 'PAID', _('Paid')     # Successfully processed
        ERROR = 'ERROR', _('Error')  # Bank rejection etc.

    batch = models.ForeignKey(PayoutBatch, on_delete=models.CASCADE, related_name='payouts')
    consultant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='payouts')
    
    # Financials (Snapshots)
    total_commission = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_adjustment = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, help_text="Future use")
    
    # Net Pay = Commission + Adjustment - Tax
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    payment_reference = models.CharField(max_length=100, blank=True, help_text="Bank Transaction ID")
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['batch', 'consultant']
        indexes = [
            models.Index(fields=['consultant', 'paid_at']),
        ]

    def __str__(self):
        return f"{self.consultant.username} - {self.net_amount}"


class PayoutLineItem(models.Model):
    """
    Links a Payout to a specific Commission.
    Ensures 1:1 mapping (Commission can only be in one active Payout line item).
    """
    payout = models.ForeignKey(Payout, on_delete=models.CASCADE, related_name='line_items')
    commission = models.OneToOneField(Commission, on_delete=models.PROTECT, related_name='payout_line_item')
    
    # Snapshot values for audit
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.amount} for {self.commission.reference_number}"


class Payslip(models.Model):
    """
    Metadata for generated PDF payslips.
    """
    payout = models.OneToOneField(Payout, on_delete=models.CASCADE, related_name='payslip')
    file_path = models.CharField(max_length=500)
    generated_at = models.DateTimeField(auto_now_add=True)
    is_published = models.BooleanField(default=False)

    def __str__(self):
        return f"Payslip for {self.payout}"


class PayoutHistory(models.Model):
    """
    Audit log for Payout actions.
    """
    batch = models.ForeignKey(PayoutBatch, on_delete=models.CASCADE, related_name='history')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=50)
    notes = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
