from rest_framework import serializers
from django.contrib.auth import get_user_model
from decimal import Decimal
from .models import Commission, CommissionApproval, ApprovalHistory
from .services import CommissionCalculationService

User = get_user_model()


class UserBasicSerializer(serializers.ModelSerializer):
    """Minimal user representation for commission responses"""
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = fields


class CommissionCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating base commissions.
    
    Validation only - NO business logic or hierarchy queries.
    Business logic (override creation, calculation) happens in views/services.
    """
    consultant_id = serializers.IntegerField(write_only=True)
    
    
    class Meta:
        model = Commission
        fields = [
            'consultant_id',
            'transaction_date',
            'sale_amount',
            'gst_rate',
            'commission_rate',
            'calculated_amount',
            'reference_number',
            'notes',
        ]
    
    def validate_consultant_id(self, value):
        """Validate consultant exists"""
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError(f"User with ID {value} not found.")
        return value
    
    def validate_sale_amount(self, value):
        """Validate sale amount is positive"""
        if value <= 0:
            raise serializers.ValidationError("Sale amount must be greater than 0.")
        return value
    
    def validate_gst_rate(self, value):
        """Validate GST rate is valid percentage"""
        if value < 0 or value > 100:
            raise serializers.ValidationError("GST rate must be between 0 and 100.")
        return value
    
    def validate_commission_rate(self, value):
        """Validate commission rate is valid percentage"""
        if value <= 0 or value > 100:
            raise serializers.ValidationError("Commission rate must be between 0 and 100.")
        return value
    
    def validate_calculated_amount(self, value):
        """Validate calculated amount is positive"""
        if value <= 0:
            raise serializers.ValidationError("Calculated amount must be greater than 0.")
        return value
    
    def validate_reference_number(self, value):
        """Validate reference number is unique"""
        if Commission.objects.filter(reference_number=value).exists():
            raise serializers.ValidationError({
                "error": "duplicate_reference",
                "detail": "A commission with this reference number already exists."
            })
        return value
    
    def validate(self, attrs):
        """Cross-field validation"""
        sale_amount = attrs.get('sale_amount')
        commission_rate = attrs.get('commission_rate')
        calculated_amount = attrs.get('calculated_amount')
        
        # Sanity check: calculated amount should be reasonable
        expected_amount = CommissionCalculationService.calculate_base_commission(
            sale_amount, commission_rate, attrs.get('gst_rate', 0)
        )
        tolerance = Decimal('0.01')  # Allow 1 cent difference for rounding
        
        if abs(calculated_amount - expected_amount) > tolerance:
            raise serializers.ValidationError({
                "calculated_amount": (
                    f"Calculated amount ({calculated_amount}) does not match "
                    f"expected value ({expected_amount}) based on sale amount "
                    f"and commission rate (after GST exclusion)."
                )
            })
        
        return attrs


class BulkCommissionCreateSerializer(serializers.Serializer):
    """
    Serializer for bulk commission creation.
    Allows creating multiple commissions in one transaction.
    """
    commissions = CommissionCreateSerializer(many=True)


class CommissionReadSerializer(serializers.ModelSerializer):
    """
    Serializer for reading commission records.
    
    Includes nested user data and related commissions.
    Read-only, no validation needed.
    """
    consultant = UserBasicSerializer(read_only=True)
    manager = UserBasicSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    approved_by = UserBasicSerializer(read_only=True)
    approval = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    
    def get_approval(self, obj):
        try:
            return CommissionApprovalSerializer(obj.approval).data
        except (CommissionApproval.DoesNotExist, AttributeError):
            return None

    def get_client_name(self, obj):
        # Fallback to parent commission client name if empty (for overrides)
        if obj.client_name:
            return obj.client_name
        if obj.parent_commission and obj.parent_commission.client_name:
            return obj.parent_commission.client_name
        return obj.reference_number # Last resort fallback
    
    class Meta:
        model = Commission
        fields = [
            'id',
            'commission_type',
            'consultant',
            'manager',
            'transaction_date',
            'sale_amount',
            'gst_rate',
            'commission_rate',
            'calculated_amount',
            'state',
            'reference_number',
            'notes',
            'override_level',
            'parent_commission',
            'adjustment_for',
            'created_at',
            'updated_at',
            'created_by',
            'approved_by',
            'approved_at',
            'paid_at',
            'rejection_reason',
            'approval',
            'client_name',
        ]
        read_only_fields = fields


class CommissionListSerializer(serializers.ModelSerializer):
    """
    Lighter serializer for list views.
    
    Omits some fields for performance.
    """
    consultant = UserBasicSerializer(read_only=True)
    manager = UserBasicSerializer(read_only=True)
    client_name = serializers.SerializerMethodField()
    
    def get_client_name(self, obj):
        if obj.client_name:
            return obj.client_name
        if obj.parent_commission and obj.parent_commission.client_name:
            return obj.parent_commission.client_name
        return obj.reference_number
    
    class Meta:
        model = Commission
        fields = [
            'id',
            'commission_type',
            'consultant',
            'manager',
            'transaction_date',
            'sale_amount',
            'calculated_amount',
            'state',
            'reference_number',
            'override_level',
            'created_at',
            'client_name',
        ]
        read_only_fields = fields


class CommissionSummarySerializer(serializers.Serializer):
    """
    Serializer for dashboard summary data.
    
    This is NOT a model serializer - it serializes aggregated data.
    Used for endpoints like /api/commissions/summary/
    """
    period = serializers.DictField(child=serializers.DateField())
    
    base_commissions = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2))
    override_commissions = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2))
    
    total_earnings = serializers.DecimalField(max_digits=12, decimal_places=2)
    pending_approval = serializers.DecimalField(max_digits=12, decimal_places=2)
    ready_for_payout = serializers.DecimalField(max_digits=12, decimal_places=2)


class CommissionAdjustmentSerializer(serializers.Serializer):
    """
    Serializer for creating adjustment commissions.
    
    Validates adjustment rules without performing the creation.
    """
    adjustment_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Adjustment amount (positive or negative)"
    )
    notes = serializers.CharField(
        required=True,
        help_text="Reason for adjustment"
    )
    
    def validate_adjustment_amount(self, value):
        """Validate adjustment amount is not zero"""
        if value == 0:
            raise serializers.ValidationError("Adjustment amount cannot be zero.")
        return value
    
    def validate_notes(self, value):
        """Require meaningful notes for adjustments"""
        if len(value.strip()) < 10:
            raise serializers.ValidationError(
                "Please provide a detailed reason for the adjustment (minimum 10 characters)."
            )
        return value
    
    def validate(self, attrs):
        """Validate original commission can be adjusted"""
        # This will be called with the original commission instance passed via context
        original_commission = self.context.get('original_commission')
        
        if not original_commission:
            raise serializers.ValidationError("Original commission not found in context.")
        
        # Adjustments can only be made to paid commissions
        if original_commission.state != 'paid':
            raise serializers.ValidationError({
                "error": "invalid_state",
                "detail": "Adjustments can only be created for paid commissions."
            })
        
        return attrs


class StateTransitionSerializer(serializers.Serializer):
    """
    Serializer for state transitions (submit, approve, reject, pay).
    
    Validates transition is allowed based on current state.
    """
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional notes for this transition"
    )
    rejection_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Required for rejections"
    )
    paid_at = serializers.DateTimeField(
        required=False,
        help_text="Optional payment timestamp (for mark-paid)"
    )
    
    # Valid state transitions
    VALID_TRANSITIONS = {
        'draft': ['submitted'],
        'submitted': ['approved', 'rejected'],
        'approved': ['paid'],
        'rejected': ['draft'],
        'paid': [],  # Final state
    }
    
    def validate(self, attrs):
        """Validate state transition is allowed"""
        commission = self.context.get('commission')
        target_state = self.context.get('target_state')
        
        if not commission or not target_state:
            raise serializers.ValidationError("Commission and target_state required in context.")
        
        current_state = commission.state
        
        # Check if transition is valid
        if target_state not in self.VALID_TRANSITIONS.get(current_state, []):
            raise serializers.ValidationError({
                "error": "invalid_transition",
                "detail": f"Cannot transition from '{current_state}' to '{target_state}'."
            })
        
        # Rejection requires reason
        if target_state == 'rejected' and not attrs.get('rejection_reason'):
            raise serializers.ValidationError({
                "rejection_reason": "Rejection reason is required when rejecting a commission."
            })
        
        return attrs


        return value


class ApprovalHistorySerializer(serializers.ModelSerializer):
    """Serializer for chronological audit log entries"""
    actor = UserBasicSerializer(read_only=True)
    
    class Meta:
        model = ApprovalHistory
        fields = ['id', 'action', 'actor', 'from_state', 'to_state', 'notes', 'timestamp']
        read_only_fields = fields


class CommissionApprovalSerializer(serializers.ModelSerializer):
    """Serializer for the overall approval workflow state"""
    assigned_approver = UserBasicSerializer(read_only=True)
    history = ApprovalHistorySerializer(many=True, read_only=True)
    
    class Meta:
        model = CommissionApproval
        fields = [
            'id', 'assigned_approver', 'assigned_role', 
            'is_auto_approved', 'created_at', 'updated_at', 'history'
        ]
        read_only_fields = fields


class ApprovalActionBaseSerializer(serializers.Serializer):
    """Base for workflow action serializers"""
    notes = serializers.CharField(required=False, allow_blank=True)


class ApprovalRejectSerializer(ApprovalActionBaseSerializer):
    """Validation for rejection - requires reason"""
    rejection_reason = serializers.CharField(required=True, min_length=5)


class ApprovalPaySerializer(ApprovalActionBaseSerializer):
    """Validation for marking as paid"""
    paid_at = serializers.DateTimeField(required=False, allow_null=True)
