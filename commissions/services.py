"""
Business logic services for the Commissions Engine.

This layer handles:
- Commission calculations
- Override resolution via Hierarchy system
- State transitions
- Adjustment creation
- Transaction management

No API views or URL routing here - pure business logic.
"""

from decimal import Decimal
from django.db import transaction
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from datetime import datetime, timedelta

from .models import Commission
from hierarchy.models import ReportingLine

User = get_user_model()


class CommissionCalculationService:
    """
    Service for calculating commission amounts.
    
    Pure calculation logic - no database writes.
    """
    
    @staticmethod
    def calculate_base_commission(sale_amount, commission_rate, gst_rate=0):
        """
        Calculate base commission amount.
        
        Args:
            sale_amount (Decimal): Sale value (pre-GST or post-GST)
            commission_rate (Decimal): Commission percentage (e.g., 7.00 for 7%)
            gst_rate (Decimal): GST percentage (e.g., 10.00 for 10%)
        
        Returns:
            Decimal: Calculated commission amount
        """
        # Convert to Decimal to ensure precision
        sale_amount = Decimal(str(sale_amount))
        commission_rate = Decimal(str(commission_rate))
        gst_rate = Decimal(str(gst_rate))
        
        # If GST is included, remove it first
        if gst_rate > 0:
            gst_multiplier = Decimal('1.0') + (gst_rate / Decimal('100.0'))
            base_amount = sale_amount / gst_multiplier
        else:
            base_amount = sale_amount
        
        # Calculate commission
        commission = base_amount * (commission_rate / Decimal('100.0'))
        
        # Round to 2 decimal places
        return commission.quantize(Decimal('0.01'))
    
    @staticmethod
    def calculate_override_commission(sale_amount, override_rate, gst_rate=0):
        """
        Calculate manager override commission.
        
        Same logic as base commission but with override rate.
        """
        return CommissionCalculationService.calculate_base_commission(
            sale_amount, override_rate, gst_rate
        )


class OverrideResolutionService:
    """
    Service for resolving manager overrides using Hierarchy system.
    
    Queries Phase 1 hierarchy to determine who gets override commissions.
    """
    
    # Default override rates (can be configurable later)
    DEFAULT_OVERRIDE_RATES = {
        1: Decimal('2.00'),  # Direct manager: 2%
        2: Decimal('1.00'),  # Manager's manager: 1%
    }
    
    MAX_OVERRIDE_LEVELS = 2
    
    @staticmethod
    def get_manager_at_date(consultant, transaction_date):
        """
        Get the consultant's manager at a specific date using Hierarchy system.
        
        Args:
            consultant (User): The consultant
            transaction_date (date): When the transaction occurred
        
        Returns:
            User or None: Manager at that date
        """
        # Query ReportingLine for active manager on that date
        reporting_line = ReportingLine.objects.filter(
            consultant=consultant,
            start_date__lte=transaction_date
        ).filter(
            # Either no end date (still active) or end date is after transaction date
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=transaction_date)
        ).select_related('manager').first()
        
        return reporting_line.manager if reporting_line else None
    
    @classmethod
    def resolve_override_chain(cls, consultant, transaction_date, max_levels=None):
        """
        Resolve the full chain of managers for override commissions.
        
        Args:
            consultant (User): The consultant who made the sale
            transaction_date (date): When the transaction occurred
            max_levels (int): Maximum levels to traverse (default: 2)
        
        Returns:
            list: List of (manager, level) tuples
                Example: [(direct_manager, 1), (senior_manager, 2)]
        """
        if max_levels is None:
            max_levels = cls.MAX_OVERRIDE_LEVELS
        
        override_chain = []
        current_user = consultant
        
        for level in range(1, max_levels + 1):
            manager = cls.get_manager_at_date(current_user, transaction_date)
            
            if not manager:
                break
            
            # Prevent circular references
            if manager == consultant:
                break
            
            override_chain.append((manager, level))
            current_user = manager
        
        return override_chain
    
    @classmethod
    def get_override_rate(cls, level):
        """Get the override rate for a specific level"""
        return cls.DEFAULT_OVERRIDE_RATES.get(level, Decimal('0.00'))


