from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status
from decimal import Decimal
from commissions.models import Commission, CommissionApproval, ApprovalHistory
from commissions.approvals.services import (
    ApprovalSubmissionService,
    ApprovalDecisionService,
    ApprovalPaymentService,
    ApprovalError
)

User = get_user_model()

class ApprovalWorkflowTests(APITestCase):
    def setUp(self):
        # Create users
        self.admin = User.objects.create_superuser(username='admin', password='password123', email='admin@test.com')
        self.consultant = User.objects.create_user(username='consultant', password='password123')
        self.manager = User.objects.create_user(username='manager', password='password123')
        
        # Add manager to a group if needed, or just use is_staff for simplicity in some tests
        # For our service logic, we check is_staff or 'Admins' group.
        
        # Create a commission in Draft state
        self.commission = Commission.objects.create(
            commission_type='base',
            consultant=self.consultant,
            transaction_date=timezone.now().date(),
            sale_amount=Decimal('1000.00'),
            commission_rate=Decimal('10.00'),
            calculated_amount=Decimal('100.00'),
            reference_number='TEST-001',
            state='draft',
            created_by=self.admin
        )

    def test_01_submit_workflow(self):
        """Test submitting a commission moves state and captures approver"""
        # Set a manager for the consultant in Phase 1 sense (mocking it by setting commission.manager or similar)
        # Actually our service uses commission.manager if assigned_approver is null
        self.commission.manager = self.manager
        self.commission.save()
        
        ApprovalSubmissionService.submit(self.commission, self.consultant)
        
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.state, 'submitted')
        
        approval = self.commission.approval
        self.assertEqual(approval.assigned_approver, self.manager)
        
        # Check history
        history = ApprovalHistory.objects.filter(approval_record=approval, action='SUBMIT').first()
        self.assertIsNotNone(history)
        self.assertEqual(history.from_state, 'draft')
        self.assertEqual(history.to_state, 'submitted')
        self.assertEqual(history.actor, self.consultant)

    def test_02_approve_workflow_permission(self):
        """Only assigned approver or admin can approve"""
        self.commission.manager = self.manager
        self.commission.save()
        ApprovalSubmissionService.submit(self.commission, self.consultant)
        
        # Consultant tries to approve own
        with self.assertRaises(ApprovalError):
            ApprovalDecisionService.approve(self.commission, self.consultant)
            
        # Random user tries to approve
        random_user = User.objects.create_user(username='random', password='password123')
        with self.assertRaises(ApprovalError):
            ApprovalDecisionService.approve(self.commission, random_user)
            
        # Manager approves
        ApprovalDecisionService.approve(self.commission, self.manager)
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.state, 'approved')
        self.assertEqual(self.commission.approved_by, self.manager)

    def test_03_reject_requires_reason(self):
        """Rejection must have a reason"""
        self.commission.manager = self.manager
        self.commission.save()
        ApprovalSubmissionService.submit(self.commission, self.consultant)
        
        with self.assertRaises(ApprovalError):
            ApprovalDecisionService.reject(self.commission, self.manager, "")
            
        ApprovalDecisionService.reject(self.commission, self.manager, "Missing docs")
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.state, 'rejected')

    def test_04_payment_admin_only(self):
        """Only admin can mark as paid"""
        self.commission.manager = self.manager
        self.commission.save()
        ApprovalSubmissionService.submit(self.commission, self.consultant)
        ApprovalDecisionService.approve(self.commission, self.manager)
        
        # Manager tries to pay
        with self.assertRaises(ApprovalError):
            ApprovalPaymentService.mark_as_paid(self.commission, self.manager)
            
        # Admin pays
        ApprovalPaymentService.mark_as_paid(self.commission, self.admin)
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.state, 'paid')
        self.assertIsNotNone(self.commission.paid_at)

    def test_05_invalid_transitions(self):
        """Cannot skip states"""
        # Draft -> Approved (Skip Submitted)
        with self.assertRaises(ApprovalError):
            ApprovalDecisionService.approve(self.commission, self.admin)
            
        # Draft -> Paid (Skip everything)
        with self.assertRaises(ApprovalError):
            ApprovalPaymentService.mark_as_paid(self.commission, self.admin)

    def test_06_override_auto_approval(self):
        """Overrides should inherit approval from base"""
        # Create base + override
        base = self.commission
        base.manager = self.manager
        base.save()
        
        override = Commission.objects.create(
            commission_type='override',
            consultant=self.consultant,
            manager=self.manager,
            transaction_date=timezone.now().date(),
            sale_amount=Decimal('1000.00'),
            commission_rate=Decimal('2.00'),
            calculated_amount=Decimal('20.00'),
            reference_number='TEST-001-OVR',
            state='draft',
            parent_commission=base
        )
        
        # Submit both
        ApprovalSubmissionService.submit(base, self.consultant)
        ApprovalSubmissionService.submit(override, self.consultant)
        
        # Approve base
        ApprovalDecisionService.approve(base, self.manager)
        
        base.refresh_from_db()
        override.refresh_from_db()
        
        self.assertEqual(base.state, 'approved')
        self.assertEqual(override.state, 'approved')
        
        # Check override history notes
        hist = ApprovalHistory.objects.filter(approval_record__commission=override, action='APPROVE').first()
        self.assertIn("Auto-approved", hist.notes)

    def test_07_resubmit_from_rejected(self):
        """Can resubmit after a rejection"""
        self.commission.manager = self.manager
        self.commission.save()
        
        ApprovalSubmissionService.submit(self.commission, self.consultant)
        ApprovalDecisionService.reject(self.commission, self.manager, "Fixed it")
        
        self.assertEqual(self.commission.state, 'rejected')
        
        # Resubmit
        ApprovalSubmissionService.submit(self.commission, self.consultant)
        self.assertEqual(self.commission.state, 'submitted')

class ApprovalAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin', password='password123', email='admin@test.com')
        self.consultant = User.objects.create_user(username='consultant', password='password123')
        self.manager = User.objects.create_user(username='manager', password='password123')
        
        self.commission = Commission.objects.create(
            commission_type='base',
            consultant=self.consultant,
            manager=self.manager,
            transaction_date=timezone.now().date(),
            sale_amount=Decimal('1000.00'),
            commission_rate=Decimal('10.00'),
            calculated_amount=Decimal('100.00'),
            reference_number='API-TEST-001',
            state='draft'
        )
        
    def test_api_workflow_end_to_end(self):
        """Full API flow: Submit -> Approve -> Paid"""
        # 1. Login as consultant and submit
        self.client.force_authenticate(user=self.consultant)
        url = f'/api/commissions/{self.commission.id}/submit/'
        response = self.client.post(url, {"notes": "Please check"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # 2. Login as manager and check pending
        self.client.force_authenticate(user=self.manager)
        pending_url = '/api/commissions/approvals/pending/'
        response = self.client.get(pending_url)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.commission.id)
        
        # 3. Manager approves
        approve_url = f'/api/commissions/{self.commission.id}/approve/'
        response = self.client.post(approve_url, {"notes": "Looks good"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # 4. Admin marks as paid
        self.client.force_authenticate(user=self.admin)
        pay_url = f'/api/commissions/{self.commission.id}/mark-paid/'
        response = self.client.post(pay_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # 5. Check timeline
        timeline_url = f'/api/commissions/{self.commission.id}/timeline/'
        response = self.client.get(timeline_url)
        self.assertEqual(len(response.data), 3) # Submit, Approve, Paid
        self.assertEqual(response.data[0]['action'], 'SUBMIT')
        self.assertEqual(response.data[1]['action'], 'APPROVE')
        self.assertEqual(response.data[2]['action'], 'PAID')

    def test_api_rejection_validation(self):
        """API Rejection requires reason"""
        self.client.force_authenticate(user=self.consultant)
        self.client.post(f'/api/commissions/{self.commission.id}/submit/')
        
        self.client.force_authenticate(user=self.manager)
        url = f'/api/commissions/{self.commission.id}/reject/'
        response = self.client.post(url, {"rejection_reason": ""})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rejection_reason", response.data)
