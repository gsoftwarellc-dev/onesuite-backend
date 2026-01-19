"""
Django signals for Phase 4 integration.
Handles automatic PaymentTransaction creation and Payout updates.
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db import transaction

from payouts.models import PayoutBatch, Payout
from .models import PaymentTransaction, PaymentAuditLog
from .services import PaymentTransactionService


@receiver(post_save, sender=PayoutBatch)
def create_payment_transaction_on_batch_release(sender, instance, created, **kwargs):
    """
    Automatically create PaymentTransaction when PayoutBatch is released.
    
    Trigger: PayoutBatch.status changes to RELEASED
    Action: Create PaymentTransaction (status=PENDING)
    Idempotency: Check if transaction already exists
    """
    # Only trigger on status change to RELEASED
    if instance.status != 'RELEASED':
        return
    
    # Check if transaction already exists (idempotency)
    if hasattr(instance, 'payment_transaction'):
        return
    
    # Avoid triggering on bulk updates (no way to detect old state)
    if kwargs.get('update_fields') is not None:
        # If update_fields is set, check if status was updated
        if 'status' not in kwargs.get('update_fields', []):
            return
    
    # Create transaction in atomic block
    with transaction.atomic():
        try:
            # Calculate total from batch payouts
            from django.db.models import Sum
            from decimal import Decimal
            
            total_amount = instance.payouts.aggregate(
                total=Sum('total_commission')
            )['total'] or Decimal('0.00')
            
            # Get actor (who released the batch)
            actor = getattr(instance, '_released_by', None)
            
            # Create payment transaction
            payment_transaction = PaymentTransaction.objects.create(
                batch=instance,
                status=PaymentTransaction.Status.PENDING,
                processor_type=PaymentTransaction.ProcessorType.MANUAL,
                total_amount=total_amount,
                initiated_by=actor
            )
            
            # Audit log
            PaymentAuditLog.objects.create(
                action_type=PaymentAuditLog.ActionType.PAYMENT_INITIATED,
                actor=actor,
                target_model='PaymentTransaction',
                target_id=payment_transaction.id,
                new_values={
                    'batch': instance.reference_number,
                    'total_amount': str(total_amount),
                    'status': payment_transaction.status
                },
                notes='Auto-created on batch release'
            )
            
        except Exception as e:
            # Log error but don't fail the batch save
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create PaymentTransaction for batch {instance.id}: {str(e)}")


@receiver(pre_save, sender=PaymentTransaction)
def detect_payment_transaction_state_change(sender, instance, **kwargs):
    """
    Detect state changes in PaymentTransaction.
    Store old state for post_save signal.
    """
    if instance.pk:
        try:
            old_instance = PaymentTransaction.objects.get(pk=instance.pk)
            instance._old_status = old_instance.status
        except PaymentTransaction.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None


@receiver(post_save, sender=PaymentTransaction)
def update_payouts_on_payment_completion(sender, instance, created, **kwargs):
    """
    Update Payout records when PaymentTransaction is completed.
    
    Trigger: PaymentTransaction.status changes to COMPLETED
    Action: Update all Payouts in batch with paid_at and payment_reference
    Safety: Only trigger on state transition (not on every save)
    """
    # Skip if this is a new record
    if created:
        return
    
    # Check if status changed to COMPLETED
    old_status = getattr(instance, '_old_status', None)
    if old_status == PaymentTransaction.Status.COMPLETED:
        # Already completed, no action needed
        return
    
    if instance.status != PaymentTransaction.Status.COMPLETED:
        # Not completed yet, no action needed
        return
    
    # Status changed to COMPLETED - update payouts
    with transaction.atomic():
        try:
            # Update all payouts in the batch
            updated_count = Payout.objects.filter(
                batch=instance.batch
            ).update(
                paid_at=instance.confirmed_at,
                payment_reference=instance.external_reference
            )
            
            # Audit log
            PaymentAuditLog.objects.create(
                action_type=PaymentAuditLog.ActionType.PAYMENT_CONFIRMED,
                actor=instance.confirmed_by,
                target_model='PaymentTransaction',
                target_id=instance.id,
                new_values={
                    'payouts_updated': updated_count,
                    'paid_at': str(instance.confirmed_at),
                    'payment_reference': instance.external_reference
                },
                notes=f'Updated {updated_count} payout records'
            )
            
        except Exception as e:
            # Log error but don't fail the transaction save
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to update payouts for transaction {instance.id}: {str(e)}")
