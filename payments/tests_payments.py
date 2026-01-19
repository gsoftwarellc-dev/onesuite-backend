"""
Phase 5.5 Verification Tests
Comprehensive test suite for Payments & Compliance system.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from datetime import date

from payments.models import (
    PaymentMethod,
    PaymentTransaction,
    W9Information,
    TaxDocument,
    PaymentReconciliation,
    PaymentAuditLog
)
from payments.services import (
    PaymentMethodService,
    PaymentTransactionService,
    W9Service,
    TaxDocumentService,
    ReconciliationService,
    PaymentStateError,
    PaymentValidationError
)
from payments.encryption import EncryptionService
from payouts.models import PayoutBatch, Payout, PayoutPeriod
from commissions.models import Commission

User = get_user_model()


class PaymentMethodTests(TestCase):
    """Test PaymentMethod lifecycle and encryption"""
    
    def setUp(self):
        self.consultant = User.objects.create_user(username='consultant1', email='c1@test.com')
        self.admin = User.objects.create_user(username='admin1', email='admin@test.com', is_staff=True)
    
    def test_create_payment_method_encrypts_sensitive_fields(self):
        """Verify sensitive fields are encrypted at rest"""
        method_data = {
            'method_type': 'ACH',
            'account_holder_name': 'John Doe',
            'bank_name': 'Test Bank',
            'routing_number': '123456789',
            'account_number': '9876543210',
            'account_type': 'CHECKING'
        }
        
        payment_method = PaymentMethodService.create_payment_method(
            consultant=self.consultant,
            method_data=method_data,
            actor=self.consultant
        )
        
        # Verify data is encrypted in database
        self.assertNotEqual(payment_method.routing_number, '123456789')
        self.assertNotEqual(payment_method.account_number, '9876543210')
        
        # Verify decryption works
        decrypted_routing = EncryptionService.decrypt(payment_method.routing_number)
        self.assertEqual(decrypted_routing, '123456789')
        
        # Verify masking works
        masked = EncryptionService.mask_account_number(payment_method.account_number)
        self.assertEqual(masked, '****3210')
    
    def test_payment_method_verification_workflow(self):
        """Test payment method verification state transition"""
        method_data = {
            'method_type': 'ACH',
            'account_holder_name': 'John Doe',
            'bank_name': 'Test Bank',
            'routing_number': '123456789',
            'account_number': '9876543210',
            'account_type': 'CHECKING'
        }
        
        payment_method = PaymentMethodService.create_payment_method(
            consultant=self.consultant,
            method_data=method_data,
            actor=self.consultant
        )
        
        # Initial status should be PENDING
        self.assertEqual(payment_method.status, PaymentMethod.Status.PENDING)
        
        # Verify method
        verified_method = PaymentMethodService.verify_payment_method(
            payment_method=payment_method,
            verified_by=self.admin,
            notes='Verified via micro-deposit'
        )
        
        self.assertEqual(verified_method.status, PaymentMethod.Status.VERIFIED)
        self.assertEqual(verified_method.verified_by, self.admin)
        self.assertIsNotNone(verified_method.verified_at)
        
        # Cannot verify again
        with self.assertRaises(PaymentStateError):
            PaymentMethodService.verify_payment_method(
                payment_method=verified_method,
                verified_by=self.admin
            )
    
    def test_set_default_requires_verified_status(self):
        """Only verified methods can be set as default"""
        method_data = {
            'method_type': 'ACH',
            'account_holder_name': 'John Doe',
            'bank_name': 'Test Bank',
            'routing_number': '123456789',
            'account_number': '9876543210',
            'account_type': 'CHECKING'
        }
        
        payment_method = PaymentMethodService.create_payment_method(
            consultant=self.consultant,
            method_data=method_data,
            actor=self.consultant
        )
        
        # Cannot set PENDING method as default
        with self.assertRaises(PaymentValidationError):
            PaymentMethodService.set_default_payment_method(
                payment_method=payment_method,
                actor=self.consultant
            )
        
        # Verify first
        PaymentMethodService.verify_payment_method(
            payment_method=payment_method,
            verified_by=self.admin
        )
        
        # Now can set as default
        default_method = PaymentMethodService.set_default_payment_method(
            payment_method=payment_method,
            actor=self.consultant
        )
        
        self.assertTrue(default_method.is_default)


class W9Tests(TestCase):
    """Test W-9 management and TIN encryption"""
    
    def setUp(self):
        self.consultant = User.objects.create_user(username='consultant1', email='c1@test.com')
        self.admin = User.objects.create_user(username='admin1', email='admin@test.com', is_staff=True)
    
    def test_w9_submission_encrypts_tin(self):
        """Verify TIN is encrypted at rest"""
        w9_data = {
            'legal_name': 'John Doe',
            'entity_type': 'INDIVIDUAL',
            'tin_type': 'SSN',
            'tin': '123-45-6789',
            'address_line1': '123 Main St',
            'city': 'New York',
            'state': 'NY',
            'zip_code': '10001'
        }
        
        w9 = W9Service.submit_w9(
            consultant=self.consultant,
            w9_data=w9_data,
            actor=self.consultant
        )
        
        # Verify TIN is encrypted
        self.assertNotEqual(w9.tin, '123-45-6789')
        
        # Verify decryption works
        decrypted_tin = EncryptionService.decrypt(w9.tin)
        self.assertEqual(decrypted_tin, '123-45-6789')
        
        # Verify masking works
        masked = EncryptionService.mask_tin(w9.tin)
        self.assertEqual(masked, '***-**-6789')
    
    def test_w9_approval_workflow(self):
        """Test W-9 approval state transitions"""
        w9_data = {
            'legal_name': 'John Doe',
            'entity_type': 'INDIVIDUAL',
            'tin_type': 'SSN',
            'tin': '123-45-6789',
            'address_line1': '123 Main St',
            'city': 'New York',
            'state': 'NY',
            'zip_code': '10001'
        }
        
        w9 = W9Service.submit_w9(
            consultant=self.consultant,
            w9_data=w9_data,
            actor=self.consultant
        )
        
        # Initial status should be PENDING
        self.assertEqual(w9.status, W9Information.Status.PENDING)
        
        # Approve W-9
        approved_w9 = W9Service.approve_w9(
            w9=w9,
            approved_by=self.admin,
            notes='Verified with IRS'
        )
        
        self.assertEqual(approved_w9.status, W9Information.Status.APPROVED)
        self.assertEqual(approved_w9.reviewed_by, self.admin)
        self.assertIsNotNone(approved_w9.reviewed_at)
    
    def test_w9_rejection_requires_reason(self):
        """W-9 rejection must include reason"""
        w9_data = {
            'legal_name': 'John Doe',
            'entity_type': 'INDIVIDUAL',
            'tin_type': 'SSN',
            'tin': '123-45-6789',
            'address_line1': '123 Main St',
            'city': 'New York',
            'state': 'NY',
            'zip_code': '10001'
        }
        
        w9 = W9Service.submit_w9(
            consultant=self.consultant,
            w9_data=w9_data,
            actor=self.consultant
        )
        
        # Reject with reason
        rejected_w9 = W9Service.reject_w9(
            w9=w9,
            rejected_by=self.admin,
            reason='Invalid TIN format'
        )
        
        self.assertEqual(rejected_w9.status, W9Information.Status.REJECTED)
        self.assertIn('Invalid TIN format', rejected_w9.approval_notes)


class PaymentTransactionTests(TestCase):
    """Test payment transaction lifecycle"""
    
    def setUp(self):
        self.consultant = User.objects.create_user(username='consultant1', email='c1@test.com')
        self.admin = User.objects.create_user(username='admin1', email='admin@test.com', is_staff=True)
        
        # Create payout batch
        period = PayoutPeriod.objects.create(
            name='Jan 2026',
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31)
        )
        self.batch = PayoutBatch.objects.create(
            period=period,
            reference_number='PAY-JAN-2026-001',
            status='RELEASED',
            run_date=date(2026, 1, 31),
            created_by=self.admin
        )
        
        # Create payout
        self.payout = Payout.objects.create(
            batch=self.batch,
            consultant=self.consultant,
            total_commission=Decimal('1000.00')
        )
    
    def test_payment_confirmation_workflow(self):
        """Test payment confirmation state transition"""
        # Create transaction
        transaction = PaymentTransaction.objects.create(
            batch=self.batch,
            status=PaymentTransaction.Status.PENDING,
            processor_type=PaymentTransaction.ProcessorType.MANUAL,
            total_amount=Decimal('1000.00'),
            initiated_by=self.admin
        )
        
        # Confirm payment
        confirmed_transaction = PaymentTransactionService.confirm_payment(
            transaction=transaction,
            confirmed_by=self.admin,
            external_reference='BANK-TX-12345',
            confirmation_code='CONF-ABC123'
        )
        
        self.assertEqual(confirmed_transaction.status, PaymentTransaction.Status.COMPLETED)
        self.assertEqual(confirmed_transaction.external_reference, 'BANK-TX-12345')
        self.assertIsNotNone(confirmed_transaction.confirmed_at)
    
    def test_payment_retry_limit_enforced(self):
        """Test maximum 3 retry attempts"""
        transaction = PaymentTransaction.objects.create(
            batch=self.batch,
            status=PaymentTransaction.Status.FAILED,
            processor_type=PaymentTransaction.ProcessorType.MANUAL,
            total_amount=Decimal('1000.00'),
            initiated_by=self.admin,
            retry_count=3  # Already at max
        )
        
        # Cannot retry beyond limit
        with self.assertRaises(PaymentValidationError) as context:
            PaymentTransactionService.retry_payment(
                transaction=transaction,
                actor=self.admin
            )
        
        self.assertIn('Maximum retry limit', str(context.exception))
    
    def test_payment_retry_creates_new_transaction(self):
        """Test retry creates new transaction with incremented count"""
        transaction = PaymentTransaction.objects.create(
            batch=self.batch,
            status=PaymentTransaction.Status.FAILED,
            processor_type=PaymentTransaction.ProcessorType.MANUAL,
            total_amount=Decimal('1000.00'),
            initiated_by=self.admin,
            retry_count=0,
            failure_reason='Invalid account'
        )
        
        # Retry payment
        new_transaction = PaymentTransactionService.retry_payment(
            transaction=transaction,
            actor=self.admin,
            notes='Retrying with updated account'
        )
        
        self.assertEqual(new_transaction.retry_count, 1)
        self.assertEqual(new_transaction.parent_transaction, transaction)
        self.assertEqual(new_transaction.status, PaymentTransaction.Status.PENDING)


class TaxDocumentTests(TestCase):
    """Test 1099-NEC generation and IRS compliance"""
    
    def setUp(self):
        self.consultant = User.objects.create_user(username='consultant1', email='c1@test.com')
        self.admin = User.objects.create_user(username='admin1', email='admin@test.com', is_staff=True)
        
        # Create approved W-9
        w9_data = {
            'legal_name': 'John Doe',
            'entity_type': 'INDIVIDUAL',
            'tin_type': 'SSN',
            'tin': '123-45-6789',
            'address_line1': '123 Main St',
            'city': 'New York',
            'state': 'NY',
            'zip_code': '10001'
        }
        self.w9 = W9Service.submit_w9(
            consultant=self.consultant,
            w9_data=w9_data,
            actor=self.consultant
        )
        W9Service.approve_w9(self.w9, self.admin)
        
        # Create payment transactions totaling $1000
        period = PayoutPeriod.objects.create(
            name='2025',
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31)
        )
        batch = PayoutBatch.objects.create(
            period=period,
            reference_number='PAY-2025-001',
            status='RELEASED',
            run_date=date(2025, 12, 31),
            created_by=self.admin
        )
        payout = Payout.objects.create(
            batch=batch,
            consultant=self.consultant,
            total_commission=Decimal('1000.00'),
        )
        self.transaction = PaymentTransaction.objects.create(
            batch=batch,
            status=PaymentTransaction.Status.COMPLETED,
            total_amount=Decimal('1000.00'),
            completed_at=timezone.make_aware(timezone.datetime(2025, 12, 31))
        )
    
    def test_1099_generation_requires_approved_w9(self):
        """Cannot generate 1099 without approved W-9"""
        consultant_no_w9 = User.objects.create_user(username='consultant2', email='c2@test.com')
        
        with self.assertRaises(PaymentValidationError) as context:
            TaxDocumentService.generate_1099_nec(
                consultant=consultant_no_w9,
                tax_year=2025,
                generated_by=self.admin
            )
        
        self.assertIn('no W-9', str(context.exception))
    
    def test_1099_generation_threshold_600_dollars(self):
        """1099 only generated for payments >= $600"""
        # Create consultant with payments < $600
        consultant2 = User.objects.create_user(username='consultant2', email='c2@test.com')
        w9_data = {
            'legal_name': 'Jane Doe',
            'entity_type': 'INDIVIDUAL',
            'tin_type': 'SSN',
            'tin': '987-65-4321',
            'address_line1': '456 Oak St',
            'city': 'Boston',
            'state': 'MA',
            'zip_code': '02101'
        }
        w9 = W9Service.submit_w9(consultant=consultant2, w9_data=w9_data, actor=consultant2)
        W9Service.approve_w9(w9, self.admin)
        
        # Create payment < $600
        period = PayoutPeriod.objects.create(
            name='2025-Q1',
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31)
        )
        batch = PayoutBatch.objects.create(
            period=period,
            reference_number='PAY-2025-002',
            status='RELEASED',
            run_date=date(2025, 3, 31),
            created_by=self.admin
        )
        payout = Payout.objects.create(
            batch=batch,
            consultant=consultant2,
            total_commission=Decimal('500.00')
        )
        PaymentTransaction.objects.create(
            batch=batch,
            status=PaymentTransaction.Status.COMPLETED,
            total_amount=Decimal('500.00'),
            completed_at=timezone.make_aware(timezone.datetime(2025, 3, 31))
        )
        
        # Should fail threshold check
        with self.assertRaises(PaymentValidationError) as context:
            TaxDocumentService.generate_1099_nec(
                consultant=consultant2,
                tax_year=2025,
                generated_by=self.admin
            )
        
        self.assertIn('below $600 threshold', str(context.exception))
    
    def test_1099_exempt_entities_excluded(self):
        """C-Corp and S-Corp are exempt from 1099"""
        # Update W-9 to C-Corp
        self.w9.entity_type = W9Information.EntityType.C_CORP
        self.w9.save()
        
        with self.assertRaises(PaymentValidationError) as context:
            TaxDocumentService.generate_1099_nec(
                consultant=self.consultant,
                tax_year=2025,
                generated_by=self.admin
            )
        
        self.assertIn('exempt from 1099', str(context.exception))


class Phase4IntegrationTests(TestCase):
    """Test Phase 4 → Phase 5 integration via signals"""
    
    def setUp(self):
        self.consultant = User.objects.create_user(username='consultant1', email='c1@test.com')
        self.admin = User.objects.create_user(username='admin1', email='admin@test.com', is_staff=True)
        
        self.period = PayoutPeriod.objects.create(
            name='Jan 2026',
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31)
        )
    
    def test_batch_release_creates_payment_transaction(self):
        """PayoutBatch RELEASED → PaymentTransaction auto-created"""
        # Create batch in DRAFT
        batch = PayoutBatch.objects.create(
            period=self.period,
            reference_number='PAY-JAN-2026-001',
            status='DRAFT',
            run_date=date(2026, 1, 31),
            created_by=self.admin
        )
        
        # Create payout
        Payout.objects.create(
            batch=batch,
            consultant=self.consultant,
            total_commission=Decimal('1000.00'),
        )
        
        # No transaction yet
        self.assertFalse(hasattr(batch, 'payment_transaction'))
        
        # Release batch
        batch.status = 'RELEASED'
        batch.save()
        
        # Transaction should be auto-created
        batch.refresh_from_db()
        self.assertTrue(hasattr(batch, 'payment_transaction'))
        self.assertEqual(batch.payment_transaction.status, PaymentTransaction.Status.PENDING)
        self.assertEqual(batch.payment_transaction.total_amount, Decimal('1000.00'))
    
    def test_payment_completion_updates_payouts(self):
        """PaymentTransaction COMPLETED → Payout.paid_at updated"""
        # Create batch and payout
        batch = PayoutBatch.objects.create(
            period=self.period,
            reference_number='PAY-JAN-2026-002',
            status='RELEASED',
            run_date=date(2026, 1, 31),
            created_by=self.admin
        )
        payout = Payout.objects.create(
            batch=batch,
            consultant=self.consultant,
            total_commission=Decimal('1000.00'),
        )
        
        # Create transaction
        transaction = PaymentTransaction.objects.create(
            batch=batch,
            status=PaymentTransaction.Status.PENDING,
            total_amount=Decimal('1000.00'),
            initiated_by=self.admin
        )
        
        # Payout should not have paid_at yet
        payout.refresh_from_db()
        self.assertIsNone(payout.paid_at)
        
        # Complete transaction
        transaction.status = PaymentTransaction.Status.COMPLETED
        transaction.confirmed_at = timezone.now()
        transaction.external_reference = 'BANK-TX-12345'
        transaction.save()
        
        # Payout should now have paid_at
        payout.refresh_from_db()
        self.assertIsNotNone(payout.paid_at)
        self.assertEqual(payout.payment_reference, 'BANK-TX-12345')
    
    def test_idempotency_no_duplicate_transactions(self):
        """Repeated saves don't create duplicate transactions"""
        batch = PayoutBatch.objects.create(
            period=self.period,
            reference_number='PAY-JAN-2026-003',
            status='RELEASED',
            run_date=date(2026, 1, 31),
            created_by=self.admin
        )
        
        Payout.objects.create(
            batch=batch,
            consultant=self.consultant,
            total_commission=Decimal('1000.00'),
        )
        
        # First save creates transaction
        batch.refresh_from_db()
        transaction_id = batch.payment_transaction.id
        
        # Save again
        batch.save()
        
        # Should still be same transaction
        batch.refresh_from_db()
        self.assertEqual(batch.payment_transaction.id, transaction_id)
        
        # Verify only one transaction exists
        transaction_count = PaymentTransaction.objects.filter(batch=batch).count()
        self.assertEqual(transaction_count, 1)


