from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal

from .models import (
    PaymentMethod,
    PaymentTransaction,
    W9Information,
    TaxDocument,
    PaymentReconciliation,
    PaymentAuditLog
)
from .encryption import EncryptionService
from payouts.models import PayoutBatch, Payout


class PaymentError(Exception):
    """Base exception for payment logic errors."""
    pass


class PaymentPermissionError(PaymentError):
    """Raised when user lacks permission for an action."""
    pass


class PaymentStateError(PaymentError):
    """Raised when attempting invalid state transition."""
    pass


class PaymentValidationError(PaymentError):
    """Raised when business rules are violated."""
    pass


class PaymentMethodService:
    """
    Service for managing payment methods.
    Handles encryption of sensitive fields.
    """
    
    @staticmethod
    @transaction.atomic
    def create_payment_method(consultant, method_data, actor=None):
        """
        Create a new payment method with encrypted sensitive fields.
        
        Args:
            consultant: User object
            method_data: dict with payment method fields
            actor: User who created (for audit)
        
        Returns:
            PaymentMethod instance
        """
        # Encrypt sensitive fields
        encrypted_data = method_data.copy()
        if 'routing_number' in encrypted_data:
            encrypted_data['routing_number'] = EncryptionService.encrypt(encrypted_data['routing_number'])
        if 'account_number' in encrypted_data:
            encrypted_data['account_number'] = EncryptionService.encrypt(encrypted_data['account_number'])
        if 'swift_code' in encrypted_data and encrypted_data['swift_code']:
            encrypted_data['swift_code'] = EncryptionService.encrypt(encrypted_data['swift_code'])
        if 'iban' in encrypted_data and encrypted_data['iban']:
            encrypted_data['iban'] = EncryptionService.encrypt(encrypted_data['iban'])
        
        # Create payment method
        payment_method = PaymentMethod.objects.create(
            consultant=consultant,
            **encrypted_data
        )
        
        # Audit log
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.PAYMENT_METHOD_CREATED,
            actor=actor or consultant,
            target_model='PaymentMethod',
            target_id=payment_method.id,
            new_values={'method_type': payment_method.method_type, 'status': payment_method.status}
        )
        
        return payment_method
    
    @staticmethod
    @transaction.atomic
    def verify_payment_method(payment_method, verified_by, notes=''):
        """
        Verify a payment method (Finance/Admin only).
        
        Args:
            payment_method: PaymentMethod instance
            verified_by: User performing verification
            notes: Optional verification notes
        
        Returns:
            Updated PaymentMethod
        """
        if payment_method.status != PaymentMethod.Status.PENDING:
            raise PaymentStateError(f"Cannot verify method in {payment_method.status} state")
        
        old_status = payment_method.status
        payment_method.status = PaymentMethod.Status.VERIFIED
        payment_method.verified_by = verified_by
        payment_method.verified_at = timezone.now()
        if notes:
            payment_method.notes = notes
        payment_method.save()
        
        # Audit log
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.PAYMENT_METHOD_VERIFIED,
            actor=verified_by,
            target_model='PaymentMethod',
            target_id=payment_method.id,
            old_values={'status': old_status},
            new_values={'status': payment_method.status, 'verified_at': str(payment_method.verified_at)}
        )
        
        return payment_method
    
    @staticmethod
    @transaction.atomic
    def inactivate_payment_method(payment_method, actor, reason=''):
        """
        Inactivate a payment method.
        
        Args:
            payment_method: PaymentMethod instance
            actor: User performing action
            reason: Reason for inactivation
        """
        # Check if used in pending transactions
        pending_transactions = PaymentTransaction.objects.filter(
            payment_method=payment_method,
            status__in=[PaymentTransaction.Status.PENDING, PaymentTransaction.Status.PROCESSING]
        )
        if pending_transactions.exists():
            raise PaymentStateError("Cannot inactivate method used in pending transactions")
        
        old_status = payment_method.status
        payment_method.status = PaymentMethod.Status.INACTIVE
        if reason:
            payment_method.notes = f"{payment_method.notes}\nInactivated: {reason}" if payment_method.notes else f"Inactivated: {reason}"
        payment_method.save()
        
        # If this was default, unset it
        if payment_method.is_default:
            payment_method.is_default = False
            payment_method.save()
        
        # Audit log
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.PAYMENT_METHOD_INACTIVATED,
            actor=actor,
            target_model='PaymentMethod',
            target_id=payment_method.id,
            old_values={'status': old_status},
            new_values={'status': payment_method.status},
            notes=reason
        )
        
        return payment_method
    
    @staticmethod
    @transaction.atomic
    def set_default_payment_method(payment_method, actor):
        """
        Set a payment method as default for consultant.
        
        Args:
            payment_method: PaymentMethod instance
            actor: User performing action
        """
        if payment_method.status != PaymentMethod.Status.VERIFIED:
            raise PaymentValidationError("Only verified payment methods can be set as default")
        
        # Unset current default
        PaymentMethod.objects.filter(
            consultant=payment_method.consultant,
            is_default=True
        ).update(is_default=False)
        
        # Set new default
        payment_method.is_default = True
        payment_method.save()
        
        return payment_method


