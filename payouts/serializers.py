from rest_framework import serializers
from .models import PayoutPeriod, PayoutBatch, Payout, PayoutLineItem, PayoutHistory
from users.serializers import UserSerializer # Assuming a generic user serializer exists, or we define a minimal one here

class UserMinimalSerializer(serializers.Serializer):
    """Minimal user info for responses"""
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()


class PayoutPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutPeriod
        fields = ['id', 'name', 'start_date', 'end_date', 'status', 'is_tax_year_end']


class PayoutLineItemSerializer(serializers.ModelSerializer):
    """
    Shows commission details for a line item.
    """
    commission_reference = serializers.CharField(source='commission.reference_number', read_only=True)
    commission_date = serializers.DateField(source='commission.transaction_date', read_only=True)
    
    class Meta:
        model = PayoutLineItem
        fields = ['id', 'amount', 'description', 'commission_reference', 'commission_date']


class PayoutDetailSerializer(serializers.ModelSerializer):
    """
    Detailed view of a single consultant's payout, including line items.
    """
    consultant = UserMinimalSerializer(read_only=True)
    line_items = PayoutLineItemSerializer(many=True, read_only=True)
    
    class Meta:
        model = Payout
        fields = [
            'id', 'consultant', 'status', 'total_commission', 
            'total_adjustment', 'total_tax', 'net_amount', 
            'payment_reference', 'paid_at', 'line_items'
        ]


class PayoutListSerializer(serializers.ModelSerializer):
    """
    Summary view of a payout (no line items).
    """
    consultant = UserMinimalSerializer(read_only=True)
    
    class Meta:
        model = Payout
        fields = [
            'id', 'consultant', 'status', 'net_amount', 'paid_at'
        ]


class PayoutBatchSerializer(serializers.ModelSerializer):
    """
    Summary of a Payout Run / Batch.
    """
    created_by = UserMinimalSerializer(read_only=True)
    period_name = serializers.CharField(source='period.name', read_only=True)
    payout_count = serializers.IntegerField(source='payouts.count', read_only=True)
    total_amount = serializers.SerializerMethodField()

    class Meta:
        model = PayoutBatch
        fields = [
            'id', 'reference_number', 'period', 'period_name',
            'run_date', 'status', 'notes', 'created_by', 
            'created_at', 'released_at', 'payout_count', 'total_amount'
        ]
        read_only_fields = ['reference_number', 'status', 'created_by', 'released_at']

    def get_total_amount(self, obj):
        # Effective aggregation or pre-calculated field
        # For huge datasets, this should be optimized.
        from django.db.models import Sum
        return obj.payouts.aggregate(Sum('net_amount'))['net_amount__sum'] or 0.00


class PayoutBatchDetailSerializer(PayoutBatchSerializer):
    """
    Full Batch details including list of payouts.
    """
    payouts = PayoutListSerializer(many=True, read_only=True)
    
    class Meta(PayoutBatchSerializer.Meta):
        fields = PayoutBatchSerializer.Meta.fields + ['payouts']


class PayoutBatchCreateSerializer(serializers.Serializer):
    """
    Input serializer for creating a draft batch.
    """
    period_id = serializers.IntegerField()
    run_date = serializers.DateField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class BatchActionSerializer(serializers.Serializer):
    """
    Simple validation for batch actions (Lock, Release, Void).
    """
    confirm = serializers.BooleanField(required=True)
