"""
Analytics Services Layer
All business logic for dashboards, metrics, and exports.
Read-only access to Phase 4/5 data. Write-only to analytics tables.
"""
import csv
import io
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, List

from django.db.models import Sum, Count, Avg, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.contrib.auth import get_user_model

from commissions.models import Commission
from payouts.models import PayoutBatch, Payout
from payments.models import W9Information, TaxDocument, PaymentTransaction
from hierarchy.models import ReportingLine

from .models import (
    CommissionMetric, PayoutSummary, TaxSummary,
    ReconciliationSummary, ExportLog,
    WindowType, ScopeType, ReportType, ExportFormat, ExportStatus
)
from .exceptions import (
    ForbiddenScopeError, ValidationError, ExportLimitExceededError
)

logger = logging.getLogger(__name__)
User = get_user_model()

MAX_EXPORT_ROWS = 10000


# =============================================================================
# Cache Key Builders
# =============================================================================

def build_dashboard_cache_key(dashboard_type: str, user_id: int, **params) -> str:
    """Build deterministic cache key for dashboard data."""
    params_str = '_'.join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"analytics:dashboard:{dashboard_type}:{user_id}:{params_str}"


def build_metrics_cache_key(model: str, **params) -> str:
    """Build deterministic cache key for metrics queries."""
    params_str = '_'.join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"analytics:metrics:{model}:{params_str}"


# =============================================================================
# Role Checking Helpers
# =============================================================================

def is_finance_or_admin(user) -> bool:
    """Check if user has finance or admin role."""
    return user.is_staff or user.is_superuser or getattr(user, 'role', None) in ['FINANCE', 'ADMIN']


def is_manager(user) -> bool:
    """Check if user is a manager (has direct reports)."""
    return ReportingLine.objects.filter(manager=user).exists()


def get_team_member_ids(manager) -> List[int]:
    """Get IDs of all team members for a manager."""
    return list(ReportingLine.objects.filter(manager=manager).values_list('consultant_id', flat=True))


# =============================================================================
# Dashboard Services
# =============================================================================