class CommissionCreationService:
    """
    Service for creating commission records atomically.
    
    Creates base commission + override commissions in a transaction.
    """
    
    @staticmethod
    @transaction.atomic
    def create_base_commission_with_overrides(
        consultant,
        transaction_date,
        sale_amount,
        gst_rate,
        commission_rate,
        reference_number,
        notes='',
        created_by=None
    ):
        """
        Create base commission and automatically create override commissions.
        
        This is the main entry point for commission creation.
        
        Args:
            consultant (User): Who earned the commission
            transaction_date (date): When the sale occurred
            sale_amount (Decimal): Sale amount
            gst_rate (Decimal): GST percentage
            commission_rate (Decimal): Commission percentage
            reference_number (str): Unique transaction reference
            notes (str): Optional notes
            created_by (User): Who created this record
        
        Returns:
            dict: {
                'base_commission': Commission instance,
                'override_commissions': list of Commission instances,
                'total_created': int
            }
        
        Raises:
            ValidationError: If validation fails
        """
        # Calculate base commission amount
        calculated_amount = CommissionCalculationService.calculate_base_commission(
            sale_amount, commission_rate, gst_rate
        )
        
        # Create base commission
        base_commission = Commission.objects.create(
            commission_type='base',
            consultant=consultant,
            manager=None,  # Base commissions have no manager
            transaction_date=transaction_date,
            sale_amount=sale_amount,
            gst_rate=gst_rate,
            commission_rate=commission_rate,
            calculated_amount=calculated_amount,
            state='draft',
            reference_number=reference_number,
            notes=notes,
            created_by=created_by
        )
        
        # Resolve override chain
        override_chain = OverrideResolutionService.resolve_override_chain(
            consultant, transaction_date
        )
        
        # Create override commissions
        override_commissions = []
        for manager, level in override_chain:
            override_rate = OverrideResolutionService.get_override_rate(level)
            override_amount = CommissionCalculationService.calculate_override_commission(
                sale_amount, override_rate, gst_rate
            )
            
            override_commission = Commission.objects.create(
                commission_type='override',
                consultant=consultant,
                manager=manager,  # Denormalized for immutability
                transaction_date=transaction_date,
                sale_amount=sale_amount,
                gst_rate=gst_rate,
                commission_rate=override_rate,
                calculated_amount=override_amount,
                state='draft',
                reference_number=f"{reference_number}-OVR-L{level}",
                notes=f"Level {level} override for {consultant.username}",
                override_level=level,
                parent_commission=base_commission,
                created_by=created_by
            )
            override_commissions.append(override_commission)
        
        return {
            'base_commission': base_commission,
            'override_commissions': override_commissions,
            'total_created': 1 + len(override_commissions)
        }


