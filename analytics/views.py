"""
Analytics Views
All 17 endpoints as specified in Phase 6.3 API Design.
Views only call services - no business logic here.
With caching and rate limiting applied.
"""
from datetime import date

from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Sum, Count
from django.db.models.functions import Coalesce
from decimal import Decimal

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from commissions.models import Commission
from hierarchy.models import ReportingLine

from .serializers import (
    DashboardQuerySerializer,
    MetricsQuerySerializer,
    TaxMetricsQuerySerializer,
    ReconciliationMetricsQuerySerializer,
    TopPerformersQuerySerializer,
    TrendQuerySerializer,
    ExportQuerySerializer,
    TaxExportQuerySerializer,
)
from .services import (
    FinanceDashboardService,
    ManagerDashboardService,
    ConsultantDashboardService,
    CommissionMetricsService,
    PayoutMetricsService,
    TaxMetricsService,
    ReconciliationMetricsService,
    CommissionDetailExportService,
    PayoutHistoryExportService,
    TaxYearSummaryExportService,
    MyEarningsExportService,
    ExportLogService,
    is_finance_or_admin,
    is_manager,
    get_team_member_ids,
)
from .exceptions import (
    AnalyticsError,
    ForbiddenScopeError,
    ValidationError,
    ExportLimitExceededError,
)
from .throttling import (
    AnalyticsDashboardThrottle,
    AnalyticsMetricsThrottle,
    AnalyticsExportThrottle,
)
from .caching import (
    build_dashboard_cache_key,
    build_metrics_cache_key,
    build_top_performers_cache_key,
    build_trend_cache_key,
    get_cached,
    set_cached,
    DASHBOARD_CACHE_TTL,
)