class FinanceDashboardService:
    """
    Dashboard service for Finance/Admin users.
    Full access to all data.
    """
    
    @staticmethod
    def get_summary(user, year: int = None) -> Dict[str, Any]:
        """Get summary KPIs for finance dashboard."""
        if not is_finance_or_admin(user):
            raise ForbiddenScopeError(
                "Finance dashboard is only accessible to Finance/Admin users",
                required_role='finance_admin',
                current_role='consultant'
            )
        
        year = year or timezone.now().year
        year_start = date(year, 1, 1)
        today = timezone.now().date()
        
        # Get YTD paid amount from PayoutSummary
        paid_ytd = PayoutSummary.objects.filter(
            window=WindowType.MONTHLY,
            scope=ScopeType.GLOBAL,
            period_start__gte=year_start,
            period_start__lte=today
        ).aggregate(total=Coalesce(Sum('paid_amount'), Decimal('0')))['total']
        
        # Outstanding liability (approved but unpaid commissions) - real-time
        outstanding = Commission.objects.filter(
            state='approved'
        ).aggregate(total=Coalesce(Sum('calculated_amount'), Decimal('0')))['total']
        
        # Payment success rate
        latest_summary = PayoutSummary.objects.filter(
            window=WindowType.MONTHLY,
            scope=ScopeType.GLOBAL
        ).order_by('-period_start').first()
        success_rate = latest_summary.success_rate if latest_summary else Decimal('0')
        
        # Average cycle days
        avg_cycle = latest_summary.avg_cycle_days if latest_summary else Decimal('0')
        
        return {
            'total_paid_ytd': str(paid_ytd),
            'outstanding_liability': str(outstanding),
            'payment_success_rate': str(success_rate),
            'avg_cycle_days': str(avg_cycle)
        }
    
    @staticmethod
    def get_commission_trend(user, months: int = 12) -> List[Dict]:
        """Get commission trend for last N months."""
        if not is_finance_or_admin(user):
            raise ForbiddenScopeError()
        
        end_date = timezone.now().date().replace(day=1)
        start_date = end_date - timedelta(days=30 * months)
        
        metrics = CommissionMetric.objects.filter(
            window=WindowType.MONTHLY,
            scope=ScopeType.GLOBAL,
            period_start__gte=start_date,
            period_start__lt=end_date
        ).order_by('-period_start')[:months]
        
        return [
            {
                'month': m.period_start.strftime('%Y-%m'),
                'total': str(m.total_amount),
                'count': m.total_count
            }
            for m in metrics
        ]
    
    @staticmethod
    def get_top_performers(user, period: str = 'YTD', limit: int = 10) -> List[Dict]:
        """Get top performing consultants."""
        if not is_finance_or_admin(user):
            raise ForbiddenScopeError()
        
        if limit > 50:
            limit = 50
        
        year = timezone.now().year
        if period == 'YTD':
            start_date = date(year, 1, 1)
        elif period == 'MONTH':
            start_date = timezone.now().date().replace(day=1)
        elif period == 'QUARTER':
            month = timezone.now().month
            quarter_start_month = ((month - 1) // 3) * 3 + 1
            start_date = date(year, quarter_start_month, 1)
        else:
            start_date = date(year, 1, 1)
        
        # Aggregate from CommissionMetric per consultant
        top = CommissionMetric.objects.filter(
            window=WindowType.MONTHLY,
            scope=ScopeType.CONSULTANT,
            period_start__gte=start_date
        ).values('scope_id').annotate(
            total=Sum('approved_amount')
        ).order_by('-total')[:limit]
        
        results = []
        for i, item in enumerate(top, 1):
            user_obj = User.objects.filter(id=item['scope_id']).first()
            name = f"{user_obj.first_name} {user_obj.last_name[:1]}." if user_obj else "Unknown"
            results.append({
                'rank': i,
                'consultant_id': item['scope_id'],
                'name': name,
                'total': str(item['total'] or Decimal('0'))
            })
        
        return results
    
    @staticmethod
    def get_reconciliation_status(user) -> Dict[str, int]:
        """Get reconciliation status counts."""
        if not is_finance_or_admin(user):
            raise ForbiddenScopeError()
        
        latest = ReconciliationSummary.objects.filter(
            window=WindowType.MONTHLY
        ).order_by('-period_start').first()
        
        if latest:
            return {
                'matched': latest.matched_count,
                'pending': latest.pending_count,
                'discrepancy': latest.discrepancy_count
            }
        return {'matched': 0, 'pending': 0, 'discrepancy': 0}


class ManagerDashboardService:
    """
    Dashboard service for Manager users.
    Access limited to their team data.
    """
    
    @staticmethod
    def get_summary(user) -> Dict[str, Any]:
        """Get summary KPIs for manager dashboard."""
        if not is_manager(user):
            raise ForbiddenScopeError(
                "Manager dashboard is only accessible to users with direct reports",
                required_role='manager',
                current_role='consultant'
            )
        
        team_ids = get_team_member_ids(user)
        year = timezone.now().year
        year_start = date(year, 1, 1)
        
        # Team total YTD
        team_total = PayoutSummary.objects.filter(
            window=WindowType.MONTHLY,
            scope=ScopeType.MANAGER,
            scope_id=user,
            period_start__gte=year_start
        ).aggregate(total=Coalesce(Sum('paid_amount'), Decimal('0')))['total']
        
        # Pending approvals (real-time from commissions)
        pending_approvals = Commission.objects.filter(
            consultant_id__in=team_ids,
            state='submitted'
        ).count()
        
        return {
            'team_total_ytd': str(team_total),
            'team_size': len(team_ids),
            'pending_approvals': pending_approvals
        }
    
    @staticmethod
    def get_team_trend(user, months: int = 6) -> List[Dict]:
        """Get team commission trend."""
        if not is_manager(user):
            raise ForbiddenScopeError()
        
        end_date = timezone.now().date().replace(day=1)
        start_date = end_date - timedelta(days=30 * months)
        
        metrics = CommissionMetric.objects.filter(
            window=WindowType.MONTHLY,
            scope=ScopeType.MANAGER,
            scope_id=user,
            period_start__gte=start_date,
            period_start__lt=end_date
        ).order_by('-period_start')[:months]
        
        return [
            {
                'month': m.period_start.strftime('%Y-%m'),
                'total': str(m.total_amount),
                'count': m.total_count
            }
            for m in metrics
        ]
    
    @staticmethod
    def get_top_team_members(user, limit: int = 10) -> List[Dict]:
        """Get top performing team members."""
        if not is_manager(user):
            raise ForbiddenScopeError()
        
        team_ids = get_team_member_ids(user)
        year = timezone.now().year
        year_start = date(year, 1, 1)
        
        top = CommissionMetric.objects.filter(
            window=WindowType.MONTHLY,
            scope=ScopeType.CONSULTANT,
            scope_id__in=team_ids,
            period_start__gte=year_start
        ).values('scope_id').annotate(
            total=Sum('approved_amount')
        ).order_by('-total')[:limit]
        
        results = []
        for i, item in enumerate(top, 1):
            user_obj = User.objects.filter(id=item['scope_id']).first()
            name = f"{user_obj.first_name} {user_obj.last_name[:1]}." if user_obj else "Unknown"
            results.append({
                'rank': i,
                'consultant_id': item['scope_id'],
                'name': name,
                'total': str(item['total'] or Decimal('0'))
            })
        
        return results


class ConsultantDashboardService:
    """
    Dashboard service for Consultant users.
    Access limited to their own data.
    """
    
    @staticmethod
    def get_summary(user) -> Dict[str, Any]:
        """Get summary KPIs for consultant dashboard."""
        year = timezone.now().year
        year_start = date(year, 1, 1)
        
        # Total paid YTD
        paid_ytd = PayoutSummary.objects.filter(
            window=WindowType.MONTHLY,
            scope=ScopeType.CONSULTANT,
            scope_id=user,
            period_start__gte=year_start
        ).aggregate(total=Coalesce(Sum('paid_amount'), Decimal('0')))['total']
        
        # Pending amount (real-time)
        pending = Commission.objects.filter(
            consultant=user,
            state__in=['submitted', 'approved']
        ).aggregate(total=Coalesce(Sum('calculated_amount'), Decimal('0')))['total']
        
        # W-9 status
        w9 = W9Information.objects.filter(consultant=user).first()
        w9_status = w9.status if w9 else 'NOT_SUBMITTED'
        
        # Tax docs count
        tax_docs = TaxDocument.objects.filter(consultant=user).count()
        
        return {
            'total_paid_ytd': str(paid_ytd),
            'pending_amount': str(pending),
            'w9_status': w9_status,
            'tax_docs_count': tax_docs
        }
    
    @staticmethod
    def get_earnings_trend(user, months: int = 6) -> List[Dict]:
        """Get personal earnings trend."""
        end_date = timezone.now().date().replace(day=1)
        start_date = end_date - timedelta(days=30 * months)
        
        metrics = CommissionMetric.objects.filter(
            window=WindowType.MONTHLY,
            scope=ScopeType.CONSULTANT,
            scope_id=user,
            period_start__gte=start_date,
            period_start__lt=end_date
        ).order_by('-period_start')[:months]
        
        return [
            {
                'month': m.period_start.strftime('%Y-%m'),
                'total': str(m.approved_amount)
            }
            for m in metrics
        ]
    
    @staticmethod
    def get_recent_payouts(user, limit: int = 10) -> List[Dict]:
        """Get recent payouts for the consultant."""
        payouts = Payout.objects.filter(
            consultant=user
        ).select_related('batch').order_by('-batch__run_date')[:limit]
        
        return [
            {
                'date': p.batch.run_date.isoformat() if p.batch else None,
                'amount': str(p.total_commission),
                'status': p.status
            }
            for p in payouts
        ]


# =============================================================================
# Metrics Query Services
# =============================================================================

class CommissionMetricsService:
    """Query service for commission metrics."""
    
    @staticmethod
    def get_metrics(
        user,
        window: str,
        period_start: date,
        period_end: date,
        scope: str = None,
        scope_id: int = None
    ) -> List[Dict]:
        """Get commission metrics with scope validation."""
        # Validate window
        if window not in [WindowType.DAILY, WindowType.MONTHLY]:
            raise ValidationError("Invalid window. Must be DAILY or MONTHLY.", field='window')
        
        # Validate and enforce scope based on role
        scope, scope_id = CommissionMetricsService._validate_scope(user, scope, scope_id)
        
        # Query
        filters = {
            'window': window,
            'period_start__gte': period_start,
            'period_end__lte': period_end,
            'scope': scope
        }
        if scope_id:
            filters['scope_id'] = scope_id
        else:
            filters['scope_id__isnull'] = True
        
        metrics = CommissionMetric.objects.filter(**filters).order_by('-period_start')
        
        return [
            {
                'window': m.window,
                'period_start': m.period_start.isoformat(),
                'period_end': m.period_end.isoformat(),
                'scope': m.scope,
                'total_count': m.total_count,
                'total_amount': str(m.total_amount),
                'approved_count': m.approved_count,
                'approved_amount': str(m.approved_amount),
                'average_amount': str(m.average_amount)
            }
            for m in metrics
        ]
    
    @staticmethod
    def _validate_scope(user, scope: str, scope_id: int):
        """Validate and enforce scope based on user role."""
        if is_finance_or_admin(user):
            # Finance/Admin can access any scope
            return scope or ScopeType.GLOBAL, scope_id
        
        if is_manager(user):
            # Manager can access their team or own data
            if scope == ScopeType.GLOBAL:
                raise ForbiddenScopeError(
                    "You do not have permission to access global metrics",
                    required_role='finance_admin',
                    current_role='manager'
                )
            if scope == ScopeType.MANAGER:
                return ScopeType.MANAGER, user.id
            if scope == ScopeType.CONSULTANT:
                # Must be team member
                team_ids = get_team_member_ids(user)
                if scope_id not in team_ids and scope_id != user.id:
                    raise ForbiddenScopeError("You can only access your team's data")
                return ScopeType.CONSULTANT, scope_id
            return ScopeType.MANAGER, user.id
        
        # Consultant can only access own data
        if scope and scope != ScopeType.CONSULTANT:
            raise ForbiddenScopeError(
                "You can only access your own data",
                required_role='finance_admin',
                current_role='consultant'
            )
        return ScopeType.CONSULTANT, user.id


class PayoutMetricsService:
    """Query service for payout metrics."""
    
    @staticmethod
    def get_metrics(
        user,
        window: str,
        period_start: date,
        period_end: date,
        scope: str = None,
        scope_id: int = None
    ) -> List[Dict]:
        """Get payout metrics with scope validation."""
        if window not in [WindowType.DAILY, WindowType.MONTHLY]:
            raise ValidationError("Invalid window. Must be DAILY or MONTHLY.", field='window')
        
        scope, scope_id = CommissionMetricsService._validate_scope(user, scope, scope_id)
        
        filters = {
            'window': window,
            'period_start__gte': period_start,
            'period_end__lte': period_end,
            'scope': scope
        }
        if scope_id:
            filters['scope_id'] = scope_id
        else:
            filters['scope_id__isnull'] = True
        
        metrics = PayoutSummary.objects.filter(**filters).order_by('-period_start')
        
        return [
            {
                'window': m.window,
                'period_start': m.period_start.isoformat(),
                'period_end': m.period_end.isoformat(),
                'scope': m.scope,
                'batch_count': m.batch_count,
                'payout_count': m.payout_count,
                'total_amount': str(m.total_amount),
                'paid_amount': str(m.paid_amount),
                'avg_cycle_days': str(m.avg_cycle_days),
                'success_rate': str(m.success_rate)
            }
            for m in metrics
        ]


class TaxMetricsService:
    """Query service for tax metrics."""
    
    @staticmethod
    def get_metrics(
        user,
        window: str,
        tax_year: int,
        quarter: int = None,
        scope: str = None,
        scope_id: int = None
    ) -> List[Dict]:
        """Get tax metrics with scope validation."""
        if window not in [WindowType.QUARTERLY, WindowType.ANNUAL]:
            raise ValidationError("Invalid window. Must be QUARTERLY or ANNUAL.", field='window')
        
        if window == WindowType.QUARTERLY and quarter is None:
            raise ValidationError("Quarter is required for QUARTERLY window.", field='quarter')
        
        # Only Finance/Admin or own data
        if is_finance_or_admin(user):
            scope = scope or ScopeType.GLOBAL
        else:
            if scope == ScopeType.GLOBAL:
                raise ForbiddenScopeError()
            scope = ScopeType.CONSULTANT
            scope_id = user.id
        
        filters = {
            'window': window,
            'tax_year': tax_year,
            'scope': scope
        }
        if quarter:
            filters['quarter'] = quarter
        if scope_id:
            filters['scope_id'] = scope_id
        else:
            filters['scope_id__isnull'] = True
        
        metrics = TaxSummary.objects.filter(**filters)
        
        return [
            {
                'window': m.window,
                'tax_year': m.tax_year,
                'quarter': m.quarter,
                'scope': m.scope,
                'total_payments': str(m.total_payments),
                'consultant_count': m.consultant_count,
                'above_threshold_count': m.above_threshold_count,
                'w9_approved_count': m.w9_approved_count,
                'forms_generated_count': m.forms_generated_count,
                'forms_filed_count': m.forms_filed_count
            }
            for m in metrics
        ]


class ReconciliationMetricsService:
    """Query service for reconciliation metrics. Finance/Admin only."""
    
    @staticmethod
    def get_metrics(
        user,
        window: str,
        period_start: date,
        period_end: date
    ) -> List[Dict]:
        """Get reconciliation metrics. Finance/Admin only."""
        if not is_finance_or_admin(user):
            raise ForbiddenScopeError()
        
        if window not in [WindowType.DAILY, WindowType.MONTHLY]:
            raise ValidationError("Invalid window. Must be DAILY or MONTHLY.", field='window')
        
        metrics = ReconciliationSummary.objects.filter(
            window=window,
            period_start__gte=period_start,
            period_end__lte=period_end
        ).order_by('-period_start')
        
        return [
            {
                'window': m.window,
                'period_start': m.period_start.isoformat(),
                'period_end': m.period_end.isoformat(),
                'total_batches': m.total_batches,
                'matched_count': m.matched_count,
                'pending_count': m.pending_count,
                'discrepancy_count': m.discrepancy_count,
                'total_discrepancy': str(m.total_discrepancy)
            }
            for m in metrics
        ]


# =============================================================================
# Export Services
# =============================================================================

class BaseExportService:
    """Base class for export services."""
    
    report_type: ReportType = None
    
    @classmethod
    def _create_export_log(cls, user, filters: dict, ip_address: str = None) -> ExportLog:
        """Create an export log entry."""
        return ExportLog.objects.create(
            user=user,
            report_type=cls.report_type,
            export_format=filters.get('format', ExportFormat.CSV),
            filters=filters,
            ip_address=ip_address,
            status=ExportStatus.PENDING
        )
    
    @classmethod
    def _check_row_limit(cls, count: int):
        """Check if export exceeds row limit."""
        if count > MAX_EXPORT_ROWS:
            raise ExportLimitExceededError(MAX_EXPORT_ROWS, count)
    
    @classmethod
    def _generate_csv(cls, headers: List[str], rows: List[List]) -> str:
        """Generate CSV content."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)
        return output.getvalue()


class CommissionDetailExportService(BaseExportService):
    """Export service for commission detail reports."""
    
    report_type = ReportType.COMMISSION_DETAIL
    
    @classmethod
    def export(
        cls,
        user,
        start_date: date,
        end_date: date,
        format: str = 'csv',
        status: str = None,
        ip_address: str = None
    ) -> tuple:
        """Export commission detail report."""
        filters = {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'format': format,
            'status': status
        }
        export_log = cls._create_export_log(user, filters, ip_address)
        
        try:
            # Build query based on role
            query = Q(created_at__date__gte=start_date, created_at__date__lte=end_date)
            
            if not is_finance_or_admin(user):
                if is_manager(user):
                    team_ids = get_team_member_ids(user)
                    query &= Q(consultant_id__in=team_ids)
                else:
                    query &= Q(consultant=user)
            
            if status:
                query &= Q(state=status)
            
            # Check count
            count = Commission.objects.filter(query).count()
            cls._check_row_limit(count)
            
            # Get data
            commissions = Commission.objects.filter(query).select_related('consultant').order_by('-created_at')
            
            headers = ['ID', 'Date', 'Consultant', 'Amount', 'Type', 'Status', 'Description']
            rows = [
                [
                    c.id,
                    c.created_at.date().isoformat(),
                    f"{c.consultant.first_name} {c.consultant.last_name[:1]}.",
                    str(c.calculated_amount),
                    c.commission_type,
                    c.state,
                    c.notes[:50] if c.notes else ''
                ]
                for c in commissions
            ]
            
            content = cls._generate_csv(headers, rows)
            
            # Update export log
            export_log.mark_completed(len(rows), len(content.encode('utf-8')))
            
            return content, f"commission_report_{start_date}_{end_date}.csv", len(rows)
            
        except Exception as e:
            export_log.mark_failed(str(e))
            raise


class PayoutHistoryExportService(BaseExportService):
    """Export service for payout history reports."""
    
    report_type = ReportType.PAYOUT_HISTORY
    
    @classmethod
    def export(
        cls,
        user,
        start_date: date,
        end_date: date,
        format: str = 'csv',
        ip_address: str = None
    ) -> tuple:
        """Export payout history report."""
        filters = {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'format': format
        }
        export_log = cls._create_export_log(user, filters, ip_address)
        
        try:
            query = Q(batch__run_date__gte=start_date, batch__run_date__lte=end_date)
            
            if not is_finance_or_admin(user):
                if is_manager(user):
                    team_ids = get_team_member_ids(user)
                    query &= Q(consultant_id__in=team_ids)
                else:
                    query &= Q(consultant=user)
            
            count = Payout.objects.filter(query).count()
            cls._check_row_limit(count)
            
            payouts = Payout.objects.filter(query).select_related('consultant', 'batch').order_by('-batch__run_date')
            
            headers = ['ID', 'Date', 'Consultant', 'Amount', 'Status', 'Batch ID']
            rows = [
                [
                    p.id,
                    p.batch.run_date.isoformat() if p.batch else '',
                    f"{p.consultant.first_name} {p.consultant.last_name[:1]}.",
                    str(p.total_commission),
                    p.status,
                    p.batch.id if p.batch else ''
                ]
                for p in payouts
            ]
            
            content = cls._generate_csv(headers, rows)
            export_log.mark_completed(len(rows), len(content.encode('utf-8')))
            
            return content, f"payout_report_{start_date}_{end_date}.csv", len(rows)
            
        except Exception as e:
            export_log.mark_failed(str(e))
            raise


class TaxYearSummaryExportService(BaseExportService):
    """Export service for tax year summary. Finance/Admin only."""
    
    report_type = ReportType.TAX_SUMMARY
    
    @classmethod
    def export(
        cls,
        user,
        tax_year: int,
        format: str = 'csv',
        ip_address: str = None
    ) -> tuple:
        """Export tax year summary report."""
        if not is_finance_or_admin(user):
            raise ForbiddenScopeError()
        
        filters = {'tax_year': tax_year, 'format': format}
        export_log = cls._create_export_log(user, filters, ip_address)
        
        try:
            summaries = TaxSummary.objects.filter(
                window=WindowType.ANNUAL,
                tax_year=tax_year,
                scope=ScopeType.CONSULTANT
            ).select_related('scope_id')
            
            headers = ['Consultant ID', 'Name', 'Total Payments', 'Above Threshold', 'W-9 Status', '1099 Generated']
            rows = [
                [
                    s.scope_id.id if s.scope_id else '',
                    f"{s.scope_id.first_name} {s.scope_id.last_name}" if s.scope_id else 'Unknown',
                    str(s.total_payments),
                    'Yes' if s.above_threshold_count > 0 else 'No',
                    'Approved' if s.w9_approved_count > 0 else 'Pending',
                    'Yes' if s.forms_generated_count > 0 else 'No'
                ]
                for s in summaries
            ]
            
            content = cls._generate_csv(headers, rows)
            export_log.mark_completed(len(rows), len(content.encode('utf-8')))
            
            return content, f"tax_summary_{tax_year}.csv", len(rows)
            
        except Exception as e:
            export_log.mark_failed(str(e))
            raise


class MyEarningsExportService(BaseExportService):
    """Export service for personal earnings. Consultant only."""
    
    report_type = ReportType.MY_EARNINGS
    
    @classmethod
    def export(
        cls,
        user,
        start_date: date,
        end_date: date,
        format: str = 'csv',
        ip_address: str = None
    ) -> tuple:
        """Export personal earnings report."""
        filters = {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'format': format
        }
        export_log = cls._create_export_log(user, filters, ip_address)
        
        try:
            # Only own data
            commissions = Commission.objects.filter(
                consultant=user,
                created_at__date__gte=start_date,
                created_at__date__lte=end_date
            ).order_by('-created_at')
            
            count = commissions.count()
            cls._check_row_limit(count)
            
            headers = ['Date', 'Amount', 'Type', 'Status', 'Description']
            rows = [
                [
                    c.created_at.date().isoformat(),
                    str(c.calculated_amount),
                    c.commission_type,
                    c.state,
                    c.notes[:50] if c.notes else ''
                ]
                for c in commissions
            ]
            
            content = cls._generate_csv(headers, rows)
            export_log.mark_completed(len(rows), len(content.encode('utf-8')))
            
            return content, f"my_earnings_{start_date}_{end_date}.csv", len(rows)
            
        except Exception as e:
            export_log.mark_failed(str(e))
            raise


class ExportLogService:
    """Service for querying export logs."""
    
    @staticmethod
    def get_exports(user, limit: int = 50) -> List[Dict]:
        """Get export history for user."""
        if is_finance_or_admin(user):
            exports = ExportLog.objects.all()
        else:
            exports = ExportLog.objects.filter(user=user)
        
        exports = exports.order_by('-created_at')[:limit]
        
        return [
            {
                'id': e.id,
                'report_type': e.report_type,
                'export_format': e.export_format,
                'row_count': e.row_count,
                'status': e.status,
                'started_at': e.started_at.isoformat(),
                'completed_at': e.completed_at.isoformat() if e.completed_at else None
            }
            for e in exports
        ]
