"""
Analytics Serializers
Query parameter validation and response shaping only.
No business logic - that stays in services.
"""
from datetime import date
from rest_framework import serializers


class DateRangeSerializer(serializers.Serializer):
    """Common date range query parameters."""
    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)
    
    def validate(self, attrs):
        if attrs['start_date'] > attrs['end_date']:
            raise serializers.ValidationError({
                'start_date': 'Start date must be before or equal to end date'
            })
        return attrs


class WindowSerializer(serializers.Serializer):
    """Window-based query parameters."""
    window = serializers.ChoiceField(choices=['DAILY', 'MONTHLY', 'QUARTERLY', 'ANNUAL'], required=True)


class MetricsQuerySerializer(serializers.Serializer):
    """Query parameters for metrics endpoints."""
    window = serializers.ChoiceField(choices=['DAILY', 'MONTHLY'], required=True)
    period_start = serializers.DateField(required=True)
    period_end = serializers.DateField(required=True)
    scope = serializers.ChoiceField(choices=['GLOBAL', 'MANAGER', 'CONSULTANT'], required=False)
    scope_id = serializers.IntegerField(required=False)
    
    def validate(self, attrs):
        if attrs['period_start'] > attrs['period_end']:
            raise serializers.ValidationError({
                'period_start': 'Period start must be before or equal to period end'
            })
        return attrs


class TaxMetricsQuerySerializer(serializers.Serializer):
    """Query parameters for tax metrics endpoint."""
    window = serializers.ChoiceField(choices=['QUARTERLY', 'ANNUAL'], required=True)
    tax_year = serializers.IntegerField(required=True, min_value=2000, max_value=2100)
    quarter = serializers.IntegerField(required=False, min_value=1, max_value=4)
    scope = serializers.ChoiceField(choices=['GLOBAL', 'CONSULTANT'], required=False)
    scope_id = serializers.IntegerField(required=False)


class ReconciliationMetricsQuerySerializer(serializers.Serializer):
    """Query parameters for reconciliation metrics endpoint."""
    window = serializers.ChoiceField(choices=['DAILY', 'MONTHLY'], required=True)
    period_start = serializers.DateField(required=True)
    period_end = serializers.DateField(required=True)


class DashboardQuerySerializer(serializers.Serializer):
    """Query parameters for dashboard endpoints."""
    year = serializers.IntegerField(required=False, min_value=2000, max_value=2100)
    months = serializers.IntegerField(required=False, min_value=1, max_value=24, default=12)


class TopPerformersQuerySerializer(serializers.Serializer):
    """Query parameters for top performers endpoint."""
    period = serializers.ChoiceField(choices=['YTD', 'MONTH', 'QUARTER'], required=False, default='YTD')
    limit = serializers.IntegerField(required=False, min_value=1, max_value=50, default=10)


class TrendQuerySerializer(serializers.Serializer):
    """Query parameters for trend endpoints."""
    months = serializers.IntegerField(required=False, min_value=1, max_value=24, default=12)


class ExportQuerySerializer(serializers.Serializer):
    """Query parameters for export endpoints."""
    format = serializers.ChoiceField(choices=['csv', 'pdf'], required=False, default='csv')
    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)
    status = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, attrs):
        if attrs['start_date'] > attrs['end_date']:
            raise serializers.ValidationError({
                'start_date': 'Start date must be before or equal to end date'
            })
        return attrs


class TaxExportQuerySerializer(serializers.Serializer):
    """Query parameters for tax export endpoint."""
    format = serializers.ChoiceField(choices=['csv', 'pdf'], required=False, default='csv')


# =============================================================================
# Response Serializers
# =============================================================================

class SummaryKPISerializer(serializers.Serializer):
    """Serializer for summary KPIs."""
    total_paid_ytd = serializers.CharField()
    outstanding_liability = serializers.CharField()
    payment_success_rate = serializers.CharField()
    avg_cycle_days = serializers.CharField()


class TrendItemSerializer(serializers.Serializer):
    """Serializer for trend items."""
    month = serializers.CharField()
    total = serializers.CharField()
    count = serializers.IntegerField(required=False)


class PerformerSerializer(serializers.Serializer):
    """Serializer for performer items."""
    rank = serializers.IntegerField()
    consultant_id = serializers.IntegerField()
    name = serializers.CharField()
    total = serializers.CharField()