class StateTransitionService:
    """
    Service for managing commission state transitions.
    
    Enforces state machine rules and records actors.
    """
    
    # Valid state transitions (same as serializer)
    VALID_TRANSITIONS = {
        'draft': ['submitted'],
        'submitted': ['approved', 'rejected'],
        'approved': ['paid'],
        'rejected': ['draft'],
        'paid': [],  # Final state
    }
    
    @classmethod
    def can_transition(cls, from_state, to_state):
        """Check if transition is valid"""
        return to_state in cls.VALID_TRANSITIONS.get(from_state, [])
    
    @classmethod
    @transaction.atomic
    def transition_to_submitted(cls, commission, actor=None, notes=''):
        """
        Transition commission from draft to submitted.
        
        Args:
            commission (Commission): The commission to transition
            actor (User): Who is performing the transition
            notes (str): Optional notes
        
        Returns:
            Commission: Updated commission
        
        Raises:
            ValidationError: If transition is invalid
        """
        if not cls.can_transition(commission.state, 'submitted'):
            raise ValidationError(
                f"Cannot transition from '{commission.state}' to 'submitted'."
            )
        
        commission.state = 'submitted'
        if notes:
            commission.notes = f"{commission.notes}\n[Submitted] {notes}"
        commission.save()
        
        return commission
    
    @classmethod
    @transaction.atomic
    def transition_to_approved(cls, commission, actor, notes=''):
        """
        Transition commission from submitted to approved.
        
        Also approves related override commissions.
        """
        if not cls.can_transition(commission.state, 'approved'):
            raise ValidationError(
                f"Cannot transition from '{commission.state}' to 'approved'."
            )
        
        commission.state = 'approved'
        commission.approved_by = actor
        commission.approved_at = datetime.now()
        if notes:
            commission.notes = f"{commission.notes}\n[Approved] {notes}"
        commission.save()
        
        # If this is a base commission, also approve related overrides
        if commission.commission_type == 'base':
            related_overrides = Commission.objects.filter(
                parent_commission=commission,
                commission_type='override'
            )
            for override_comm in related_overrides:
                if override_comm.state == 'submitted':
                    override_comm.state = 'approved'
                    override_comm.approved_by = actor
                    override_comm.approved_at = datetime.now()
                    override_comm.save()
        
        return commission
    
    @classmethod
    @transaction.atomic
    def transition_to_rejected(cls, commission, actor, rejection_reason):
        """Transition commission from submitted to rejected"""
        if not cls.can_transition(commission.state, 'rejected'):
            raise ValidationError(
                f"Cannot transition from '{commission.state}' to 'rejected'."
            )
        
        commission.state = 'rejected'
        commission.rejection_reason = rejection_reason
        commission.save()
        
        return commission
    
    @classmethod
    @transaction.atomic
    def transition_to_paid(cls, commission, actor, paid_at=None):
        """Transition commission from approved to paid"""
        if not cls.can_transition(commission.state, 'paid'):
            raise ValidationError(
                f"Cannot transition from '{commission.state}' to 'paid'."
            )
        
        commission.state = 'paid'
        commission.paid_at = paid_at or datetime.now()
        commission.save()
        
        return commission


class AdjustmentService:
    """
    Service for creating adjustment commissions.
    
    Adjustments are used to correct paid commissions without modifying them.
    """
    
    @staticmethod
    @transaction.atomic
    def create_adjustment(
        original_commission,
        adjustment_amount,
        notes,
        created_by=None
    ):
        """
        Create an adjustment commission for a paid commission.
        
        Args:
            original_commission (Commission): The commission being adjusted
            adjustment_amount (Decimal): Positive or negative adjustment
            notes (str): Reason for adjustment
            created_by (User): Who created the adjustment
        
        Returns:
            Commission: The adjustment commission record
        
        Raises:
            ValidationError: If original is not paid or validation fails
        """
        # Validate original commission is paid
        if original_commission.state != 'paid':
            raise ValidationError(
                "Adjustments can only be created for paid commissions."
            )
        
        # Validate adjustment amount is not zero
        if adjustment_amount == 0:
            raise ValidationError("Adjustment amount cannot be zero.")
        
        # Create adjustment commission
        adjustment = Commission.objects.create(
            commission_type='adjustment',
            consultant=original_commission.consultant,
            manager=original_commission.manager,  # Preserve manager
            transaction_date=original_commission.transaction_date,
            sale_amount=original_commission.sale_amount,
            gst_rate=original_commission.gst_rate,
            commission_rate=Decimal('0.00'),  # Not applicable for adjustments
            calculated_amount=adjustment_amount,
            state='draft',
            reference_number=f"{original_commission.reference_number}-ADJ-{datetime.now().timestamp()}",
            notes=notes,
            adjustment_for=original_commission,
            created_by=created_by
        )
        
        return adjustment


# Import fix for OverrideResolutionService.get_manager_at_date
from django.db import models
