"""
Unit tests for the Commissions Engine.

Tests:
- Commission creation
- Override resolution
- State transitions
- Adjustments
- Financial calculations
"""

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from datetime import date, datetime, timedelta

from commissions.models import Commission
from commissions.services import (
    CommissionCalculationService,
    OverrideResolutionService,
    CommissionCreationService,
    StateTransitionService,
    AdjustmentService,
)
from hierarchy.models import ReportingLine

User = get_user_model()


class CommissionCalculationServiceTest(TestCase):
    """Test commission calculation logic"""
    
    def test_calculate_base_commission_no_gst(self):
        """Test basic commission calculation without GST"""
        amount = CommissionCalculationService.calculate_base_commission(
            sale_amount=Decimal('1000.00'),
            commission_rate=Decimal('5.00'),
            gst_rate=Decimal('0.00')
        )
        self.assertEqual(amount, Decimal('50.00'))
    
    def test_calculate_base_commission_with_gst(self):
        """Test commission calculation with GST included in sale amount"""
        # Sale amount is $1100 including 10% GST
        # Base amount = 1100 / 1.10 = 1000
        # Commission = 1000 * 5% = 50
        amount = CommissionCalculationService.calculate_base_commission(
            sale_amount=Decimal('1100.00'),
            commission_rate=Decimal('5.00'),
            gst_rate=Decimal('10.00')
        )
        self.assertEqual(amount, Decimal('50.00'))
    
    def test_decimal_precision(self):
        """Ensure no floating point errors"""
        amount = CommissionCalculationService.calculate_base_commission(
            sale_amount=Decimal('3333.33'),
            commission_rate=Decimal('7.77'),
            gst_rate=Decimal('0.00')
        )
        # Result should be 3333.33 * 0.0777 = 259.00
        self.assertEqual(amount, Decimal('259.00'))


class OverrideResolutionServiceTest(TestCase):
    """Test override resolution using hierarchy"""
    
    def setUp(self):
        """Create test users and hierarchy"""
        self.consultant = User.objects.create_user('consultant', 'c@test.com', 'pass')
        self.manager1 = User.objects.create_user('manager1', 'm1@test.com', 'pass')
        self.manager2 = User.objects.create_user('manager2', 'm2@test.com', 'pass')
        
        # Create hierarchy: consultant → manager1 → manager2
        ReportingLine.objects.create(
            consultant=self.consultant,
            manager=self.manager1,
            start_date=date(2026, 1, 1),
            is_active=True
        )
        ReportingLine.objects.create(
            consultant=self.manager1,
            manager=self.manager2,
            start_date=date(2026, 1, 1),
            is_active=True
        )
    
    def test_get_manager_at_date(self):
        """Test finding manager at specific date"""
        manager = OverrideResolutionService.get_manager_at_date(
            self.consultant,
            date(2026, 1, 15)
        )
        self.assertEqual(manager, self.manager1)
    
    def test_resolve_override_chain(self):
        """Test multi-level override resolution"""
        chain = OverrideResolutionService.resolve_override_chain(
            self.consultant,
            date(2026, 1, 15),
            max_levels=2
        )
        
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0], (self.manager1, 1))
        self.assertEqual(chain[1], (self.manager2, 2))
    
    def test_no_manager_found(self):
        """Test when consultant has no manager"""
        orphan = User.objects.create_user('orphan', 'o@test.com', 'pass')
        chain = OverrideResolutionService.resolve_override_chain(
            orphan,
            date(2026, 1, 15)
        )
        self.assertEqual(len(chain), 0)