class PaymentTransactionService:
    """
    Service for managing payment transactions.
    """
    
    @staticmethod
    @transaction.atomic
    def create_transaction_for_batch(batch, initiated_by):
        """
        Create a payment transaction for a released payout batch.
        Called automatically when batch is released.
        
        Args:
            batch: PayoutBatch instance
            initiated_by: User who released the batch
        
        Returns:
            PaymentTransaction instance
        """
        if batch.status != 'RELEASED':
            raise PaymentStateError("Can only create transaction for RELEASED batches")
        
        # Check if transaction already exists
        if hasattr(batch, 'payment_transaction'):
            return batch.payment_transaction
        
        # Calculate total from batch
        total_amount = batch.payouts.aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')
        
        transaction = PaymentTransaction.objects.create(
            batch=batch,
            status=PaymentTransaction.Status.PENDING,
            processor_type=PaymentTransaction.ProcessorType.MANUAL,
            total_amount=total_amount,
            initiated_by=initiated_by
        )
        
        # Audit log
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.PAYMENT_INITIATED,
            actor=initiated_by,
            target_model='PaymentTransaction',
            target_id=transaction.id,
            new_values={'batch': batch.reference_number, 'total_amount': str(total_amount)}
        )
        
        return transaction
    
    @staticmethod
    @transaction.atomic
    def confirm_payment(transaction, confirmed_by, external_reference, confirmation_code='', notes=''):
        """
        Confirm a payment transaction (manual mode).
        
        Args:
            transaction: PaymentTransaction instance
            confirmed_by: User confirming payment
            external_reference: Bank transaction ID
            confirmation_code: Optional confirmation code
            notes: Optional notes
        
        Returns:
            Updated PaymentTransaction
        """
        if transaction.status not in [PaymentTransaction.Status.PENDING, PaymentTransaction.Status.PROCESSING]:
            raise PaymentStateError(f"Cannot confirm transaction in {transaction.status} state")
        
        if not external_reference:
            raise PaymentValidationError("External reference is required for confirmation")
        
        old_status = transaction.status
        transaction.status = PaymentTransaction.Status.COMPLETED
        transaction.confirmed_by = confirmed_by
        transaction.confirmed_at = timezone.now()
        transaction.completed_at = timezone.now()
        transaction.external_reference = external_reference
        transaction.confirmation_code = confirmation_code
        if notes:
            transaction.notes = notes
        transaction.save()
        
        # Update payouts in batch
        Payout.objects.filter(batch=transaction.batch).update(
            paid_at=transaction.confirmed_at,
            payment_reference=external_reference
        )
        
        # Audit log
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.PAYMENT_CONFIRMED,
            actor=confirmed_by,
            target_model='PaymentTransaction',
            target_id=transaction.id,
            old_values={'status': old_status},
            new_values={'status': transaction.status, 'external_reference': external_reference}
        )
        
        return transaction
    
    @staticmethod
    @transaction.atomic
    def mark_payment_failed(transaction, actor, failure_reason):
        """
        Mark a payment transaction as failed.
        
        Args:
            transaction: PaymentTransaction instance
            actor: User marking as failed
            failure_reason: Reason for failure
        
        Returns:
            Updated PaymentTransaction
        """
        if transaction.status not in [PaymentTransaction.Status.PENDING, PaymentTransaction.Status.PROCESSING]:
            raise PaymentStateError(f"Cannot fail transaction in {transaction.status} state")
        
        if not failure_reason:
            raise PaymentValidationError("Failure reason is required")
        
        old_status = transaction.status
        transaction.status = PaymentTransaction.Status.FAILED
        transaction.failed_at = timezone.now()
        transaction.failure_reason = failure_reason
        transaction.save()
        
        # Audit log
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.PAYMENT_FAILED,
            actor=actor,
            target_model='PaymentTransaction',
            target_id=transaction.id,
            old_values={'status': old_status},
            new_values={'status': transaction.status, 'failure_reason': failure_reason}
        )
        
        return transaction
    
    @staticmethod
    @transaction.atomic
    def retry_payment(transaction, actor, payment_method=None, notes=''):
        """
        Retry a failed payment transaction.
        
        Args:
            transaction: Original PaymentTransaction instance
            actor: User initiating retry
            payment_method: Optional new payment method
            notes: Optional notes
        
        Returns:
            New PaymentTransaction instance
        """
        if transaction.status != PaymentTransaction.Status.FAILED:
            raise PaymentStateError("Can only retry FAILED transactions")
        
        if transaction.retry_count >= 3:
            raise PaymentValidationError("Maximum retry limit (3) reached")
        
        if payment_method and payment_method.status != PaymentMethod.Status.VERIFIED:
            raise PaymentValidationError("Payment method must be verified")
        
        # Create new transaction
        new_transaction = PaymentTransaction.objects.create(
            batch=transaction.batch,
            payment_method=payment_method or transaction.payment_method,
            status=PaymentTransaction.Status.PENDING,
            processor_type=transaction.processor_type,
            total_amount=transaction.total_amount,
            currency=transaction.currency,
            initiated_by=actor,
            retry_count=transaction.retry_count + 1,
            parent_transaction=transaction,
            notes=notes
        )
        
        return new_transaction
    
    @staticmethod
    @transaction.atomic
    def cancel_payment(transaction, actor, reason=''):
        """
        Cancel a payment transaction.
        
        Args:
            transaction: PaymentTransaction instance
            actor: User cancelling
            reason: Cancellation reason
        
        Returns:
            Updated PaymentTransaction
        """
        if transaction.status not in [PaymentTransaction.Status.PENDING, PaymentTransaction.Status.PROCESSING]:
            raise PaymentStateError("Can only cancel PENDING or PROCESSING transactions")
        
        old_status = transaction.status
        transaction.status = PaymentTransaction.Status.CANCELLED
        if reason:
            transaction.notes = f"{transaction.notes}\nCancelled: {reason}" if transaction.notes else f"Cancelled: {reason}"
        transaction.save()
        
        # Audit log
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.PAYMENT_CANCELLED,
            actor=actor,
            target_model='PaymentTransaction',
            target_id=transaction.id,
            old_values={'status': old_status},
            new_values={'status': transaction.status},
            notes=reason
        )
        
        return transaction


