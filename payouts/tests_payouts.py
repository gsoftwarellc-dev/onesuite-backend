from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal

from commissions.models import Commission, CommissionApproval
from payouts.models import PayoutPeriod, PayoutBatch, Payout, PayoutLineItem
from payouts.services import PayoutCalculationService, PayoutLifecycleService, PayoutError

User = get_user_model()

class PayoutServiceTests(APITestCase):
    def setUp(self):
        # Users
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pass')
        self.consultant = User.objects.create_user('consultant', 'user@example.com', 'pass')
        
        # Period
        self.period = PayoutPeriod.objects.create(
            name="Jan 2026",
            start_date="2026-01-01",
            end_date="2026-01-31",
            status='OPEN'
        )
        
        # Commissions (Approved)
        self.comm1 = Commission.objects.create(
            consultant=self.consultant,
            commission_type='base',
            state='approved',
            sale_amount=1000,
            commission_rate=10,
            calculated_amount=100,
            reference_number='C1',
            transaction_date="2026-01-05"
        )
        self.comm2 = Commission.objects.create(
            consultant=self.consultant,
            commission_type='base',
            state='approved',
            sale_amount=2000,
            commission_rate=10,
            calculated_amount=200,
            reference_number='C2',
            transaction_date="2026-01-10"
        )
        # Not Approved Commission
        self.comm_pending = Commission.objects.create(
            consultant=self.consultant,
            commission_type='base',
            state='submitted',
            sale_amount=500,
            commission_rate=10,
            calculated_amount=50,
            reference_number='C3',
            transaction_date="2026-01-15"
        )

    def test_calculation_service(self):
        """Test batch creation and payout generation logic."""
        batch = PayoutCalculationService.create_batch_for_period(self.period, self.admin)
        
        self.assertEqual(batch.status, 'DRAFT')
        self.assertEqual(batch.payouts.count(), 1)
        
        payout = batch.payouts.first()
        self.assertEqual(payout.consultant, self.consultant)
        self.assertEqual(payout.total_commission, Decimal('300.00')) # 100 + 200
        
        # Ensure pending commission was ignored
        self.assertEqual(payout.line_items.count(), 2)

    def test_lifecycle_release(self):
        """Test Lock -> Release flow and side effects."""
        batch = PayoutCalculationService.create_batch_for_period(self.period, self.admin)
        
        # Draft -> Release (Should Fail)
        with self.assertRaises(PayoutError):
            PayoutLifecycleService.release_batch(batch, self.admin)
            
        # Draft -> Lock
        PayoutLifecycleService.lock_batch(batch, self.admin)
        self.assertEqual(batch.status, 'LOCKED')
        
        # Lock -> Release
        PayoutLifecycleService.release_batch(batch, self.admin)
        self.assertEqual(batch.status, 'RELEASED')
        
        # Check Commissions updated to PAID
        self.comm1.refresh_from_db()
        self.comm2.refresh_from_db()
        self.assertEqual(self.comm1.state, 'paid')
        self.assertEqual(self.comm2.state, 'paid')

    def test_lifecycle_void(self):
        """Test Void flow and Unlinking."""
        batch = PayoutCalculationService.create_batch_for_period(self.period, self.admin)
        
        # Void Batch
        PayoutLifecycleService.void_batch(batch, self.admin)
        self.assertEqual(batch.status, 'VOID')
        
        # Check Lines Deleted
        self.assertEqual(PayoutLineItem.objects.filter(payout__batch=batch).count(), 0)
        
        # Check Commissions Free
        self.comm1.refresh_from_db()
        self.assertTrue(hasattr(self.comm1, 'payout_line_item') == False or self.comm1.payout_line_item is None)
        self.assertEqual(self.comm1.state, 'approved') # Should remain approved

    def test_double_payment_prevention(self):
        """Ensure a commission cannot be added to two batches."""
        # Batch 1
        batch1 = PayoutCalculationService.create_batch_for_period(self.period, self.admin)
        
        # Batch 2 (Should not pick up same commissions)
        batch2 = PayoutCalculationService.create_batch_for_period(self.period, self.admin)
        
        payout1 = batch1.payouts.first()
        self.assertIsNotNone(payout1)
        
        # Batch 2 shouldn't have payouts as no free commissions exist
        self.assertEqual(batch2.payouts.count(), 0)


class PayoutAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pass')
        self.user = User.objects.create_user('user', 'user@example.com', 'pass')
        
        self.period = PayoutPeriod.objects.create(
            name="Feb 2026",
            start_date="2026-02-01",
            end_date="2026-02-28",
            status='OPEN'
        )

    def test_admin_permissions(self):
        """Admin can create batches."""
        self.client.force_authenticate(user=self.admin)
        url = reverse('payout-batch-list')
        data = {'period_id': self.period.id, 'notes': 'Test'}
        
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_user_permissions(self):
        """Regular user cannot create batches."""
        self.client.force_authenticate(user=self.user)
        url = reverse('payout-batch-list')
        data = {'period_id': self.period.id}
        
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
