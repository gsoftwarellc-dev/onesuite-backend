from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from decimal import Decimal

from commissions.models import Commission
from .models import PayoutBatch, Payout, PayoutLineItem, PayoutHistory

class PayoutError(Exception):
    """Base exception for payout logic errors."""
    pass

class PayoutPermissionError(PayoutError):
    """Raised when user lacks permission for an action."""
    pass

class PayoutStateError(PayoutError):
    """Raised when attempting invalid state transition."""
    pass

class PayoutValidationError(PayoutError):
    """Raised when business rules are violated (e.g., closed period, empty batch)."""
    pass

class PayoutCalculationService:
    """
    Service to calculate and generate draft payouts.
    """
    
    @staticmethod
    @transaction.atomic
    def create_batch_for_period(period, created_by, run_date=None, notes=""):
        """
        Creates a new Payout Batch for a given period and finding eligible commissions.
        """
        # 1. Validation
        if period.status == 'CLOSED':
             raise PayoutValidationError("Cannot create batch for a closed period.")
             
        # Optional: Prevent multiple DRAFT batches if that's a rule, but we allow it for now.
        
        # 2. Create Batch
        if not run_date:
            run_date = timezone.now().date()
            
        import random
        suffix = random.randint(1000, 9999)
        reference = f"PAY-{period.name.replace(' ', '-').upper()}-{timezone.now().strftime('%Y%m%d-%H%M%S')}-{suffix}"
        
        batch = PayoutBatch.objects.create(
            period=period,
            reference_number=reference,
            run_date=run_date,
            status=PayoutBatch.Status.DRAFT,
            created_by=created_by,
            notes=notes
        )
        
        # 3. Generate Draft Payouts
        PayoutCalculationService.generate_draft_payouts(batch)
        
        # Log creation
        PayoutHistory.objects.create(
            batch=batch,
            actor=created_by,
            action='CREATE',
            notes=f"Created batch {reference}"
        )
        
        return batch

    @staticmethod
    def generate_draft_payouts(batch):
        """
        Finds eligible commissions and links them to the batch.
        Eligible = State is APPROVED and not linked to any other PayoutLineItem.
        """
        if batch.status != PayoutBatch.Status.DRAFT:
            raise PayoutStateError("Can only generate payouts for DRAFT batches.")
            
        # 1. Find eligible commissions
        eligible_commissions = Commission.objects.filter(
            state='approved',
            payout_line_item__isnull=True  # Not already in a payout
        ).select_related('consultant')
        
        if not eligible_commissions.exists():
            return 0

        # 2. Group by consultant
        consultant_groups = {}
        for comm in eligible_commissions:
            if comm.consultant_id not in consultant_groups:
                consultant_groups[comm.consultant_id] = []
            consultant_groups[comm.consultant_id].append(comm)
            
        payouts_created = 0
        
        # 3. Create Payouts and Line Items
        for consultant_id, commissions in consultant_groups.items():
            
            # Create Payout Header
            payout, created = Payout.objects.get_or_create(
                batch=batch,
                consultant_id=consultant_id,
                defaults={
                    'status': Payout.Status.DRAFT,
                    'total_commission': Decimal('0.00'),
                    'total_adjustment': Decimal('0.00'),
                    'total_tax': Decimal('0.00'),
                    'net_amount': Decimal('0.00'),
                }
            )
            
            # Ensure we are working with Decimals if fetched from DB (SQLite can fetch floats sometimes)
            payout.total_commission = Decimal(str(payout.total_commission))
            payout.total_adjustment = Decimal(str(payout.total_adjustment))
            payout.total_tax = Decimal(str(payout.total_tax))

            total_comm = Decimal('0.00')
            
            for comm in commissions:
                # Create Line Item (OneToOne ensures uniqueness)
                line_item = PayoutLineItem.objects.create(
                    payout=payout,
                    commission=comm,
                    amount=comm.calculated_amount,
                    description=f"{comm.get_commission_type_display()} - {comm.reference_number}"
                )
                total_comm += comm.calculated_amount
            
            # Update totals (Decimal arithmetic)
            payout.total_commission += total_comm
            payout.net_amount = payout.total_commission + payout.total_adjustment - payout.total_tax
            payout.save()
            
            payouts_created += 1
            
        return payouts_created


class PayoutLifecycleService:
    """
    Manages state transitions: LOCK, RELEASE, VOID.
    """
    
    @staticmethod
    @transaction.atomic
    def lock_batch(batch, user):
        """
        Locks the batch. No more line items can be added/removed.
        """
        if batch.status != PayoutBatch.Status.DRAFT:
            raise PayoutStateError(f"Cannot lock batch in {batch.status} state.")
            
        if not batch.payouts.exists():
            raise PayoutValidationError("Cannot lock an empty batch.")
            
        batch.status = PayoutBatch.Status.LOCKED
        batch.save()
        
        PayoutHistory.objects.create(
            batch=batch,
            actor=user,
            action='LOCK',
            notes="Batch Locked. Ready for processing."
        )
        return batch

    @staticmethod
    @transaction.atomic
    def release_batch(batch, user):
        """
        Releases the batch. This is the Point of No Return.
        1. batch -> RELEASED
        2. payouts -> PAID
        3. commissions -> PAID
        """
        if batch.status != PayoutBatch.Status.LOCKED:
            raise PayoutStateError("Batch must be LOCKED before releasing.")
            
        # 1. Update Batch
        batch.status = PayoutBatch.Status.RELEASED
        batch.released_at = timezone.now()
        batch.save()
        
        # 2. Update Payouts
        batch.payouts.update(status=Payout.Status.PAID, paid_at=timezone.now())
        
        # 3. Update Commissions (Bulk update via relationship)
        # Get all line items for this batch
        line_items = PayoutLineItem.objects.filter(payout__batch=batch)
        
        # Collect commission IDs (To optimize with bulk update if list isn't huge, 
        # or use subquery update for large datasets)
        commission_ids = line_items.values_list('commission_id', flat=True)
        
        # Mark Commissions as PAID
        Commission.objects.filter(id__in=commission_ids).update(
            state='paid',
            paid_at=timezone.now()
            # approved_by is kept as original approver
        )
        
        PayoutHistory.objects.create(
            batch=batch,
            actor=user,
            action='RELEASE',
            notes="Batch Released. Commissions marked as PAID."
        )
        return batch

    @staticmethod
    @transaction.atomic
    def void_batch(batch, user):
        """
        Voids a batch.
        1. batch -> VOID
        2. Payouts/LineItems logic:
           - We keep the Batch and Payout records for audit (as VOID).
           - We DELETE the LineItems to free the specific Commissions.
           - Commissions return to 'approved' state automatically (since they are unchanged).
        """
        if batch.status == PayoutBatch.Status.RELEASED:
            raise PayoutStateError("Cannot void a RELEASED batch (must reverse transactions manually).")
            
        # 1. Update Batch
        batch.status = PayoutBatch.Status.VOID
        batch.save()
        
        # 2. Update Payouts to Error/Draft (or stick to Void concept, but models.py doesn't have VOID for payout)
        # Let's delete the line items to unlink commissions
        line_items = PayoutLineItem.objects.filter(payout__batch=batch)
        count = line_items.count()
        line_items.delete() # This frees the OneToOne link on Commissions
        
        # Commissions are now free (still 'approved', just not linked)
        
        PayoutHistory.objects.create(
            batch=batch,
            actor=user,
            action='VOID',
            notes=f"Batch Voided. {count} commissions released back to pool."
        )
        return batch