class W9Service:
    """
    Service for managing W-9 information.
    Handles encryption of TIN.
    """
    
    @staticmethod
    @transaction.atomic
    def submit_w9(consultant, w9_data, actor=None):
        """
        Submit W-9 information with encrypted TIN.
        
        Args:
            consultant: User object
            w9_data: dict with W-9 fields
            actor: User submitting (for audit)
        
        Returns:
            W9Information instance
        """
        # Encrypt TIN
        encrypted_data = w9_data.copy()
        if 'tin' in encrypted_data:
            encrypted_data['tin'] = EncryptionService.encrypt(encrypted_data['tin'])
        
        # Create or update W-9
        w9, created = W9Information.objects.update_or_create(
            consultant=consultant,
            defaults=encrypted_data
        )
        
        # Audit log
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.W9_SUBMITTED,
            actor=actor or consultant,
            target_model='W9Information',
            target_id=w9.id,
            new_values={'status': w9.status, 'entity_type': w9.entity_type}
        )
        
        return w9
    
    @staticmethod
    @transaction.atomic
    def approve_w9(w9, approved_by, notes=''):
        """
        Approve a W-9 (Finance/Admin only).
        
        Args:
            w9: W9Information instance
            approved_by: User approving
            notes: Optional approval notes
        
        Returns:
            Updated W9Information
        """
        if w9.status != W9Information.Status.PENDING:
            raise PaymentStateError(f"Cannot approve W-9 in {w9.status} state")
        
        old_status = w9.status
        w9.status = W9Information.Status.APPROVED
        w9.reviewed_by = approved_by
        w9.reviewed_at = timezone.now()
        if notes:
            w9.approval_notes = notes
        w9.save()
        
        # Audit log
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.W9_APPROVED,
            actor=approved_by,
            target_model='W9Information',
            target_id=w9.id,
            old_values={'status': old_status},
            new_values={'status': w9.status}
        )
        
        return w9
    
    @staticmethod
    @transaction.atomic
    def reject_w9(w9, rejected_by, reason):
        """
        Reject a W-9 (Finance/Admin only).
        
        Args:
            w9: W9Information instance
            rejected_by: User rejecting
            reason: Rejection reason
        
        Returns:
            Updated W9Information
        """
        if w9.status != W9Information.Status.PENDING:
            raise PaymentStateError(f"Cannot reject W-9 in {w9.status} state")
        
        if not reason:
            raise PaymentValidationError("Rejection reason is required")
        
        old_status = w9.status
        w9.status = W9Information.Status.REJECTED
        w9.reviewed_by = rejected_by
        w9.reviewed_at = timezone.now()
        w9.approval_notes = reason
        w9.save()
        
        # Audit log
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.W9_REJECTED,
            actor=rejected_by,
            target_model='W9Information',
            target_id=w9.id,
            old_values={'status': old_status},
            new_values={'status': w9.status},
            notes=reason
        )
        
        return w9


