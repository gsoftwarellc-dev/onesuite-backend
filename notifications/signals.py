"""
Notification Signals
Django signals for triggering notifications from Phase 4-6 events.
Non-blocking, no modifications to existing models.
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import NotificationChannel, EventType
from .services import NotificationService

logger = logging.getLogger(__name__)


# =============================================================================
# Helper to safely import Phase 4-6 models
# =============================================================================

def get_model_safely(app_label: str, model_name: str):
    """Safely get a model without breaking if it doesn't exist."""
    try:
        from django.apps import apps
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


# =============================================================================
# Payment Transaction Signals (Phase 5)
# =============================================================================

@receiver(post_save, sender='payments.PaymentTransaction')
def on_payment_transaction_saved(sender, instance, created, **kwargs):
    """Handle PaymentTransaction status changes."""
    try:
        # Only process status changes on existing records
        if created:
            return
        
        status = getattr(instance, 'status', None)
        
        if status == 'COMPLETED':
            NotificationService.send(
                event_type=EventType.PAY_001,
                recipient=instance.consultant,
                source_model='PaymentTransaction',
                source_id=instance.id,
                metadata={
                    'amount': str(instance.amount),
                    'summary': f"Payment of ${instance.amount} completed",
                    'action_url': f"/payments/{instance.id}"
                }
            )
        
        elif status == 'FAILED':
            NotificationService.send(
                event_type=EventType.PAY_002,
                recipient=instance.consultant,
                source_model='PaymentTransaction',
                source_id=instance.id,
                metadata={
                    'amount': str(instance.amount),
                    'error': getattr(instance, 'failure_reason', 'Unknown'),
                    'summary': f"Payment of ${instance.amount} failed",
                    'action_url': f"/payments/{instance.id}"
                }
            )
        
        elif status == 'PROCESSING' and getattr(instance, 'retry_count', 0) > 0:
            NotificationService.send(
                event_type=EventType.PAY_003,
                recipient=instance.consultant,
                source_model='PaymentTransaction',
                source_id=instance.id,
                metadata={
                    'amount': str(instance.amount),
                    'retry_count': instance.retry_count,
                    'summary': f"Payment retry in progress",
                    'action_url': f"/payments/{instance.id}"
                }
            )
    
    except Exception as e:
        logger.error(f"Payment notification error: {e}")


# =============================================================================
# W9 Information Signals (Phase 5)
# =============================================================================

@receiver(post_save, sender='payments.W9Information')
def on_w9_saved(sender, instance, created, **kwargs):
    """Handle W9 status changes."""
    try:
        if created:
            return
        
        status = getattr(instance, 'status', None)
        
        if status == 'REJECTED':
            NotificationService.send(
                event_type=EventType.COMP_002,
                recipient=instance.consultant,
                source_model='W9Information',
                source_id=instance.id,
                metadata={
                    'reason': getattr(instance, 'rejection_reason', 'Please review and resubmit'),
                    'summary': "Your W-9 submission was rejected",
                    'action_url': "/compliance/w9"
                }
            )
    
    except Exception as e:
        logger.error(f"W9 notification error: {e}")


# =============================================================================
# Tax Document Signals (Phase 5)
# =============================================================================

@receiver(post_save, sender='payments.TaxDocument')
def on_tax_document_created(sender, instance, created, **kwargs):
    """Handle 1099 document creation."""
    try:
        if not created:
            return
        
        doc_type = getattr(instance, 'document_type', None)
        
        if doc_type in ['1099-NEC', '1099-C']:
            NotificationService.send(
                event_type=EventType.COMP_003,
                recipient=instance.consultant,
                source_model='TaxDocument',
                source_id=instance.id,
                metadata={
                    'tax_year': instance.tax_year,
                    'document_type': doc_type,
                    'summary': f"{doc_type} tax document generated for {instance.tax_year}",
                    'action_url': "/tax/documents"
                },
                channels=[NotificationChannel.IN_APP]  # In-app only for tax docs
            )
    
    except Exception as e:
        logger.error(f"Tax document notification error: {e}")


# =============================================================================
# Payout Batch Signals (Phase 4)
# =============================================================================

@receiver(post_save, sender='payouts.PayoutBatch')
def on_payout_batch_saved(sender, instance, created, **kwargs):
    """Handle PayoutBatch status changes."""
    try:
        if created:
            return
        
        status = getattr(instance, 'status', None)
        
        if status == 'RELEASED':
            # Get all consultants in this batch
            Payout = get_model_safely('payouts', 'Payout')
            if Payout:
                payouts = Payout.objects.filter(batch=instance).select_related('consultant')
                for payout in payouts:
                    NotificationService.send(
                        event_type=EventType.OUT_001,
                        recipient=payout.consultant,
                        source_model='PayoutBatch',
                        source_id=instance.id,
                        metadata={
                            'amount': str(payout.total_commission),
                            'batch_id': instance.id,
                            'summary': f"Payout of ${payout.total_commission} has been released",
                            'action_url': f"/payouts/{payout.id}"
                        }
                    )
    
    except Exception as e:
        logger.error(f"Payout batch notification error: {e}")


# =============================================================================
# Export Log Signals (Phase 6)
# =============================================================================

@receiver(post_save, sender='analytics.ExportLog')
def on_export_completed(sender, instance, created, **kwargs):
    """Handle export completion."""
    try:
        if created:
            return
        
        status = getattr(instance, 'status', None)
        
        if status == 'COMPLETED':
            NotificationService.send(
                event_type=EventType.SYS_002,
                recipient=instance.user,
                source_model='ExportLog',
                source_id=instance.id,
                metadata={
                    'report_type': instance.report_type,
                    'row_count': instance.row_count,
                    'summary': f"Your {instance.report_type} export is ready",
                    'action_url': "/analytics/exports"
                },
                channels=[NotificationChannel.IN_APP]  # In-app only for exports
            )
    
    except Exception as e:
        logger.error(f"Export notification error: {e}")