class AuditLoggingTests(TestCase):
    """Test audit trail completeness"""
    
    def setUp(self):
        self.consultant = User.objects.create_user(username='consultant1', email='c1@test.com')
        self.admin = User.objects.create_user(username='admin1', email='admin@test.com', is_staff=True)
    
    def test_payment_method_creation_logged(self):
        """Payment method creation creates audit log"""
        initial_count = PaymentAuditLog.objects.count()
        
        method_data = {
            'method_type': 'ACH',
            'account_holder_name': 'John Doe',
            'bank_name': 'Test Bank',
            'routing_number': '123456789',
            'account_number': '9876543210',
            'account_type': 'CHECKING'
        }
        
        PaymentMethodService.create_payment_method(
            consultant=self.consultant,
            method_data=method_data,
            actor=self.consultant
        )
        
        # Audit log should be created
        self.assertEqual(PaymentAuditLog.objects.count(), initial_count + 1)
        
        log = PaymentAuditLog.objects.latest('timestamp')
        self.assertEqual(log.action_type, PaymentAuditLog.ActionType.PAYMENT_METHOD_CREATED)
        self.assertEqual(log.actor, self.consultant)
    
    def test_w9_approval_logged(self):
        """W-9 approval creates audit log"""
        w9_data = {
            'legal_name': 'John Doe',
            'entity_type': 'INDIVIDUAL',
            'tin_type': 'SSN',
            'tin': '123-45-6789',
            'address_line1': '123 Main St',
            'city': 'New York',
            'state': 'NY',
            'zip_code': '10001'
        }
        
        w9 = W9Service.submit_w9(consultant=self.consultant, w9_data=w9_data, actor=self.consultant)
        
        initial_count = PaymentAuditLog.objects.count()
        
        W9Service.approve_w9(w9=w9, approved_by=self.admin)
        
        # Audit log should be created
        self.assertEqual(PaymentAuditLog.objects.count(), initial_count + 1)
        
        log = PaymentAuditLog.objects.latest('timestamp')
        self.assertEqual(log.action_type, PaymentAuditLog.ActionType.W9_APPROVED)
        self.assertEqual(log.actor, self.admin)