class TaxDocumentService:
    """
    Service for generating and managing tax documents (1099-NEC).
    """
    
    @staticmethod
    @transaction.atomic
    def generate_1099_nec(consultant, tax_year, generated_by):
        """
        Generate 1099-NEC for a consultant for a tax year.
        
        Args:
            consultant: User object
            tax_year: Integer year
            generated_by: User generating document
        
        Returns:
            TaxDocument instance
        """
        # Validate W-9
        try:
            w9 = consultant.w9_information
            if w9.status != W9Information.Status.APPROVED:
                raise PaymentValidationError(f"Consultant W-9 is not approved (status: {w9.status})")
        except W9Information.DoesNotExist:
            raise PaymentValidationError("Consultant has no W-9 on file")
        
        # Check if exempt (C-Corp, S-Corp)
        if w9.entity_type in [W9Information.EntityType.C_CORP, W9Information.EntityType.S_CORP]:
            raise PaymentValidationError(f"Entity type {w9.entity_type} is exempt from 1099 reporting")
        
        # Calculate total payments for year
        from django.db.models import Sum
        total_payments = PaymentTransaction.objects.filter(
            batch__payouts__consultant=consultant,
            status=PaymentTransaction.Status.COMPLETED,
            completed_at__year=tax_year
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        if total_payments < Decimal('600.00'):
            raise PaymentValidationError(f"Total payments (${total_payments}) below $600 threshold")
        
        # Check for existing document
        existing = TaxDocument.objects.filter(
            consultant=consultant,
            tax_year=tax_year,
            document_type=TaxDocument.DocumentType.FORM_1099_NEC
        ).exists()
        if existing:
            raise PaymentValidationError(f"1099-NEC already generated for {tax_year}")
        
        # Generate PDF (placeholder - actual PDF generation would go here)
        file_path = f"tax_documents/{consultant.id}/1099-NEC-{tax_year}.pdf"
        file_hash = "placeholder_hash"  # Would be actual SHA-256 of PDF
        
        # Create tax document
        tax_doc = TaxDocument.objects.create(
            consultant=consultant,
            tax_year=tax_year,
            document_type=TaxDocument.DocumentType.FORM_1099_NEC,
            total_amount=total_payments,
            file_path=file_path,
            file_hash=file_hash,
            generated_by=generated_by
        )
        
        # Audit log
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.TAX_DOCUMENT_GENERATED,
            actor=generated_by,
            target_model='TaxDocument',
            target_id=tax_doc.id,
            new_values={'tax_year': tax_year, 'total_amount': str(total_payments)}
        )
        
        return tax_doc
    
    @staticmethod
    @transaction.atomic
    def mark_sent(tax_doc, actor):
        """Mark tax document as sent to consultant."""
        tax_doc.sent_to_consultant = True
        tax_doc.sent_at = timezone.now()
        tax_doc.save()
        
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.TAX_DOCUMENT_SENT,
            actor=actor,
            target_model='TaxDocument',
            target_id=tax_doc.id,
            new_values={'sent_at': str(tax_doc.sent_at)}
        )
        
        return tax_doc
    
    @staticmethod
    @transaction.atomic
    def mark_filed(tax_doc, actor, filing_confirmation=''):
        """Mark tax document as filed with IRS."""
        tax_doc.filed_with_irs = True
        tax_doc.filed_at = timezone.now()
        if filing_confirmation:
            tax_doc.notes = f"{tax_doc.notes}\nFiling confirmation: {filing_confirmation}" if tax_doc.notes else f"Filing confirmation: {filing_confirmation}"
        tax_doc.save()
        
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.TAX_DOCUMENT_FILED,
            actor=actor,
            target_model='TaxDocument',
            target_id=tax_doc.id,
            new_values={'filed_at': str(tax_doc.filed_at)}
        )
        
        return tax_doc


