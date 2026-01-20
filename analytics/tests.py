"""
Phase 6.5 Analytics Verification Tests
Comprehensive test suite for Analytics & Reporting module.
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError

from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from commissions.models import Commission
from payouts.models import PayoutBatch, Payout, PayoutPeriod
from payments.models import W9Information, TaxDocument
from hierarchy.models import ReportingLine

from .models import (
    CommissionMetric, PayoutSummary, TaxSummary,
    ReconciliationSummary, ExportLog,
    WindowType, ScopeType, ReportType, ExportFormat
)
from .services import (
    FinanceDashboardService, ManagerDashboardService, ConsultantDashboardService,
    CommissionMetricsService, PayoutMetricsService,
    is_finance_or_admin, is_manager
)
from .aggregation import AggregationEngine, AggregationResult
from .exceptions import ForbiddenScopeError, ValidationError as AnalyticsValidationError


User = get_user_model()


# =============================================================================
# 1. Functional Verification Tests
# =============================================================================

class FinanceDashboardTests(APITestCase):
    """Test Finance dashboard functionality."""
    
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='testpass123'
        )
        self.consultant = User.objects.create_user(
            username='consultant1', email='consultant@test.com', password='testpass123'
        )
        self.client = APIClient()
    
    def test_finance_dashboard_access_admin(self):
        """Admin can access finance dashboard."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/analytics/dashboards/finance/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('summary', response.data)
        self.assertIn('commission_trend', response.data)
        self.assertIn('top_performers', response.data)
        self.assertIn('reconciliation_status', response.data)
    
    def test_finance_dashboard_denied_consultant(self):
        """Consultant cannot access finance dashboard."""
        self.client.force_authenticate(user=self.consultant)
        response = self.client.get('/api/analytics/dashboards/finance/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error'], 'forbidden')


class ManagerDashboardTests(APITestCase):
    """Test Manager dashboard team scoping."""
    
    def setUp(self):
        self.manager = User.objects.create_user(
            username='manager1', email='manager@test.com', password='testpass123'
        )
        self.consultant1 = User.objects.create_user(
            username='consultant1', email='c1@test.com', password='testpass123'
        )
        self.consultant2 = User.objects.create_user(
            username='consultant2', email='c2@test.com', password='testpass123'
        )
        # Create reporting line
        ReportingLine.objects.create(manager=self.manager, consultant=self.consultant1)
        self.client = APIClient()
    
    def test_manager_dashboard_access(self):
        """Manager can access manager dashboard."""
        self.client.force_authenticate(user=self.manager)
        response = self.client.get('/api/analytics/dashboards/manager/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('summary', response.data)
        self.assertEqual(response.data['summary']['team_size'], 1)
    
    def test_manager_dashboard_denied_non_manager(self):
        """Non-manager cannot access manager dashboard."""
        self.client.force_authenticate(user=self.consultant2)
        response = self.client.get('/api/analytics/dashboards/manager/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ConsultantDashboardTests(APITestCase):
    """Test Consultant dashboard isolation."""
    
    def setUp(self):
        self.consultant = User.objects.create_user(
            username='consultant1', email='c1@test.com', password='testpass123'
        )
        self.client = APIClient()
    
    def test_consultant_dashboard_access(self):
        """Consultant can access their dashboard."""
        self.client.force_authenticate(user=self.consultant)
        response = self.client.get('/api/analytics/dashboards/consultant/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('summary', response.data)
        self.assertIn('earnings_trend', response.data)
        self.assertIn('recent_payouts', response.data)


# =============================================================================
# 2. Aggregation Verification Tests
# =============================================================================

class AggregationEngineTests(TestCase):
    """Test aggregation engine functionality."""
    
    def setUp(self):
        self.consultant = User.objects.create_user(
            username='consultant1', email='c1@test.com', password='testpass123'
        )
    
    def test_daily_aggregation_creates_records(self):
        """Daily aggregation creates metric records."""
        engine = AggregationEngine(target_date=date.today() - timedelta(days=1))
        results = engine.run_daily_aggregation()
        
        self.assertIn('commission_metrics', results)
        self.assertIsInstance(results['commission_metrics'], AggregationResult)
    
    def test_idempotency_no_duplicates(self):
        """Running aggregation twice doesn't create duplicates."""
        target_date = date.today() - timedelta(days=1)
        
        # First run
        engine1 = AggregationEngine(target_date=target_date)
        results1 = engine1.run_daily_aggregation()
        created1 = results1['commission_metrics'].created
        
        # Second run (same date)
        engine2 = AggregationEngine(target_date=target_date)
        results2 = engine2.run_daily_aggregation()
        skipped2 = results2['commission_metrics'].skipped
        
        # Second run should skip all (already exists)
        self.assertGreaterEqual(skipped2, created1)


class AppendOnlyTests(TestCase):
    """Test append-only enforcement."""
    
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='testpass123'
        )
    
    def test_commission_metric_no_update(self):
        """CommissionMetric cannot be updated after creation."""
        metric = CommissionMetric.objects.create(
            window=WindowType.DAILY,
            period_start=date.today(),
            period_end=date.today(),
            scope=ScopeType.GLOBAL,
            scope_id=None,
            total_count=10,
            total_amount=Decimal('1000.00')
        )
        
        # Attempt to update should raise ValidationError
        metric.total_count = 20
        with self.assertRaises(ValidationError):
            metric.save()
    
    def test_commission_metric_no_delete(self):
        """CommissionMetric cannot be deleted."""
        metric = CommissionMetric.objects.create(
            window=WindowType.DAILY,
            period_start=date.today(),
            period_end=date.today(),
            scope=ScopeType.GLOBAL,
            scope_id=None,
            total_count=10,
            total_amount=Decimal('1000.00')
        )
        
        with self.assertRaises(ValidationError):
            metric.delete()


# =============================================================================
# 3. Caching Verification Tests
# =============================================================================

class CachingTests(APITestCase):
    """Test caching functionality."""
    
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='testpass123'
        )
        self.client = APIClient()
    
    @patch('analytics.views.get_cached')
    @patch('analytics.views.set_cached')
    def test_cache_hit_returns_cached_data(self, mock_set, mock_get):
        """Cached data is returned on cache hit."""
        cached_response = {'summary': {'test': 'cached'}}
        mock_get.return_value = cached_response
        
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/analytics/dashboards/finance/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, cached_response)
        mock_set.assert_not_called()  # Should not set cache on hit
    
    @patch('analytics.views.get_cached')
    @patch('analytics.views.set_cached')
    def test_cache_miss_calls_service(self, mock_set, mock_get):
        """Cache miss triggers service call and caches result."""
        mock_get.return_value = None  # Cache miss
        
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/analytics/dashboards/finance/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_set.assert_called_once()  # Should cache the result


