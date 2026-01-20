"""
Analytics Aggregation Engine
Computes daily, monthly, quarterly, and annual metrics from Phase 4/5 data.
All operations are read-only against source tables and write-only to analytics tables.
"""
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, List, Tuple

from django.db import transaction, IntegrityError
from django.db.models import Count, Sum, Avg, Q, F
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.contrib.auth import get_user_model

from commissions.models import Commission
from payouts.models import PayoutBatch, Payout, PayoutPeriod
from payments.models import PaymentTransaction, PaymentReconciliation, W9Information, TaxDocument
from hierarchy.models import ReportingLine

from .models import (
    CommissionMetric, PayoutSummary, TaxSummary, 
    ReconciliationSummary, ExportLog,
    WindowType, ScopeType
)

logger = logging.getLogger(__name__)
User = get_user_model()


class AggregationResult:
    """Container for aggregation job results."""
    def __init__(self):
        self.created = 0
        self.skipped = 0
        self.errors = []
    
    def add_created(self, count: int = 1):
        self.created += count
    
    def add_skipped(self, count: int = 1):
        self.skipped += count
    
    def add_error(self, error: str):
        self.errors.append(error)
    
    def __str__(self):
        return f"Created: {self.created}, Skipped: {self.skipped}, Errors: {len(self.errors)}"