class ReconciliationService:
    """
    Service for payment reconciliation.
    """
    
    @staticmethod
    @transaction.atomic
    def create_reconciliation(batch, reconciled_by, reconciliation_date, actual_amount, transaction=None, notes=''):
        """
        Create a reconciliation record for a batch.
        
        Args:
            batch: PayoutBatch instance
            reconciled_by: User performing reconciliation
            reconciliation_date: Date of reconciliation
            actual_amount: Actual amount paid
            transaction: Optional PaymentTransaction
            notes: Optional notes
        
        Returns:
            PaymentReconciliation instance
        """
        # Get expected amount from batch
        expected_amount = batch.payouts.aggregate(total=Sum('total_commission'))['total'] or Decimal('0.00')
        
        # Calculate discrepancy
        discrepancy = actual_amount - expected_amount if actual_amount else Decimal('0.00')
        
        # Determine status
        if discrepancy == Decimal('0.00'):
            status = PaymentReconciliation.Status.RECONCILED
        else:
            status = PaymentReconciliation.Status.DISCREPANCY
        
        reconciliation = PaymentReconciliation.objects.create(
            batch=batch,
            transaction=transaction,
            reconciliation_date=reconciliation_date,
            reconciled_by=reconciled_by,
            status=status,
            expected_amount=expected_amount,
            actual_amount=actual_amount,
            discrepancy_amount=discrepancy,
            notes=notes
        )
        
        # Audit log
        PaymentAuditLog.objects.create(
            action_type=PaymentAuditLog.ActionType.RECONCILIATION_COMPLETED,
            actor=reconciled_by,
            target_model='PaymentReconciliation',
            target_id=reconciliation.id,
            new_values={'status': status, 'discrepancy_amount': str(discrepancy)}
        )
        
        return reconciliation
    
    @staticmethod
    @transaction.atomic
    def resolve_discrepancy(reconciliation, actor, resolution_notes):
        """
        Resolve a reconciliation discrepancy.
        
        Args:
            reconciliation: PaymentReconciliation instance
            actor: User resolving
            resolution_notes: Explanation of resolution
        
        Returns:
            Updated PaymentReconciliation
        """
        if reconciliation.status != PaymentReconciliation.Status.DISCREPANCY:
            raise PaymentStateError("Can only resolve discrepancies")
        
        reconciliation.status = PaymentReconciliation.Status.RECONCILED
        reconciliation.resolution_notes = resolution_notes
        reconciliation.resolved_at = timezone.now()
        reconciliation.save()
        
        return reconciliation