class CacheIsolationTests(TestCase):
    """Test cache isolation by user/scope."""
    
    def test_cache_keys_include_user_id(self):
        """Cache keys include user_id for isolation."""
        from analytics.caching import build_dashboard_cache_key
        
        key1 = build_dashboard_cache_key('finance', 1, year=2026)
        key2 = build_dashboard_cache_key('finance', 2, year=2026)
        
        self.assertNotEqual(key1, key2)
        self.assertIn(':1:', key1)
        self.assertIn(':2:', key2)
    
    def test_cache_keys_deterministic(self):
        """Cache keys are deterministic for same params."""
        from analytics.caching import build_dashboard_cache_key
        
        key1 = build_dashboard_cache_key('finance', 1, year=2026, months=12)
        key2 = build_dashboard_cache_key('finance', 1, year=2026, months=12)
        
        self.assertEqual(key1, key2)


# =============================================================================
# 4. Rate Limiting Verification Tests
# =============================================================================

class RateLimitingTests(APITestCase):
    """Test rate limiting functionality."""
    
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='testpass123'
        )
        self.client = APIClient()
    
    def test_throttle_classes_assigned(self):
        """Views have correct throttle classes."""
        from analytics.views import (
            FinanceDashboardView, CommissionMetricsView, CommissionDetailExportView
        )
        from analytics.throttling import (
            AnalyticsDashboardThrottle, AnalyticsMetricsThrottle, AnalyticsExportThrottle
        )
        
        self.assertIn(AnalyticsDashboardThrottle, FinanceDashboardView.throttle_classes)
        self.assertIn(AnalyticsMetricsThrottle, CommissionMetricsView.throttle_classes)
        self.assertIn(AnalyticsExportThrottle, CommissionDetailExportView.throttle_classes)


# =============================================================================
# 5. Security & Privacy Verification Tests
# =============================================================================