class CommissionCreationServiceTest(TestCase):
    """Test commission creation with overrides"""
    
    def setUp(self):
        """Setup test data"""
        self.consultant = User.objects.create_user('consultant', 'c@test.com', 'pass')
        self.manager = User.objects.create_user('manager', 'm@test.com', 'pass')
        self.admin = User.objects.create_user('admin', 'a@test.com', 'pass', is_staff=True)
        
        ReportingLine.objects.create(
            consultant=self.consultant,
            manager=self.manager,
            start_date=date(2026, 1, 1),
            is_active=True
        )
    
    def test_create_base_commission_with_overrides(self):
        """Test creating commission automatically creates overrides"""
        result = CommissionCreationService.create_base_commission_with_overrides(
            consultant=self.consultant,
            transaction_date=date(2026, 1, 15),
            sale_amount=Decimal('1000.00'),
            gst_rate=Decimal('0.00'),
            commission_rate=Decimal('5.00'),
            reference_number='TEST-001',
            notes='Test sale',
            created_by=self.admin,
            client_name='Test Client'
        )
        
        # Should create 1 base + 1 override
        self.assertEqual(result['total_created'], 2)
        self.assertIsNotNone(result['base_commission'])
        self.assertEqual(len(result['override_commissions']), 1)
        
        # Verify base commission
        base = result['base_commission']
        self.assertEqual(base.commission_type, 'base')
        self.assertEqual(base.calculated_amount, Decimal('50.00'))
        self.assertEqual(base.consultant, self.consultant)
        self.assertIsNone(base.manager)
        self.assertEqual(base.client_name, 'Test Client')
        
        # Verify override commission
        override = result['override_commissions'][0]
        self.assertEqual(override.commission_type, 'override')
        self.assertEqual(override.manager, self.manager)
        self.assertEqual(override.parent_commission, base)
        self.assertEqual(override.client_name, 'Test Client')
    
    def test_duplicate_reference_number_fails(self):
        """Test that duplicate reference numbers are prevented"""
        CommissionCreationService.create_base_commission_with_overrides(
            consultant=self.consultant,
            transaction_date=date(2026, 1, 15),
            sale_amount=Decimal('1000.00'),
            gst_rate=Decimal('0.00'),
            commission_rate=Decimal('5.00'),
            reference_number='TEST-DUP',
            created_by=self.admin,
            client_name='Test Client'
        )
        
        # Try to create duplicate
        with self.assertRaises(Exception):
            CommissionCreationService.create_base_commission_with_overrides(
                consultant=self.consultant,
                transaction_date=date(2026, 1, 16),
                sale_amount=Decimal('2000.00'),
                gst_rate=Decimal('0.00'),
                commission_rate=Decimal('5.00'),
                reference_number='TEST-DUP',
                created_by=self.admin,
                client_name='Test Client'
            )


class StateTransitionServiceTest(TestCase):
    """Test commission state transitions"""
    
    def setUp(self):
        """Create test commission"""
        self.user = User.objects.create_user('user', 'u@test.com', 'pass')
        self.admin = User.objects.create_user('admin', 'a@test.com', 'pass', is_staff=True)
        
        self.commission = Commission.objects.create(
            commission_type='base',
            consultant=self.user,
            transaction_date=date(2026, 1, 15),
            sale_amount=Decimal('1000.00'),
            gst_rate=Decimal('0.00'),
            commission_rate=Decimal('5.00'),
            calculated_amount=Decimal('50.00'),
            state='draft',
            reference_number='TEST-STATE-001',
            created_by=self.user
        )
    
    def test_draft_to_submitted(self):
        """Test draft → submitted transition"""
        StateTransitionService.transition_to_submitted(
            self.commission,
            actor=self.user
        )
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.state, 'submitted')
    
    def test_submitted_to_approved(self):
        """Test submitted → approved transition"""
        self.commission.state = 'submitted'
        self.commission.save()
        
        StateTransitionService.transition_to_approved(
            self.commission,
            actor=self.admin
        )
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.state, 'approved')
        self.assertEqual(self.commission.approved_by, self.admin)
        self.assertIsNotNone(self.commission.approved_at)
    
    def test_approved_to_paid(self):
        """Test approved → paid transition"""
        self.commission.state = 'approved'
        self.commission.save()
        
        StateTransitionService.transition_to_paid(
            self.commission,
            actor=self.admin
        )
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.state, 'paid')
        self.assertIsNotNone(self.commission.paid_at)
    
    def test_invalid_transition_fails(self):
        """Test invalid transitions raise errors"""
        # Cannot go from draft directly to paid
        with self.assertRaises(ValidationError):
            StateTransitionService.transition_to_paid(
                self.commission,
                actor=self.admin
            )
    
    def test_submitted_to_rejected(self):
        """Test submitted → rejected transition"""
        self.commission.state = 'submitted'
        self.commission.save()
        
        StateTransitionService.transition_to_rejected(
            self.commission,
            actor=self.admin,
            rejection_reason='Incorrect amount'
        )
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.state, 'rejected')
        self.assertEqual(self.commission.rejection_reason, 'Incorrect amount')


