from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from commissions.models import Commission, CommissionApproval, ApprovalHistory

class ApprovalError(ValidationError):
    """Base error for approval workflow issues"""
    pass

class ApprovalStateService:
    """
    Core service for managing commission lifecycle transitions and audit trails.
    
    This service ensures that no financial data is ever modified during approval.
    """
    
    VALID_TRANSITIONS = {
        'draft': ['submitted'],
        'submitted': ['approved', 'rejected'],
        'approved': ['paid'],
        'rejected': ['submitted'],  # Can resubmit from rejected (moves back to submitted)
    }

    @staticmethod
    def validate_transition(commission, target_state):
        current_state = commission.state
        allowed = ApprovalStateService.VALID_TRANSITIONS.get(current_state, [])
        if target_state not in allowed:
            raise ApprovalError(
                f"Invalid transition from '{current_state}' to '{target_state}'."
            )

    @staticmethod
    @transaction.atomic
    def record_action(commission, action, actor, to_state, notes=""):
        """
        Atomically updates commission state and writes into approval history.
        """
        from_state = commission.state
        
        # 1. Update Commission record
        commission.state = to_state
        
        # Special case: if approving, also set approved_by/at on Commission for backward compatibility
        if to_state == 'approved':
            commission.approved_by = actor
            commission.approved_at = timezone.now()
        
        # Special case: if paying, also set paid_at
        if to_state == 'paid':
            commission.paid_at = timezone.now()
            
        commission.save()
        
        # 2. Ensure Approval process record exists
        approval_record, created = CommissionApproval.objects.get_or_create(
            commission=commission
        )
        
        # 3. Write History Entry
        history_entry = ApprovalHistory.objects.create(
            approval_record=approval_record,
            action=action,
            actor=actor,
            from_state=from_state,
            to_state=to_state,
            notes=notes
        )
        
        return history_entry


class ApprovalSubmissionService:
    """Handles the 'SUBMIT' action (Draft -> Submitted)"""
    
    @staticmethod
    @transaction.atomic
    def submit(commission, actor, notes=""):
        ApprovalStateService.validate_transition(commission, 'submitted')
        
        approval_record, created = CommissionApproval.objects.get_or_create(
            commission=commission
        )
        
        # Lock in the approver at time of submission
        # For base commissions, it uses the manager identified in Phase 1 (if any)
        # For overrides, it's the manager assigned to the commission
        if not approval_record.assigned_approver:
            approval_record.assigned_approver = commission.manager
            approval_record.assigned_role = 'MANAGER'
            approval_record.save()
            
        return ApprovalStateService.record_action(
            commission, 'SUBMIT', actor, 'submitted', notes
        )


class ApprovalDecisionService:
    """Handles 'APPROVE' or 'REJECT' actions (Submitted -> Approved/Rejected)"""
    
    @staticmethod
    @transaction.atomic
    def approve(commission, actor, notes=""):
        ApprovalStateService.validate_transition(commission, 'approved')
        
        # Security: Only assigned approver, Manager (Hierarchy), or Admin can approve
        approval_record = getattr(commission, 'approval', None)
        is_admin = actor.is_staff or actor.groups.filter(name='Admins').exists()
        
        # Check hierarchy permission
        from hierarchy.models import ReportingLine
        is_hierarchy_manager = ReportingLine.objects.filter(
            manager=actor, 
            consultant=commission.consultant,
            is_active=True
        ).exists()
        
        is_explicit_manager = commission.manager == actor
        
        if not is_admin and not is_hierarchy_manager and not is_explicit_manager and (not approval_record or approval_record.assigned_approver != actor):
            raise ApprovalError(f"Auth Denied. Admin:{is_admin}, Hier:{is_hierarchy_manager}, Expl:{is_explicit_manager}, Actor:{actor.username}, Cons:{commission.consultant.username}")
            
        history = ApprovalStateService.record_action(
            commission, 'APPROVE', actor, 'approved', notes
        )
        
        # CASCADE: If this is a base commission, automatically approve linked overrides
        if commission.commission_type == 'base':
             overrides = Commission.objects.filter(
                 parent_commission=commission, 
                 state='submitted' # Only auto-approve if they were submitted
             )
             for ovr in overrides:
                 ApprovalDecisionService.approve(ovr, actor, f"Auto-approved via base {commission.reference_number}")
                 
        return history

    @staticmethod
    @transaction.atomic
    def reject(commission, actor, rejection_reason):
        if not rejection_reason:
            raise ApprovalError("Rejection reason is mandatory.")
            
        ApprovalStateService.validate_transition(commission, 'rejected')
        
        # Security: Only assigned approver, Manager, or Admin can reject
        approval_record = getattr(commission, 'approval', None)
        is_admin = actor.is_staff or actor.groups.filter(name='Admins').exists()
        
        # Check hierarchy permission
        from hierarchy.models import ReportingLine
        is_hierarchy_manager = ReportingLine.objects.filter(
            manager=actor, 
            consultant=commission.consultant,
            is_active=True
        ).exists()
        
        is_explicit_manager = commission.manager == actor
        
        if not is_admin and not is_hierarchy_manager and not is_explicit_manager and (not approval_record or approval_record.assigned_approver != actor):
            raise ApprovalError("You are not authorized to reject this commission.")
            
        return ApprovalStateService.record_action(
            commission, 'REJECT', actor, 'rejected', rejection_reason
        )


class ApprovalPaymentService:
    """Handles 'PAID' action (Approved -> Paid)"""
    
    @staticmethod
    @transaction.atomic
    def mark_as_paid(commission, actor, notes=""):
        # Security: Only Admins can mark as paid
        if not (actor.is_staff or actor.groups.filter(name='Admins').exists()):
            raise ApprovalError("Only Admins or Finance roles can mark commissions as paid.")
            
        ApprovalStateService.validate_transition(commission, 'paid')
        
        return ApprovalStateService.record_action(
            commission, 'PAID', actor, 'paid', notes
        )