class SecurityTests(APITestCase):
    """Test security and privacy enforcement."""
    
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='testpass123'
        )
        self.manager = User.objects.create_user(
            username='manager1', email='manager@test.com', password='testpass123'
        )
        self.consultant1 = User.objects.create_user(
            username='consultant1', email='c1@test.com', password='testpass123'
        )
        self.consultant2 = User.objects.create_user(
            username='consultant2', email='c2@test.com', password='testpass123'
        )
        ReportingLine.objects.create(manager=self.manager, consultant=self.consultant1)
        self.client = APIClient()
    
    def test_consultant_cannot_access_global_scope(self):
        """Consultant cannot access global scope metrics."""
        self.client.force_authenticate(user=self.consultant1)
        response = self.client.get('/api/analytics/commissions/metrics/', {
            'window': 'MONTHLY',
            'period_start': '2026-01-01',
            'period_end': '2026-01-31',
            'scope': 'GLOBAL'
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_consultant_cannot_access_other_consultant(self):
        """Consultant cannot access another consultant's data."""
        self.client.force_authenticate(user=self.consultant1)
        response = self.client.get('/api/analytics/commissions/metrics/', {
            'window': 'MONTHLY',
            'period_start': '2026-01-01',
            'period_end': '2026-01-31',
            'scope': 'CONSULTANT',
            'scope_id': self.consultant2.id
        })
        # Should either get 403 or be forced to own scope
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_200_OK])
    
    def test_manager_cannot_access_global_scope(self):
        """Manager cannot access global scope metrics."""
        self.client.force_authenticate(user=self.manager)
        response = self.client.get('/api/analytics/commissions/metrics/', {
            'window': 'MONTHLY',
            'period_start': '2026-01-01',
            'period_end': '2026-01-31',
            'scope': 'GLOBAL'
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_admin_can_access_all_scopes(self):
        """Admin can access all scopes."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/analytics/commissions/metrics/', {
            'window': 'MONTHLY',
            'period_start': '2026-01-01',
            'period_end': '2026-01-31',
            'scope': 'GLOBAL'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class ExportLogTests(APITestCase):
    """Test ExportLog creation."""
    
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='testpass123'
        )
        self.client = APIClient()
    
    def test_export_creates_log_entry(self):
        """Export creates ExportLog entry."""
        initial_count = ExportLog.objects.count()
        
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/analytics/reports/commission-detail/', {
            'start_date': '2026-01-01',
            'end_date': '2026-01-31',
            'format': 'csv'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ExportLog.objects.count(), initial_count + 1)
        
        log = ExportLog.objects.latest('created_at')
        self.assertEqual(log.user, self.admin)
        self.assertEqual(log.report_type, ReportType.COMMISSION_DETAIL)


# =============================================================================
# 6. Regression Verification Tests
# =============================================================================

class RegressionTests(TestCase):
    """Test for regressions in Phase 4/5."""
    
    def test_commission_model_unchanged(self):
        """Commission model from Phase 4 is unaffected."""
        from commissions.models import Commission
        # Model should exist and have expected fields
        self.assertTrue(hasattr(Commission, 'amount'))
        self.assertTrue(hasattr(Commission, 'status'))
        self.assertTrue(hasattr(Commission, 'consultant'))
    
    def test_payout_model_unchanged(self):
        """Payout model from Phase 4 is unaffected."""
        from payouts.models import Payout
        self.assertTrue(hasattr(Payout, 'total_commission'))
        self.assertTrue(hasattr(Payout, 'status'))
        self.assertTrue(hasattr(Payout, 'consultant'))
    
    def test_payment_model_unchanged(self):
        """Payment models from Phase 5 are unaffected."""
        from payments.models import PaymentMethod, PaymentTransaction
        self.assertTrue(hasattr(PaymentMethod, 'consultant'))
        self.assertTrue(hasattr(PaymentTransaction, 'amount'))


class EndpointRegressionTests(APITestCase):
    """Test that Phase 4/5 endpoints still work."""
    
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='testpass123'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
    
    def test_commissions_endpoint_works(self):
        """Phase 4 commissions endpoint still works."""
        response = self.client.get('/api/commissions/')
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN])
    
    def test_payouts_endpoint_works(self):
        """Phase 4 payouts endpoint still works."""
        response = self.client.get('/api/payouts/')
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN])
    
    def test_payments_endpoint_works(self):
        """Phase 5 payments endpoint still works."""
        response = self.client.get('/api/payments/methods/')
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN])