class AdjustmentServiceTest(TestCase):
    """Test adjustment creation"""
    
    def setUp(self):
        """Create paid commission"""
        self.user = User.objects.create_user('user', 'u@test.com', 'pass')
        self.admin = User.objects.create_user('admin', 'a@test.com', 'pass', is_staff=True)
        
        self.paid_commission = Commission.objects.create(
            commission_type='base',
            consultant=self.user,
            transaction_date=date(2026, 1, 15),
            sale_amount=Decimal('1000.00'),
            gst_rate=Decimal('0.00'),
            commission_rate=Decimal('5.00'),
            calculated_amount=Decimal('50.00'),
            state='paid',
            reference_number='TEST-ADJ-001',
            created_by=self.user
        )
    
    def test_create_adjustment_for_paid_commission(self):
        """Test creating adjustment for paid commission"""
        adjustment = AdjustmentService.create_adjustment(
            original_commission=self.paid_commission,
            adjustment_amount=Decimal('-10.00'),
            notes='Overpayment correction',
            created_by=self.admin
        )
        
        self.assertEqual(adjustment.commission_type, 'adjustment')
        self.assertEqual(adjustment.calculated_amount, Decimal('-10.00'))
        self.assertEqual(adjustment.adjustment_for, self.paid_commission)
        self.assertEqual(adjustment.state, 'draft')
    
    def test_adjustment_for_non_paid_fails(self):
        """Test adjustment only works for paid commissions"""
        draft_commission = Commission.objects.create(
            commission_type='base',
            consultant=self.user,
            transaction_date=date(2026, 1, 16),
            sale_amount=Decimal('1000.00'),
            gst_rate=Decimal('0.00'),
            commission_rate=Decimal('5.00'),
            calculated_amount=Decimal('50.00'),
            state='draft',
            reference_number='TEST-ADJ-002',
            created_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            AdjustmentService.create_adjustment(
                original_commission=draft_commission,
                adjustment_amount=Decimal('-10.00'),
                notes='Should fail',
                created_by=self.admin
            )
    
    def test_zero_adjustment_fails(self):
        """Test zero adjustment is not allowed"""
        with self.assertRaises(ValidationError):
            AdjustmentService.create_adjustment(
                original_commission=self.paid_commission,
                adjustment_amount=Decimal('0.00'),
                notes='Zero adjustment',
                created_by=self.admin
            )


class CommissionModelTest(TestCase):
    """Test Commission model constraints"""
    
    def setUp(self):
        self.user = User.objects.create_user('user', 'u@test.com', 'pass')
        self.manager = User.objects.create_user('manager', 'm@test.com', 'pass')
    
    def test_base_commission_cannot_have_manager(self):
        """Test base commissions must not have manager field"""
        commission = Commission(
            commission_type='base',
            consultant=self.user,
            manager=self.manager,  # Should not be set for base
            transaction_date=date(2026, 1, 15),
            sale_amount=Decimal('1000.00'),
            gst_rate=Decimal('0.00'),
            commission_rate=Decimal('5.00'),
            calculated_amount=Decimal('50.00'),
            state='draft',
            reference_number='TEST-MODEL-001'
        )
        
        with self.assertRaises(ValidationError):
            commission.save()
    
    def test_override_must_have_manager(self):
        """Test override commissions must have manager"""
        commission = Commission(
            commission_type='override',
            consultant=self.user,
            manager=None,  # Should be set for override
            transaction_date=date(2026, 1, 15),
            sale_amount=Decimal('1000.00'),
            gst_rate=Decimal('0.00'),
            commission_rate=Decimal('2.00'),
            calculated_amount=Decimal('20.00'),
            state='draft',
            reference_number='TEST-MODEL-002-OVR'
        )
        
        with self.assertRaises(ValidationError):
            commission.save()