class AggregationEngine:
    """
    Main aggregation engine for analytics.
    Reads from Phase 4/5 tables and writes to analytics tables.
    All writes are insert-only (append-only enforcement).
    """
    
    def __init__(self, target_date: Optional[date] = None):
        """
        Initialize the aggregation engine.
        
        Args:
            target_date: The date to compute metrics for. Defaults to yesterday.
        """
        self.target_date = target_date or (timezone.now().date() - timedelta(days=1))
        self.computed_at = timezone.now()
        self.results = {}
    
    def run_daily_aggregation(self) -> Dict[str, AggregationResult]:
        """
        Run the daily aggregation job.
        Computes daily metrics for all models and scopes.
        """
        logger.info(f"Starting daily aggregation for {self.target_date}")
        start_time = timezone.now()
        
        # Commission Metrics (DAILY)
        self.results['commission_metrics'] = self._aggregate_commission_metrics_daily()
        
        # Payout Summaries (DAILY)
        self.results['payout_summaries'] = self._aggregate_payout_summaries_daily()
        
        # Reconciliation Summaries (DAILY)
        self.results['reconciliation_summaries'] = self._aggregate_reconciliation_summaries_daily()
        
        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.info(f"Daily aggregation completed in {duration:.2f}s")
        for model, result in self.results.items():
            logger.info(f"  {model}: {result}")
        
        return self.results
    
    def run_monthly_rollup(self) -> Dict[str, AggregationResult]:
        """
        Run monthly rollup. Should be called on the 1st of each month.
        Aggregates the previous month's data.
        """
        # Calculate previous month
        first_of_current = self.target_date.replace(day=1)
        last_of_previous = first_of_current - timedelta(days=1)
        first_of_previous = last_of_previous.replace(day=1)
        
        logger.info(f"Starting monthly rollup for {first_of_previous} to {last_of_previous}")
        
        self.results['commission_metrics_monthly'] = self._aggregate_commission_metrics_monthly(
            first_of_previous, last_of_previous
        )
        self.results['payout_summaries_monthly'] = self._aggregate_payout_summaries_monthly(
            first_of_previous, last_of_previous
        )
        self.results['reconciliation_summaries_monthly'] = self._aggregate_reconciliation_summaries_monthly(
            first_of_previous, last_of_previous
        )
        
        return self.results
    
    def run_quarterly_rollup(self) -> Dict[str, AggregationResult]:
        """
        Run quarterly rollup. Should be called on the 1st day of each quarter.
        """
        # Calculate previous quarter
        year = self.target_date.year
        month = self.target_date.month
        
        if month in [1, 2, 3]:
            quarter = 4
            year -= 1
            period_start = date(year, 10, 1)
            period_end = date(year, 12, 31)
        elif month in [4, 5, 6]:
            quarter = 1
            period_start = date(year, 1, 1)
            period_end = date(year, 3, 31)
        elif month in [7, 8, 9]:
            quarter = 2
            period_start = date(year, 4, 1)
            period_end = date(year, 6, 30)
        else:
            quarter = 3
            period_start = date(year, 7, 1)
            period_end = date(year, 9, 30)
        
        logger.info(f"Starting quarterly rollup for Q{quarter} {year}")
        
        self.results['tax_summaries_quarterly'] = self._aggregate_tax_summaries(
            WindowType.QUARTERLY, year, quarter, period_start, period_end
        )
        
        return self.results
    
    def run_annual_rollup(self) -> Dict[str, AggregationResult]:
        """
        Run annual rollup. Should be called on Jan 1st.
        Aggregates the previous year's data.
        """
        previous_year = self.target_date.year - 1
        period_start = date(previous_year, 1, 1)
        period_end = date(previous_year, 12, 31)
        
        logger.info(f"Starting annual rollup for {previous_year}")
        
        self.results['tax_summaries_annual'] = self._aggregate_tax_summaries(
            WindowType.ANNUAL, previous_year, None, period_start, period_end
        )
        
        return self.results
    
    # =========================================================================
    # Commission Metrics Aggregation
    # =========================================================================
    
    def _aggregate_commission_metrics_daily(self) -> AggregationResult:
        """Aggregate daily commission metrics for all scopes."""
        result = AggregationResult()
        period_start = self.target_date
        period_end = self.target_date
        
        # GLOBAL scope
        self._compute_commission_metric(
            result, WindowType.DAILY, period_start, period_end,
            ScopeType.GLOBAL, None
        )
        
        # Per MANAGER scope
        managers = self._get_all_managers()
        for manager in managers:
            self._compute_commission_metric(
                result, WindowType.DAILY, period_start, period_end,
                ScopeType.MANAGER, manager
            )
        
        # Per CONSULTANT scope
        consultants = self._get_all_consultants()
        for consultant in consultants:
            self._compute_commission_metric(
                result, WindowType.DAILY, period_start, period_end,
                ScopeType.CONSULTANT, consultant
            )
        
        return result
    
    def _aggregate_commission_metrics_monthly(self, period_start: date, period_end: date) -> AggregationResult:
        """Aggregate monthly commission metrics for all scopes."""
        result = AggregationResult()
        
        # GLOBAL scope
        self._compute_commission_metric(
            result, WindowType.MONTHLY, period_start, period_end,
            ScopeType.GLOBAL, None
        )
        
        # Per MANAGER and CONSULTANT
        managers = self._get_all_managers()
        for manager in managers:
            self._compute_commission_metric(
                result, WindowType.MONTHLY, period_start, period_end,
                ScopeType.MANAGER, manager
            )
        
        consultants = self._get_all_consultants()
        for consultant in consultants:
            self._compute_commission_metric(
                result, WindowType.MONTHLY, period_start, period_end,
                ScopeType.CONSULTANT, consultant
            )
        
        return result
    
    def _compute_commission_metric(
        self, result: AggregationResult, window: str, 
        period_start: date, period_end: date,
        scope: str, scope_user: Optional[Any]
    ):
        """Compute and save a single commission metric."""
        try:
            # Check if already exists (idempotency)
            exists = CommissionMetric.objects.filter(
                window=window,
                period_start=period_start,
                scope=scope,
                scope_id=scope_user
            ).exists()
            
            if exists:
                logger.debug(f"CommissionMetric already exists: {window} {period_start} {scope}")
                result.add_skipped()
                return
            
            # Build query filter based on scope
            base_filter = Q(created_at__date__gte=period_start, created_at__date__lte=period_end)
            
            if scope == ScopeType.CONSULTANT and scope_user:
                base_filter &= Q(consultant=scope_user)
            elif scope == ScopeType.MANAGER and scope_user:
                # Get all consultants reporting to this manager
                team_ids = self._get_team_consultant_ids(scope_user)
                base_filter &= Q(consultant_id__in=team_ids)
            
            # Aggregate commissions
            metrics = Commission.objects.filter(base_filter).aggregate(
                total_count=Count('id'),
                total_amount=Coalesce(Sum('amount'), Decimal('0')),
                approved_count=Count('id', filter=Q(status='APPROVED')),
                approved_amount=Coalesce(Sum('amount', filter=Q(status='APPROVED')), Decimal('0')),
                pending_count=Count('id', filter=Q(status='PENDING')),
                pending_amount=Coalesce(Sum('amount', filter=Q(status='PENDING')), Decimal('0')),
                rejected_count=Count('id', filter=Q(status='REJECTED')),
                rejected_amount=Coalesce(Sum('amount', filter=Q(status='REJECTED')), Decimal('0')),
                average_amount=Coalesce(Avg('amount'), Decimal('0'))
            )
            
            # Create metric record
            with transaction.atomic():
                CommissionMetric.objects.create(
                    window=window,
                    period_start=period_start,
                    period_end=period_end,
                    scope=scope,
                    scope_id=scope_user,
                    total_count=metrics['total_count'],
                    total_amount=metrics['total_amount'],
                    approved_count=metrics['approved_count'],
                    approved_amount=metrics['approved_amount'],
                    pending_count=metrics['pending_count'],
                    pending_amount=metrics['pending_amount'],
                    rejected_count=metrics['rejected_count'],
                    rejected_amount=metrics['rejected_amount'],
                    average_amount=metrics['average_amount']
                )
                result.add_created()
                
        except IntegrityError:
            # Unique constraint violation - already exists (race condition)
            logger.debug(f"CommissionMetric duplicate skipped: {window} {period_start} {scope}")
            result.add_skipped()
        except Exception as e:
            error_msg = f"Error computing CommissionMetric: {e}"
            logger.error(error_msg)
            result.add_error(error_msg)
    
    # =========================================================================
    # Payout Summary Aggregation
    # =========================================================================
    
    def _aggregate_payout_summaries_daily(self) -> AggregationResult:
        """Aggregate daily payout summaries for all scopes."""
        result = AggregationResult()
        period_start = self.target_date
        period_end = self.target_date
        
        # GLOBAL scope
        self._compute_payout_summary(
            result, WindowType.DAILY, period_start, period_end,
            ScopeType.GLOBAL, None
        )
        
        # Per MANAGER scope
        managers = self._get_all_managers()
        for manager in managers:
            self._compute_payout_summary(
                result, WindowType.DAILY, period_start, period_end,
                ScopeType.MANAGER, manager
            )
        
        # Per CONSULTANT scope
        consultants = self._get_all_consultants()
        for consultant in consultants:
            self._compute_payout_summary(
                result, WindowType.DAILY, period_start, period_end,
                ScopeType.CONSULTANT, consultant
            )
        
        return result
    
    def _aggregate_payout_summaries_monthly(self, period_start: date, period_end: date) -> AggregationResult:
        """Aggregate monthly payout summaries."""
        result = AggregationResult()
        
        self._compute_payout_summary(
            result, WindowType.MONTHLY, period_start, period_end,
            ScopeType.GLOBAL, None
        )
        
        managers = self._get_all_managers()
        for manager in managers:
            self._compute_payout_summary(
                result, WindowType.MONTHLY, period_start, period_end,
                ScopeType.MANAGER, manager
            )
        
        consultants = self._get_all_consultants()
        for consultant in consultants:
            self._compute_payout_summary(
                result, WindowType.MONTHLY, period_start, period_end,
                ScopeType.CONSULTANT, consultant
            )
        
        return result
    
    def _compute_payout_summary(
        self, result: AggregationResult, window: str,
        period_start: date, period_end: date,
        scope: str, scope_user: Optional[Any]
    ):
        """Compute and save a single payout summary."""
        try:
            # Check if already exists
            exists = PayoutSummary.objects.filter(
                window=window,
                period_start=period_start,
                scope=scope,
                scope_id=scope_user
            ).exists()
            
            if exists:
                result.add_skipped()
                return
            
            # Build query filter
            base_filter = Q(batch__run_date__gte=period_start, batch__run_date__lte=period_end)
            
            if scope == ScopeType.CONSULTANT and scope_user:
                base_filter &= Q(consultant=scope_user)
            elif scope == ScopeType.MANAGER and scope_user:
                team_ids = self._get_team_consultant_ids(scope_user)
                base_filter &= Q(consultant_id__in=team_ids)
            
            # Aggregate payouts
            metrics = Payout.objects.filter(base_filter).aggregate(
                payout_count=Count('id'),
                total_amount=Coalesce(Sum('total_commission'), Decimal('0')),
                paid_amount=Coalesce(Sum('total_commission', filter=Q(status='PAID')), Decimal('0')),
                pending_amount=Coalesce(Sum('total_commission', filter=Q(status='DRAFT')), Decimal('0')),
                failed_amount=Coalesce(Sum('total_commission', filter=Q(status='ERROR')), Decimal('0'))
            )
            
            # Count unique batches
            batch_count = Payout.objects.filter(base_filter).values('batch').distinct().count()
            
            # Calculate average cycle time and success rate
            paid_count = Payout.objects.filter(base_filter, status='PAID').count()
            total_count = metrics['payout_count'] or 1
            success_rate = (paid_count / total_count) * 100 if total_count > 0 else Decimal('0')
            
            with transaction.atomic():
                PayoutSummary.objects.create(
                    window=window,
                    period_start=period_start,
                    period_end=period_end,
                    scope=scope,
                    scope_id=scope_user,
                    batch_count=batch_count,
                    payout_count=metrics['payout_count'],
                    total_amount=metrics['total_amount'],
                    paid_amount=metrics['paid_amount'],
                    pending_amount=metrics['pending_amount'],
                    failed_amount=metrics['failed_amount'],
                    avg_cycle_days=Decimal('0'),  # TODO: Calculate from actual data
                    success_rate=Decimal(str(success_rate))
                )
                result.add_created()
                
        except IntegrityError:
            result.add_skipped()
        except Exception as e:
            result.add_error(f"Error computing PayoutSummary: {e}")
    
    # =========================================================================
    # Reconciliation Summary Aggregation
    # =========================================================================
    
    def _aggregate_reconciliation_summaries_daily(self) -> AggregationResult:
        """Aggregate daily reconciliation summaries (global only)."""
        result = AggregationResult()
        self._compute_reconciliation_summary(
            result, WindowType.DAILY, self.target_date, self.target_date
        )
        return result
    
    def _aggregate_reconciliation_summaries_monthly(self, period_start: date, period_end: date) -> AggregationResult:
        """Aggregate monthly reconciliation summaries."""
        result = AggregationResult()
        self._compute_reconciliation_summary(result, WindowType.MONTHLY, period_start, period_end)
        return result
    
    def _compute_reconciliation_summary(
        self, result: AggregationResult, window: str,
        period_start: date, period_end: date
    ):
        """Compute and save reconciliation summary."""
        try:
            exists = ReconciliationSummary.objects.filter(
                window=window,
                period_start=period_start
            ).exists()
            
            if exists:
                result.add_skipped()
                return
            
            # Aggregate reconciliations
            base_filter = Q(reconciliation_date__gte=period_start, reconciliation_date__lte=period_end)
            
            metrics = PaymentReconciliation.objects.filter(base_filter).aggregate(
                total_batches=Count('batch', distinct=True),
                matched_count=Count('id', filter=Q(status='MATCHED')),
                pending_count=Count('id', filter=Q(status='PENDING')),
                discrepancy_count=Count('id', filter=Q(status='DISCREPANCY')),
                total_expected=Coalesce(Sum('expected_amount'), Decimal('0')),
                total_actual=Coalesce(Sum('actual_amount'), Decimal('0')),
                total_discrepancy=Coalesce(Sum('discrepancy_amount'), Decimal('0'))
            )
            
            with transaction.atomic():
                ReconciliationSummary.objects.create(
                    window=window,
                    period_start=period_start,
                    period_end=period_end,
                    total_batches=metrics['total_batches'] or 0,
                    matched_count=metrics['matched_count'] or 0,
                    pending_count=metrics['pending_count'] or 0,
                    discrepancy_count=metrics['discrepancy_count'] or 0,
                    total_expected=metrics['total_expected'],
                    total_actual=metrics['total_actual'],
                    total_discrepancy=metrics['total_discrepancy']
                )
                result.add_created()
                
        except IntegrityError:
            result.add_skipped()
        except Exception as e:
            result.add_error(f"Error computing ReconciliationSummary: {e}")
    
    # =========================================================================
    # Tax Summary Aggregation
    # =========================================================================
    
    def _aggregate_tax_summaries(
        self, window: str, tax_year: int, quarter: Optional[int],
        period_start: date, period_end: date
    ) -> AggregationResult:
        """Aggregate tax summaries for all scopes."""
        result = AggregationResult()
        
        # GLOBAL scope
        self._compute_tax_summary(
            result, window, tax_year, quarter, period_start, period_end,
            ScopeType.GLOBAL, None
        )
        
        # Per CONSULTANT scope
        consultants = self._get_all_consultants()
        for consultant in consultants:
            self._compute_tax_summary(
                result, window, tax_year, quarter, period_start, period_end,
                ScopeType.CONSULTANT, consultant
            )
        
        return result
    
    def _compute_tax_summary(
        self, result: AggregationResult, window: str, tax_year: int,
        quarter: Optional[int], period_start: date, period_end: date,
        scope: str, scope_user: Optional[Any]
    ):
        """Compute and save a single tax summary."""
        try:
            exists = TaxSummary.objects.filter(
                window=window,
                tax_year=tax_year,
                quarter=quarter,
                scope=scope,
                scope_id=scope_user
            ).exists()
            
            if exists:
                result.add_skipped()
                return
            
            if scope == ScopeType.GLOBAL:
                # Global metrics
                total_payments = Payout.objects.filter(
                    batch__run_date__gte=period_start,
                    batch__run_date__lte=period_end,
                    status='PAID'
                ).aggregate(total=Coalesce(Sum('total_commission'), Decimal('0')))['total']
                
                consultant_count = Payout.objects.filter(
                    batch__run_date__gte=period_start,
                    batch__run_date__lte=period_end
                ).values('consultant').distinct().count()
                
                # Above threshold: consultants with >= $600
                above_threshold = Payout.objects.filter(
                    batch__run_date__gte=period_start,
                    batch__run_date__lte=period_end,
                    status='PAID'
                ).values('consultant').annotate(
                    total=Sum('total_commission')
                ).filter(total__gte=600).count()
                
                w9_approved = W9Information.objects.filter(status='APPROVED').count()
                w9_pending = W9Information.objects.filter(status='PENDING').count()
                forms_generated = TaxDocument.objects.filter(tax_year=tax_year).count()
                forms_filed = TaxDocument.objects.filter(tax_year=tax_year, filed_at__isnull=False).count()
                
            else:
                # Consultant-specific metrics
                total_payments = Payout.objects.filter(
                    batch__run_date__gte=period_start,
                    batch__run_date__lte=period_end,
                    consultant=scope_user,
                    status='PAID'
                ).aggregate(total=Coalesce(Sum('total_commission'), Decimal('0')))['total']
                
                consultant_count = 1
                above_threshold = 1 if total_payments >= 600 else 0
                
                w9_approved = W9Information.objects.filter(
                    consultant=scope_user, status='APPROVED'
                ).count()
                w9_pending = W9Information.objects.filter(
                    consultant=scope_user, status='PENDING'
                ).count()
                forms_generated = TaxDocument.objects.filter(
                    consultant=scope_user, tax_year=tax_year
                ).count()
                forms_filed = TaxDocument.objects.filter(
                    consultant=scope_user, tax_year=tax_year, filed_at__isnull=False
                ).count()
            
            with transaction.atomic():
                TaxSummary.objects.create(
                    window=window,
                    tax_year=tax_year,
                    quarter=quarter,
                    period_start=period_start,
                    period_end=period_end,
                    scope=scope,
                    scope_id=scope_user,
                    total_payments=total_payments,
                    consultant_count=consultant_count,
                    above_threshold_count=above_threshold,
                    w9_approved_count=w9_approved,
                    w9_pending_count=w9_pending,
                    forms_generated_count=forms_generated,
                    forms_filed_count=forms_filed
                )
                result.add_created()
                
        except IntegrityError:
            result.add_skipped()
        except Exception as e:
            result.add_error(f"Error computing TaxSummary: {e}")
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _get_all_managers(self) -> List[Any]:
        """Get all users who are managers (have direct reports)."""
        manager_ids = ReportingLine.objects.values_list('manager_id', flat=True).distinct()
        return list(User.objects.filter(id__in=manager_ids))
    
    def _get_all_consultants(self) -> List[Any]:
        """Get all users who are consultants (have commissions)."""
        consultant_ids = Commission.objects.values_list('consultant_id', flat=True).distinct()
        return list(User.objects.filter(id__in=consultant_ids))
    
    def _get_team_consultant_ids(self, manager) -> List[int]:
        """Get IDs of all consultants reporting to a manager."""
        return list(
            ReportingLine.objects.filter(manager=manager).values_list('consultant_id', flat=True)
        )