class ReconciliationStatusSerializer(serializers.Serializer):
    """Serializer for reconciliation status."""
    matched = serializers.IntegerField()
    pending = serializers.IntegerField()
    discrepancy = serializers.IntegerField()


class FinanceDashboardSerializer(serializers.Serializer):
    """Response serializer for finance dashboard."""
    summary = SummaryKPISerializer()
    commission_trend = TrendItemSerializer(many=True)
    top_performers = PerformerSerializer(many=True)
    reconciliation_status = ReconciliationStatusSerializer()
    computed_at = serializers.DateTimeField()


class ManagerSummarySerializer(serializers.Serializer):
    """Serializer for manager summary."""
    team_total_ytd = serializers.CharField()
    team_size = serializers.IntegerField()
    pending_approvals = serializers.IntegerField()


class ManagerDashboardSerializer(serializers.Serializer):
    """Response serializer for manager dashboard."""
    summary = ManagerSummarySerializer()
    team_trend = TrendItemSerializer(many=True)
    top_team_members = PerformerSerializer(many=True)
    computed_at = serializers.DateTimeField()


class ConsultantSummarySerializer(serializers.Serializer):
    """Serializer for consultant summary."""
    total_paid_ytd = serializers.CharField()
    pending_amount = serializers.CharField()
    w9_status = serializers.CharField()
    tax_docs_count = serializers.IntegerField()


class PayoutItemSerializer(serializers.Serializer):
    """Serializer for payout items."""
    date = serializers.CharField(allow_null=True)
    amount = serializers.CharField()
    status = serializers.CharField()


class ConsultantDashboardSerializer(serializers.Serializer):
    """Response serializer for consultant dashboard."""
    summary = ConsultantSummarySerializer()
    earnings_trend = TrendItemSerializer(many=True)
    recent_payouts = PayoutItemSerializer(many=True)
    computed_at = serializers.DateTimeField()


class CommissionMetricSerializer(serializers.Serializer):
    """Response serializer for commission metrics."""
    window = serializers.CharField()
    period_start = serializers.CharField()
    period_end = serializers.CharField()
    scope = serializers.CharField()
    total_count = serializers.IntegerField()
    total_amount = serializers.CharField()
    approved_count = serializers.IntegerField()
    approved_amount = serializers.CharField()
    average_amount = serializers.CharField()


class PayoutMetricSerializer(serializers.Serializer):
    """Response serializer for payout metrics."""
    window = serializers.CharField()
    period_start = serializers.CharField()
    period_end = serializers.CharField()
    scope = serializers.CharField()
    batch_count = serializers.IntegerField()
    payout_count = serializers.IntegerField()
    total_amount = serializers.CharField()
    paid_amount = serializers.CharField()
    avg_cycle_days = serializers.CharField()
    success_rate = serializers.CharField()


class TaxMetricSerializer(serializers.Serializer):
    """Response serializer for tax metrics."""
    window = serializers.CharField()
    tax_year = serializers.IntegerField()
    quarter = serializers.IntegerField(allow_null=True)
    scope = serializers.CharField()
    total_payments = serializers.CharField()
    consultant_count = serializers.IntegerField()
    above_threshold_count = serializers.IntegerField()
    w9_approved_count = serializers.IntegerField()
    forms_generated_count = serializers.IntegerField()
    forms_filed_count = serializers.IntegerField()


class ReconciliationMetricSerializer(serializers.Serializer):
    """Response serializer for reconciliation metrics."""
    window = serializers.CharField()
    period_start = serializers.CharField()
    period_end = serializers.CharField()
    total_batches = serializers.IntegerField()
    matched_count = serializers.IntegerField()
    pending_count = serializers.IntegerField()
    discrepancy_count = serializers.IntegerField()
    total_discrepancy = serializers.CharField()


class PendingCountSerializer(serializers.Serializer):
    """Response serializer for pending count."""
    pending_count = serializers.IntegerField()
    pending_amount = serializers.CharField()
    as_of = serializers.DateTimeField()


class ExportLogSerializer(serializers.Serializer):
    """Response serializer for export logs."""
    id = serializers.IntegerField()
    report_type = serializers.CharField()
    export_format = serializers.CharField()
    row_count = serializers.IntegerField()
    status = serializers.CharField()
    started_at = serializers.CharField()
    completed_at = serializers.CharField(allow_null=True)


class ErrorSerializer(serializers.Serializer):
    """Standard error response serializer."""
    error = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField(required=False)
