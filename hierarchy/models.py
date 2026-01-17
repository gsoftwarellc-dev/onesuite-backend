from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q

User = get_user_model()


class ReportingLine(models.Model):
    """
    Represents a time-bounded manager-consultant relationship.
    
    Business Rules:
    - One consultant can have only ONE active manager at a time
    - A manager can have MULTIPLE consultants
    - Relationships are time-bounded (start_date to end_date)
    - Historical relationships are preserved (soft delete via is_active)
    - A user cannot manage themselves
    """
    
    consultant = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='reporting_to',
        help_text="The user who reports to a manager"
    )
    
    manager = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='managing',
        help_text="The user who manages the consultant"
    )
    
    start_date = models.DateField(
        help_text="When this reporting relationship began"
    )
    
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="When this reporting relationship ended (NULL = currently active)"
    )
    
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Quick filter for current relationships"
    )
    
    notes = models.TextField(
        blank=True,
        help_text="Optional context about this relationship"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_reporting_lines',
        help_text="Admin who created this relationship"
    )
    
    class Meta:
        db_table = 'hierarchy_reporting_line'
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['consultant', 'is_active']),
            models.Index(fields=['manager', 'is_active']),
            models.Index(fields=['start_date', 'end_date']),
        ]
        constraints = [
            # Prevent self-management
            models.CheckConstraint(
                check=~Q(consultant=models.F('manager')),
                name='no_self_management'
            ),
            # Only one active relationship per consultant
            models.UniqueConstraint(
                fields=['consultant'],
                condition=Q(is_active=True),
                name='one_active_manager_per_consultant'
            ),
            # End date must be after start date
            models.CheckConstraint(
                check=Q(end_date__isnull=True) | Q(end_date__gte=models.F('start_date')),
                name='end_date_after_start_date'
            ),
        ]
    
    def __str__(self):
        status = "Active" if self.is_active else "Ended"
        return f"{self.consultant.username} → {self.manager.username} ({status})"
    
    def clean(self):
        """Validate business rules"""
        # Prevent self-management
        if self.consultant_id == self.manager_id:
            raise ValidationError("A user cannot be their own manager.")
        
        # Validate date logic
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError("End date cannot be before start date.")
        
        # Check for active manager conflict
        if self.is_active:
            existing_active = ReportingLine.objects.filter(
                consultant=self.consultant,
                is_active=True
            ).exclude(pk=self.pk)
            
            if existing_active.exists():
                raise ValidationError(
                    f"{self.consultant.username} already has an active manager. "
                    "Use the change-manager endpoint to update."
                )
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    
    def deactivate(self, end_date=None):
        """Soft-delete this relationship"""
        from django.utils import timezone
        self.is_active = False
        self.end_date = end_date or timezone.now().date()
        self.save()
    
    def get_downstream_consultants(self):
        """Get all consultants managed by this manager (recursive)"""
        # This will be used for full team hierarchy queries
        # Returns a list of user IDs in the downstream tree
        downstream = []
        direct_reports = ReportingLine.objects.filter(
            manager=self.consultant,
            is_active=True
        ).select_related('consultant')
        
        for report in direct_reports:
            downstream.append(report.consultant.id)
            # Recursively get their reports
            sub_reports = report.get_downstream_consultants()
            downstream.extend(sub_reports)
        
        return downstream