def get_client_ip(request):
    """Get client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class AnalyticsAPIView(APIView):
    """Base view for analytics endpoints with error handling."""
    permission_classes = [IsAuthenticated]
    
    def handle_exception(self, exc):
        """Convert custom exceptions to standard error envelope."""
        from rest_framework.exceptions import Throttled
        
        # Handle throttled exceptions with standard envelope
        if isinstance(exc, Throttled):
            return Response(
                {
                    'error': 'rate_limited',
                    'message': 'Too many requests',
                    'details': {'retry_after': exc.wait}
                },
                status=429
            )
        
        if isinstance(exc, AnalyticsError):
            return Response(
                exc.to_dict(),
                status=exc.status_code
            )
        return super().handle_exception(exc)


# =============================================================================
# Dashboard Endpoints (3) - Cached, 60/min throttle
# =============================================================================

class FinanceDashboardView(AnalyticsAPIView):
    """
    GET /api/analytics/dashboards/finance/
    Finance/Admin dashboard with full access.
    """
    throttle_classes = [AnalyticsDashboardThrottle]
    
    def get(self, request):
        serializer = DashboardQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        year = params.get('year', timezone.now().year)
        months = params.get('months', 12)
        
        # Check cache
        cache_key = build_dashboard_cache_key('finance', request.user.id, year=year, months=months)
        cached = get_cached(cache_key)
        if cached:
            return Response(cached)
        
        response_data = {
            'summary': FinanceDashboardService.get_summary(request.user, year),
            'commission_trend': FinanceDashboardService.get_commission_trend(request.user, months),
            'top_performers': FinanceDashboardService.get_top_performers(request.user),
            'reconciliation_status': FinanceDashboardService.get_reconciliation_status(request.user),
            'computed_at': timezone.now().isoformat(),
            'cache_expires_at': (timezone.now() + timezone.timedelta(minutes=5)).isoformat()
        }
        
        set_cached(cache_key, response_data, DASHBOARD_CACHE_TTL)
        return Response(response_data)


class ManagerDashboardView(AnalyticsAPIView):
    """
    GET /api/analytics/dashboards/manager/
    Manager dashboard with team scope.
    """
    throttle_classes = [AnalyticsDashboardThrottle]
    
    def get(self, request):
        serializer = DashboardQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        months = params.get('months', 6)
        
        # Check cache
        cache_key = build_dashboard_cache_key('manager', request.user.id, months=months)
        cached = get_cached(cache_key)
        if cached:
            return Response(cached)
        
        response_data = {
            'summary': ManagerDashboardService.get_summary(request.user),
            'team_trend': ManagerDashboardService.get_team_trend(request.user, months),
            'top_team_members': ManagerDashboardService.get_top_team_members(request.user),
            'computed_at': timezone.now().isoformat()
        }
        
        set_cached(cache_key, response_data, DASHBOARD_CACHE_TTL)
        return Response(response_data)


class ConsultantDashboardView(AnalyticsAPIView):
    """
    GET /api/analytics/dashboards/consultant/
    Consultant dashboard with own data only.
    """
    throttle_classes = [AnalyticsDashboardThrottle]
    
    def get(self, request):
        serializer = DashboardQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        months = params.get('months', 6)
        
        # Check cache
        cache_key = build_dashboard_cache_key('consultant', request.user.id, months=months)
        cached = get_cached(cache_key)
        if cached:
            return Response(cached)
        
        response_data = {
            'summary': ConsultantDashboardService.get_summary(request.user),
            'earnings_trend': ConsultantDashboardService.get_earnings_trend(request.user, months),
            'recent_payouts': ConsultantDashboardService.get_recent_payouts(request.user),
            'computed_at': timezone.now().isoformat()
        }
        
        set_cached(cache_key, response_data, DASHBOARD_CACHE_TTL)
        return Response(response_data)


# =============================================================================
# Analytics Endpoints (8) - Cached, 60/min throttle
# =============================================================================

class CommissionMetricsView(AnalyticsAPIView):
    """
    GET /api/analytics/commissions/metrics/
    Commission metrics with scope validation.
    """
    throttle_classes = [AnalyticsMetricsThrottle]
    
    def get(self, request):
        serializer = MetricsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        # Check cache
        cache_key = build_metrics_cache_key(
            'commission',
            user_id=request.user.id,
            **{k: str(v) for k, v in params.items() if v is not None}
        )
        cached = get_cached(cache_key)
        if cached:
            return Response(cached)
        
        results = CommissionMetricsService.get_metrics(
            user=request.user,
            window=params['window'],
            period_start=params['period_start'],
            period_end=params['period_end'],
            scope=params.get('scope'),
            scope_id=params.get('scope_id')
        )
        
        response_data = {'results': results, 'count': len(results)}
        set_cached(cache_key, response_data, DASHBOARD_CACHE_TTL)
        return Response(response_data)


class PayoutMetricsView(AnalyticsAPIView):
    """
    GET /api/analytics/payouts/metrics/
    Payout metrics with scope validation.
    """
    throttle_classes = [AnalyticsMetricsThrottle]
    
    def get(self, request):
        serializer = MetricsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        # Check cache
        cache_key = build_metrics_cache_key(
            'payout',
            user_id=request.user.id,
            **{k: str(v) for k, v in params.items() if v is not None}
        )
        cached = get_cached(cache_key)
        if cached:
            return Response(cached)
        
        results = PayoutMetricsService.get_metrics(
            user=request.user,
            window=params['window'],
            period_start=params['period_start'],
            period_end=params['period_end'],
            scope=params.get('scope'),
            scope_id=params.get('scope_id')
        )
        
        response_data = {'results': results, 'count': len(results)}
        set_cached(cache_key, response_data, DASHBOARD_CACHE_TTL)
        return Response(response_data)


class TaxMetricsView(AnalyticsAPIView):
    """
    GET /api/analytics/tax/metrics/
    Tax metrics with scope validation.
    """
    throttle_classes = [AnalyticsMetricsThrottle]
    
    def get(self, request):
        serializer = TaxMetricsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        # Check cache
        cache_key = build_metrics_cache_key(
            'tax',
            user_id=request.user.id,
            **{k: str(v) for k, v in params.items() if v is not None}
        )
        cached = get_cached(cache_key)
        if cached:
            return Response(cached)
        
        results = TaxMetricsService.get_metrics(
            user=request.user,
            window=params['window'],
            tax_year=params['tax_year'],
            quarter=params.get('quarter'),
            scope=params.get('scope'),
            scope_id=params.get('scope_id')
        )
        
        response_data = {'results': results, 'count': len(results)}
        set_cached(cache_key, response_data, DASHBOARD_CACHE_TTL)
        return Response(response_data)


class ReconciliationMetricsView(AnalyticsAPIView):
    """
    GET /api/analytics/reconciliation/metrics/
    Reconciliation metrics (Finance/Admin only).
    """
    throttle_classes = [AnalyticsMetricsThrottle]
    
    def get(self, request):
        serializer = ReconciliationMetricsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        # Check cache
        cache_key = build_metrics_cache_key(
            'reconciliation',
            **{k: str(v) for k, v in params.items() if v is not None}
        )
        cached = get_cached(cache_key)
        if cached:
            return Response(cached)
        
        results = ReconciliationMetricsService.get_metrics(
            user=request.user,
            window=params['window'],
            period_start=params['period_start'],
            period_end=params['period_end']
        )
        
        response_data = {'results': results, 'count': len(results)}
        set_cached(cache_key, response_data, DASHBOARD_CACHE_TTL)
        return Response(response_data)


class TopPerformersView(AnalyticsAPIView):
    """
    GET /api/analytics/commissions/top-performers/
    Top performing consultants.
    """
    throttle_classes = [AnalyticsMetricsThrottle]
    
    def get(self, request):
        serializer = TopPerformersQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        period = params.get('period', 'YTD')
        limit = params.get('limit', 10)
        
        # Determine scope
        if is_finance_or_admin(request.user):
            scope = 'global'
            scope_id = None
        elif is_manager(request.user):
            scope = 'manager'
            scope_id = request.user.id
        else:
            raise ForbiddenScopeError("Top performers is only accessible to Finance/Admin or Managers")
        
        # Check cache
        cache_key = build_top_performers_cache_key(scope, scope_id, period)
        cached = get_cached(cache_key)
        if cached:
            return Response(cached)
        
        # Get results
        if scope == 'global':
            results = FinanceDashboardService.get_top_performers(request.user, period=period, limit=limit)
        else:
            results = ManagerDashboardService.get_top_team_members(request.user, limit=limit)
        
        response_data = {'period': period, 'results': results}
        set_cached(cache_key, response_data, DASHBOARD_CACHE_TTL)
        return Response(response_data)


class CommissionTrendView(AnalyticsAPIView):
    """
    GET /api/analytics/commissions/trend/
    Commission trend over time.
    """
    throttle_classes = [AnalyticsMetricsThrottle]
    
    def get(self, request):
        serializer = TrendQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        months = params.get('months', 12)
        
        # Determine scope
        if is_finance_or_admin(request.user):
            scope = 'global'
            scope_id = None
        elif is_manager(request.user):
            scope = 'manager'
            scope_id = request.user.id
        else:
            scope = 'consultant'
            scope_id = request.user.id
        
        # Check cache
        cache_key = build_trend_cache_key('commission', scope, scope_id, months)
        cached = get_cached(cache_key)
        if cached:
            return Response(cached)
        
        # Get results
        if scope == 'global':
            results = FinanceDashboardService.get_commission_trend(request.user, months)
        elif scope == 'manager':
            results = ManagerDashboardService.get_team_trend(request.user, months)
        else:
            results = ConsultantDashboardService.get_earnings_trend(request.user, months)
        
        response_data = {'results': results}
        set_cached(cache_key, response_data, DASHBOARD_CACHE_TTL)
        return Response(response_data)


class PayoutTrendView(AnalyticsAPIView):
    """
    GET /api/analytics/payouts/trend/
    Payout trend over time.
    """
    throttle_classes = [AnalyticsMetricsThrottle]
    
    def get(self, request):
        serializer = TrendQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        months = params.get('months', 12)
        
        # Determine scope
        if is_finance_or_admin(request.user):
            scope = 'global'
            scope_id = None
        elif is_manager(request.user):
            scope = 'manager'
            scope_id = request.user.id
        else:
            scope = 'consultant'
            scope_id = request.user.id
        
        # Check cache
        cache_key = build_trend_cache_key('payout', scope, scope_id, months)
        cached = get_cached(cache_key)
        if cached:
            return Response(cached)
        
        # Use payout summary data
        from .models import PayoutSummary, WindowType, ScopeType
        from datetime import timedelta
        
        end_date = timezone.now().date().replace(day=1)
        start_date = end_date - timedelta(days=30 * months)
        
        if scope == 'global':
            scope_type = ScopeType.GLOBAL
            scope_user = None
        elif scope == 'manager':
            scope_type = ScopeType.MANAGER
            scope_user = request.user
        else:
            scope_type = ScopeType.CONSULTANT
            scope_user = request.user
        
        filters = {
            'window': WindowType.MONTHLY,
            'scope': scope_type,
            'period_start__gte': start_date,
            'period_start__lt': end_date
        }
        if scope_user:
            filters['scope_id'] = scope_user
        else:
            filters['scope_id__isnull'] = True
        
        summaries = PayoutSummary.objects.filter(**filters).order_by('-period_start')[:months]
        
        results = [
            {
                'month': s.period_start.strftime('%Y-%m'),
                'total': str(s.paid_amount),
                'count': s.payout_count
            }
            for s in summaries
        ]
        
        response_data = {'results': results}
        set_cached(cache_key, response_data, DASHBOARD_CACHE_TTL)
        return Response(response_data)


class PendingCountView(AnalyticsAPIView):
    """
    GET /api/analytics/commissions/pending-count/
    Real-time pending approvals count (Manager only).
    No caching - real-time.
    """
    throttle_classes = [AnalyticsMetricsThrottle]
    
    def get(self, request):
        if not is_manager(request.user):
            raise ForbiddenScopeError("Pending count is only accessible to Managers")
        
        team_ids = get_team_member_ids(request.user)
        
        pending = Commission.objects.filter(
            consultant_id__in=team_ids,
            status='SUBMITTED'
        ).aggregate(
            count=Count('id'),
            amount=Coalesce(Sum('amount'), Decimal('0'))
        )
        
        return Response({
            'pending_count': pending['count'],
            'pending_amount': str(pending['amount']),
            'as_of': timezone.now().isoformat()
        })


# =============================================================================
# Report/Export Endpoints (6) - No caching, 10/min throttle
# =============================================================================

class CommissionDetailExportView(AnalyticsAPIView):
    """
    GET /api/analytics/reports/commission-detail/
    Export commission detail report.
    """
    throttle_classes = [AnalyticsExportThrottle]
    
    def get(self, request):
        serializer = ExportQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        content, filename, row_count = CommissionDetailExportService.export(
            user=request.user,
            start_date=params['start_date'],
            end_date=params['end_date'],
            format=params.get('format', 'csv'),
            status=params.get('status'),
            ip_address=get_client_ip(request)
        )
        
        response = HttpResponse(content, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class PayoutHistoryExportView(AnalyticsAPIView):
    """
    GET /api/analytics/reports/payout-history/
    Export payout history report.
    """
    throttle_classes = [AnalyticsExportThrottle]
    
    def get(self, request):
        serializer = ExportQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        content, filename, row_count = PayoutHistoryExportService.export(
            user=request.user,
            start_date=params['start_date'],
            end_date=params['end_date'],
            format=params.get('format', 'csv'),
            ip_address=get_client_ip(request)
        )
        
        response = HttpResponse(content, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class TaxYearSummaryExportView(AnalyticsAPIView):
    """
    GET /api/analytics/reports/tax-year-summary/{year}/
    Export tax year summary (Finance/Admin only).
    """
    throttle_classes = [AnalyticsExportThrottle]
    
    def get(self, request, year):
        if not is_finance_or_admin(request.user):
            raise ForbiddenScopeError("Tax year summary is only accessible to Finance/Admin")
        
        serializer = TaxExportQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        content, filename, row_count = TaxYearSummaryExportService.export(
            user=request.user,
            tax_year=year,
            format=params.get('format', 'csv'),
            ip_address=get_client_ip(request)
        )
        
        response = HttpResponse(content, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class ReconciliationExportView(AnalyticsAPIView):
    """
    GET /api/analytics/reports/reconciliation/
    Export reconciliation report (Finance/Admin only).
    """
    throttle_classes = [AnalyticsExportThrottle]
    
    def get(self, request):
        if not is_finance_or_admin(request.user):
            raise ForbiddenScopeError("Reconciliation report is only accessible to Finance/Admin")
        
        serializer = ExportQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        from .models import ReconciliationSummary
        
        summaries = ReconciliationSummary.objects.filter(
            period_start__gte=params['start_date'],
            period_end__lte=params['end_date']
        ).order_by('-period_start')
        
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Period Start', 'Period End', 'Window', 'Total Batches', 'Matched', 'Pending', 'Discrepancy', 'Total Discrepancy'])
        for s in summaries:
            writer.writerow([
                s.period_start.isoformat(),
                s.period_end.isoformat(),
                s.window,
                s.total_batches,
                s.matched_count,
                s.pending_count,
                s.discrepancy_count,
                str(s.total_discrepancy)
            ])
        
        content = output.getvalue()
        filename = f"reconciliation_report_{params['start_date']}_{params['end_date']}.csv"
        
        response = HttpResponse(content, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class MyEarningsExportView(AnalyticsAPIView):
    """
    GET /api/analytics/reports/my-earnings/
    Export personal earnings report.
    """
    throttle_classes = [AnalyticsExportThrottle]
    
    def get(self, request):
        serializer = ExportQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        content, filename, row_count = MyEarningsExportService.export(
            user=request.user,
            start_date=params['start_date'],
            end_date=params['end_date'],
            format=params.get('format', 'csv'),
            ip_address=get_client_ip(request)
        )
        
        response = HttpResponse(content, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class ExportLogView(AnalyticsAPIView):
    """
    GET /api/analytics/exports/
    List export history.
    """
    throttle_classes = [AnalyticsMetricsThrottle]
    
    def get(self, request):
        limit = int(request.query_params.get('limit', 50))
        if limit > 100:
            limit = 100
        
        results = ExportLogService.get_exports(request.user, limit)
        
        return Response({'results': results, 'count': len(results)})
