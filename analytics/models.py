"""
Phase 6: Analytics & Reporting Models
All models are append-only for immutability and audit compliance.
"""
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class AppendOnlyModel(models.Model):
    """
    Abstract base class that enforces append-only behavior.
    No updates or deletes allowed after creation.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        abstract = True
    
    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("This model is append-only. Updates are not allowed.")
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        raise ValidationError("This model is append-only. Deletes are not allowed.")


class WindowType(models.TextChoices):
    DAILY = 'DAILY', _('Daily')
    MONTHLY = 'MONTHLY', _('Monthly')
    QUARTERLY = 'QUARTERLY', _('Quarterly')
    ANNUAL = 'ANNUAL', _('Annual')


class ScopeType(models.TextChoices):
    GLOBAL = 'GLOBAL', _('Global')
    MANAGER = 'MANAGER', _('Manager')
    CONSULTANT = 'CONSULTANT', _('Consultant')


class CommissionMetric(AppendOnlyModel):
    """
    Aggregated commission metrics per window and scope.
    Supports global, manager-level, and consultant-level views.
    """
    window = models.CharField(max_length=10, choices=WindowType.choices)
    period_start = models.DateField()
    period_end = models.DateField()
    scope = models.CharField(max_length=15, choices=ScopeType.choices)
    scope_id = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='commission_metrics'
    )
    
    # Metrics
    total_count = models.IntegerField(default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    approved_count = models.IntegerField(default=0)
    approved_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pending_count = models.IntegerField(default=0)
    pending_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rejected_count = models.IntegerField(default=0)
    rejected_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    average_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    computed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['window', 'period_start', 'scope', 'scope_id'],
                name='unique_commission_metric'
            ),
            models.CheckConstraint(
                check=(
                    models.Q(scope='GLOBAL', scope_id__isnull=True) |
                    models.Q(scope__in=['MANAGER', 'CONSULTANT'], scope_id__isnull=False)
                ),
                name='commission_metric_scope_check'
            )
        ]
        indexes = [
            models.Index(fields=['window', 'scope', 'scope_id', 'period_start'], name='idx_cm_lookup'),
            models.Index(fields=['period_start', 'period_end'], name='idx_cm_period'),
        ]
    
    def __str__(self):
        return f"CommissionMetric {self.window} {self.period_start} ({self.scope})"


class PayoutSummary(AppendOnlyModel):
    """
    Aggregated payout metrics per window and scope.
    """
    window = models.CharField(max_length=10, choices=WindowType.choices)
    period_start = models.DateField()
    period_end = models.DateField()
    scope = models.CharField(max_length=15, choices=ScopeType.choices)
    scope_id = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='payout_summaries'
    )
    
    # Metrics
    batch_count = models.IntegerField(default=0)
    payout_count = models.IntegerField(default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pending_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    failed_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    avg_cycle_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    success_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    computed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name_plural = "Payout Summaries"
        constraints = [
            models.UniqueConstraint(
                fields=['window', 'period_start', 'scope', 'scope_id'],
                name='unique_payout_summary'
            ),
            models.CheckConstraint(
                check=(
                    models.Q(scope='GLOBAL', scope_id__isnull=True) |
                    models.Q(scope__in=['MANAGER', 'CONSULTANT'], scope_id__isnull=False)
                ),
                name='payout_summary_scope_check'
            )
        ]
        indexes = [
            models.Index(fields=['window', 'scope', 'scope_id', 'period_start'], name='idx_ps_lookup'),
            models.Index(fields=['period_start', 'period_end'], name='idx_ps_period'),
        ]
    
    def __str__(self):
        return f"PayoutSummary {self.window} {self.period_start} ({self.scope})"


class TaxSummary(AppendOnlyModel):
    """
    Tax obligation summaries for 1099 compliance tracking.
    """
    window = models.CharField(max_length=10, choices=WindowType.choices)
    tax_year = models.IntegerField()
    quarter = models.IntegerField(null=True, blank=True)  # 1-4 for quarterly
    period_start = models.DateField()
    period_end = models.DateField()
    scope = models.CharField(max_length=15, choices=ScopeType.choices)
    scope_id = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='tax_summaries'
    )
    
    # Metrics
    total_payments = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    consultant_count = models.IntegerField(default=0)  # For GLOBAL scope
    above_threshold_count = models.IntegerField(default=0)  # Consultants >= $600
    w9_approved_count = models.IntegerField(default=0)
    w9_pending_count = models.IntegerField(default=0)
    forms_generated_count = models.IntegerField(default=0)
    forms_filed_count = models.IntegerField(default=0)
    
    computed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name_plural = "Tax Summaries"
        constraints = [
            models.UniqueConstraint(
                fields=['window', 'tax_year', 'quarter', 'scope', 'scope_id'],
                name='unique_tax_summary'
            ),
            models.CheckConstraint(
                check=(
                    models.Q(scope='GLOBAL', scope_id__isnull=True) |
                    models.Q(scope='CONSULTANT', scope_id__isnull=False)
                ),
                name='tax_summary_scope_check'
            )
        ]
        indexes = [
            models.Index(fields=['window', 'tax_year', 'scope', 'scope_id'], name='idx_ts_lookup'),
            models.Index(fields=['tax_year', 'quarter'], name='idx_ts_year'),
        ]
    
    def __str__(self):
        q = f"Q{self.quarter}" if self.quarter else "Annual"
        return f"TaxSummary {self.tax_year} {q} ({self.scope})"


class ReconciliationSummary(AppendOnlyModel):
    """
    Reconciliation status rollups for financial oversight.
    Always global scope.
    """
    window = models.CharField(max_length=10, choices=WindowType.choices)
    period_start = models.DateField()
    period_end = models.DateField()
    
    # Metrics
    total_batches = models.IntegerField(default=0)
    matched_count = models.IntegerField(default=0)
    pending_count = models.IntegerField(default=0)
    discrepancy_count = models.IntegerField(default=0)
    total_expected = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_actual = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_discrepancy = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    computed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name_plural = "Reconciliation Summaries"
        constraints = [
            models.UniqueConstraint(
                fields=['window', 'period_start'],
                name='unique_reconciliation_summary'
            )
        ]
        indexes = [
            models.Index(fields=['window', 'period_start'], name='idx_rs_period'),
        ]
    
    def __str__(self):
        return f"ReconciliationSummary {self.window} {self.period_start}"


class ReportType(models.TextChoices):
    COMMISSION_DETAIL = 'COMMISSION_DETAIL', _('Commission Detail')
    PAYOUT_HISTORY = 'PAYOUT_HISTORY', _('Payout History')
    TAX_SUMMARY = 'TAX_SUMMARY', _('Tax Summary')
    RECONCILIATION = 'RECONCILIATION', _('Reconciliation')
    TEAM_PERFORMANCE = 'TEAM_PERFORMANCE', _('Team Performance')
    MY_EARNINGS = 'MY_EARNINGS', _('My Earnings')


class ExportFormat(models.TextChoices):
    CSV = 'CSV', _('CSV')
    PDF = 'PDF', _('PDF')


class ExportStatus(models.TextChoices):
    PENDING = 'PENDING', _('Pending')
    COMPLETED = 'COMPLETED', _('Completed')
    FAILED = 'FAILED', _('Failed')


class ExportLog(AppendOnlyModel):
    """
    Audit trail for all report exports.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='export_logs'
    )
    report_type = models.CharField(max_length=20, choices=ReportType.choices)
    export_format = models.CharField(max_length=5, choices=ExportFormat.choices)
    filters = models.JSONField(default=dict, blank=True)
    row_count = models.IntegerField(default=0)
    file_size_bytes = models.IntegerField(default=0)
    status = models.CharField(max_length=15, choices=ExportStatus.choices, default=ExportStatus.PENDING)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user', 'created_at'], name='idx_el_user'),
            models.Index(fields=['report_type', 'created_at'], name='idx_el_type'),
        ]
    
    def __str__(self):
        return f"Export {self.report_type} by {self.user} at {self.started_at}"
    
    def mark_completed(self, row_count, file_size_bytes):
        """Special method to update status - bypasses append-only for this field only."""
        ExportLog.objects.filter(pk=self.pk).update(
            status=ExportStatus.COMPLETED,
            row_count=row_count,
            file_size_bytes=file_size_bytes,
            completed_at=models.functions.Now()
        )
    
    def mark_failed(self, error_message):
        """Special method to update status on failure."""
        ExportLog.objects.filter(pk=self.pk).update(
            status=ExportStatus.FAILED,
            error_message=error_message,
            completed_at=models.functions.Now()
        )
