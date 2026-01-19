from rest_framework import viewsets, status, permissions, decorators, mixins
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.http import FileResponse, Http404
from django.db.models import Sum, Q
from decimal import Decimal

from .models import (
    PaymentMethod,
    PaymentTransaction,
    W9Information,
    TaxDocument,
    PaymentReconciliation
)
from .serializers import (
    PaymentMethodListSerializer,
    PaymentMethodCreateSerializer,
    PaymentMethodUpdateSerializer,
    PaymentTransactionListSerializer,
    PaymentTransactionDetailSerializer,
    PaymentConfirmSerializer,
    PaymentFailSerializer,
    PaymentRetrySerializer,
    PaymentCancelSerializer,
    W9InformationSerializer,
    W9SubmitSerializer,
    W9ApproveSerializer,
    W9RejectSerializer,
    TaxDocumentListSerializer,
    TaxDocumentDetailSerializer,
    TaxDocumentGenerateSerializer,
    TaxDocumentMarkFiledSerializer,
    PaymentReconciliationListSerializer,
    PaymentReconciliationDetailSerializer,
    ReconciliationCreateSerializer,
    ReconciliationResolveSerializer
)
from .services import (
    PaymentMethodService,
    PaymentTransactionService,
    W9Service,
    TaxDocumentService,
    ReconciliationService,
    PaymentError,
    PaymentPermissionError,
    PaymentStateError,
    PaymentValidationError
)
from payouts.models import PayoutBatch


class IsFinanceAdmin(permissions.BasePermission):
    """Check if user is Admin or Finance"""
    def has_permission(self, request, view):
        return (
            request.user.is_staff or
            request.user.groups.filter(name__in=['Admins', 'Finance']).exists()
        )


class PaymentMethodViewSet(viewsets.ModelViewSet):
    """
    API endpoints for payment methods.
    Consultants: own methods only
    Finance/Admin: all methods
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        qs = PaymentMethod.objects.all().select_related('consultant', 'verified_by')
        
        # Finance/Admin see all, consultants see own
        if user.is_staff or user.groups.filter(name__in=['Admins', 'Finance']).exists():
            # Apply filters
            status_filter = self.request.query_params.get('status')
            consultant_id = self.request.query_params.get('consultant_id')
            
            if status_filter:
                qs = qs.filter(status=status_filter)
            if consultant_id:
                qs = qs.filter(consultant_id=consultant_id)
            
            return qs
        
        return qs.filter(consultant=user)
    
    def get_serializer_class(self):
        if self.action == 'create':
            return PaymentMethodCreateSerializer
        if self.action in ['update', 'partial_update']:
            return PaymentMethodUpdateSerializer
        return PaymentMethodListSerializer
    
    def create(self, request, *args, **kwargs):
        """POST /api/payments/methods/"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            payment_method = PaymentMethodService.create_payment_method(
                consultant=request.user,
                method_data=serializer.validated_data,
                actor=request.user
            )
            
            response_serializer = PaymentMethodListSerializer(payment_method)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            
        except PaymentValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    def update(self, request, *args, **kwargs):
        """PATCH /api/payments/methods/{id}/"""
        payment_method = self.get_object()
        
        # Check ownership
        if payment_method.consultant != request.user:
            is_admin = request.user.is_staff or request.user.groups.filter(name__in=['Admins', 'Finance']).exists()
            if not is_admin:
                return Response({"detail": "Cannot update another consultant's payment method"}, status=status.HTTP_403_FORBIDDEN)
        
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        # Update allowed fields
        for field, value in serializer.validated_data.items():
            setattr(payment_method, field, value)
        payment_method.save()
        
        response_serializer = PaymentMethodListSerializer(payment_method)
        return Response(response_serializer.data)
    
    @decorators.action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsFinanceAdmin])
    def verify(self, request, pk=None):
        """POST /api/payments/methods/{id}/verify/"""
        payment_method = self.get_object()
        notes = request.data.get('notes', '')
        
        try:
            updated_method = PaymentMethodService.verify_payment_method(
                payment_method=payment_method,
                verified_by=request.user,
                notes=notes
            )
            
            serializer = PaymentMethodListSerializer(updated_method)
            return Response(serializer.data)
            
        except PaymentStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @decorators.action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsFinanceAdmin])
    def inactivate(self, request, pk=None):
        """POST /api/payments/methods/{id}/inactivate/"""
        payment_method = self.get_object()
        reason = request.data.get('reason', '')
        
        try:
            updated_method = PaymentMethodService.inactivate_payment_method(
                payment_method=payment_method,
                actor=request.user,
                reason=reason
            )
            
            serializer = PaymentMethodListSerializer(updated_method)
            return Response(serializer.data)
            
        except PaymentStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @decorators.action(detail=True, methods=['post'], url_path='set-default')
    def set_default(self, request, pk=None):
        """POST /api/payments/methods/{id}/set-default/"""
        payment_method = self.get_object()
        
        # Check ownership
        if payment_method.consultant != request.user:
            is_admin = request.user.is_staff or request.user.groups.filter(name__in=['Admins', 'Finance']).exists()
            if not is_admin:
                return Response({"detail": "Cannot set default for another consultant"}, status=status.HTTP_403_FORBIDDEN)
        
        try:
            updated_method = PaymentMethodService.set_default_payment_method(
                payment_method=payment_method,
                actor=request.user
            )
            
            serializer = PaymentMethodListSerializer(updated_method)
            return Response(serializer.data)
            
        except PaymentValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class W9ViewSet(viewsets.GenericViewSet):
    """
    API endpoints for W-9 management.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = W9InformationSerializer
    
    def get_queryset(self):
        user = self.request.user
        qs = W9Information.objects.all().select_related('consultant', 'reviewed_by')
        
        # Finance/Admin see all, consultants see own
        if user.is_staff or user.groups.filter(name__in=['Admins', 'Finance']).exists():
            consultant_id = self.request.query_params.get('consultant_id')
            if consultant_id:
                qs = qs.filter(consultant_id=consultant_id)
            return qs
        
        return qs.filter(consultant=user)
    
    def list(self, request):
        """GET /api/payments/w9/"""
        # For consultants, return their own W-9 or 404
        if not (request.user.is_staff or request.user.groups.filter(name__in=['Admins', 'Finance']).exists()):
            try:
                w9 = W9Information.objects.get(consultant=request.user)
                serializer = self.get_serializer(w9)
                return Response(serializer.data)
            except W9Information.DoesNotExist:
                return Response({"detail": "W-9 not found"}, status=status.HTTP_404_NOT_FOUND)
        
        # Finance/Admin can list all
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    def create(self, request):
        """POST /api/payments/w9/"""
        serializer = W9SubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            w9 = W9Service.submit_w9(
                consultant=request.user,
                w9_data=serializer.validated_data,
                actor=request.user
            )
            
            response_serializer = W9InformationSerializer(w9)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            
        except PaymentValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @decorators.action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsFinanceAdmin])
    def approve(self, request, pk=None):
        """POST /api/payments/w9/{id}/approve/"""
        w9 = get_object_or_404(W9Information, pk=pk)
        notes = request.data.get('notes', '')
        
        try:
            updated_w9 = W9Service.approve_w9(
                w9=w9,
                approved_by=request.user,
                notes=notes
            )
            
            serializer = W9InformationSerializer(updated_w9)
            return Response(serializer.data)
            
        except PaymentStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @decorators.action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsFinanceAdmin])
    def reject(self, request, pk=None):
        """POST /api/payments/w9/{id}/reject/"""
        w9 = get_object_or_404(W9Information, pk=pk)
        
        serializer = W9RejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            updated_w9 = W9Service.reject_w9(
                w9=w9,
                rejected_by=request.user,
                reason=serializer.validated_data['reason']
            )
            
            response_serializer = W9InformationSerializer(updated_w9)
            return Response(response_serializer.data)
            
        except PaymentStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PaymentValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PaymentTransactionViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    API endpoints for payment transactions (Finance/Admin only).
    """
    permission_classes = [permissions.IsAuthenticated, IsFinanceAdmin]
    
    def get_queryset(self):
        qs = PaymentTransaction.objects.all().select_related('batch', 'payment_method', 'initiated_by', 'confirmed_by')
        
        # Apply filters
        status_filter = self.request.query_params.get('status')
        batch_id = self.request.query_params.get('batch_id')
        
        if status_filter:
            qs = qs.filter(status=status_filter)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        
        return qs.order_by('-created_at')
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PaymentTransactionDetailSerializer
        return PaymentTransactionListSerializer
    
    @decorators.action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """POST /api/payments/transactions/{id}/confirm/"""
        transaction = self.get_object()
        
        serializer = PaymentConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            updated_transaction = PaymentTransactionService.confirm_payment(
                transaction=transaction,
                confirmed_by=request.user,
                external_reference=serializer.validated_data['external_reference'],
                confirmation_code=serializer.validated_data.get('confirmation_code', ''),
                notes=serializer.validated_data.get('notes', '')
            )
            
            response_serializer = PaymentTransactionDetailSerializer(updated_transaction)
            return Response(response_serializer.data)
            
        except PaymentStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PaymentValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @decorators.action(detail=True, methods=['post'])
    def fail(self, request, pk=None):
        """POST /api/payments/transactions/{id}/fail/"""
        transaction = self.get_object()
        
        serializer = PaymentFailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            updated_transaction = PaymentTransactionService.mark_payment_failed(
                transaction=transaction,
                actor=request.user,
                failure_reason=serializer.validated_data['failure_reason']
            )
            
            response_serializer = PaymentTransactionDetailSerializer(updated_transaction)
            return Response(response_serializer.data)
            
        except PaymentStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PaymentValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @decorators.action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """POST /api/payments/transactions/{id}/retry/"""
        transaction = self.get_object()
        
        serializer = PaymentRetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            payment_method = None
            if 'payment_method_id' in serializer.validated_data:
                payment_method = get_object_or_404(PaymentMethod, pk=serializer.validated_data['payment_method_id'])
            
            new_transaction = PaymentTransactionService.retry_payment(
                transaction=transaction,
                actor=request.user,
                payment_method=payment_method,
                notes=serializer.validated_data.get('notes', '')
            )
            
            response_serializer = PaymentTransactionDetailSerializer(new_transaction)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            
        except PaymentStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PaymentValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @decorators.action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """POST /api/payments/transactions/{id}/cancel/"""
        transaction = self.get_object()
        
        serializer = PaymentCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            updated_transaction = PaymentTransactionService.cancel_payment(
                transaction=transaction,
                actor=request.user,
                reason=serializer.validated_data.get('reason', '')
            )
            
            response_serializer = PaymentTransactionDetailSerializer(updated_transaction)
            return Response(response_serializer.data)
            
        except PaymentStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class TaxDocumentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    API endpoints for tax documents.
    Consultants: own documents only
    Finance/Admin: all documents
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        qs = TaxDocument.objects.all().select_related('consultant', 'generated_by')
        
        # Finance/Admin see all, consultants see own
        if user.is_staff or user.groups.filter(name__in=['Admins', 'Finance']).exists():
            # Apply filters
            tax_year = self.request.query_params.get('tax_year')
            consultant_id = self.request.query_params.get('consultant_id')
            document_type = self.request.query_params.get('document_type')
            
            if tax_year:
                qs = qs.filter(tax_year=tax_year)
            if consultant_id:
                qs = qs.filter(consultant_id=consultant_id)
            if document_type:
                qs = qs.filter(document_type=document_type)
            
            return qs
        
        return qs.filter(consultant=user)
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return TaxDocumentDetailSerializer
        return TaxDocumentListSerializer
    
    @decorators.action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsFinanceAdmin])
    def generate(self, request):
        """POST /api/payments/tax-documents/generate/"""
        serializer = TaxDocumentGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        tax_year = serializer.validated_data['tax_year']
        consultant_ids = serializer.validated_data.get('consultant_ids', [])
        
        generated_docs = []
        errors = []
        
        # If no consultant_ids specified, generate for all eligible
        if not consultant_ids:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            consultants = User.objects.filter(w9_information__status='APPROVED')
        else:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            consultants = User.objects.filter(id__in=consultant_ids)
        
        for consultant in consultants:
            try:
                tax_doc = TaxDocumentService.generate_1099_nec(
                    consultant=consultant,
                    tax_year=tax_year,
                    generated_by=request.user
                )
                generated_docs.append(tax_doc)
            except PaymentValidationError as e:
                errors.append({'consultant_id': consultant.id, 'error': str(e)})
            except PaymentError as e:
                errors.append({'consultant_id': consultant.id, 'error': str(e)})
        
        response_serializer = TaxDocumentListSerializer(generated_docs, many=True)
        return Response({
            'generated_count': len(generated_docs),
            'documents': response_serializer.data,
            'errors': errors
        }, status=status.HTTP_201_CREATED)
    
    @decorators.action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """GET /api/payments/tax-documents/{id}/download/"""
        tax_doc = self.get_object()
        
        # Check ownership
        if tax_doc.consultant != request.user:
            is_admin = request.user.is_staff or request.user.groups.filter(name__in=['Admins', 'Finance']).exists()
            if not is_admin:
                return Response({"detail": "Cannot download another consultant's tax document"}, status=status.HTTP_403_FORBIDDEN)
        
        # TODO: Return actual PDF file
        # For now, return placeholder response
        return Response({"detail": "PDF download not yet implemented (placeholder)"}, status=status.HTTP_501_NOT_IMPLEMENTED)
    
    @decorators.action(detail=True, methods=['post'], url_path='mark-sent', permission_classes=[permissions.IsAuthenticated, IsFinanceAdmin])
    def mark_sent(self, request, pk=None):
        """POST /api/payments/tax-documents/{id}/mark-sent/"""
        tax_doc = self.get_object()
        
        try:
            updated_doc = TaxDocumentService.mark_sent(
                tax_doc=tax_doc,
                actor=request.user
            )
            
            serializer = TaxDocumentDetailSerializer(updated_doc)
            return Response(serializer.data)
            
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @decorators.action(detail=True, methods=['post'], url_path='mark-filed', permission_classes=[permissions.IsAuthenticated, IsFinanceAdmin])
    def mark_filed(self, request, pk=None):
        """POST /api/payments/tax-documents/{id}/mark-filed/"""
        tax_doc = self.get_object()
        
        serializer = TaxDocumentMarkFiledSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            updated_doc = TaxDocumentService.mark_filed(
                tax_doc=tax_doc,
                actor=request.user,
                filing_confirmation=serializer.validated_data.get('filing_confirmation', '')
            )
            
            response_serializer = TaxDocumentDetailSerializer(updated_doc)
            return Response(response_serializer.data)
            
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ReconciliationViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """
    API endpoints for payment reconciliation (Finance/Admin only).
    """
    permission_classes = [permissions.IsAuthenticated, IsFinanceAdmin]
    
    def get_queryset(self):
        qs = PaymentReconciliation.objects.all().select_related('batch', 'transaction', 'reconciled_by')
        
        # Apply filters
        status_filter = self.request.query_params.get('status')
        batch_id = self.request.query_params.get('batch_id')
        
        if status_filter:
            qs = qs.filter(status=status_filter)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        
        return qs.order_by('-reconciliation_date')
    
    def get_serializer_class(self):
        if self.action == 'create':
            return ReconciliationCreateSerializer
        return PaymentReconciliationListSerializer
    
    def create(self, request):
        """POST /api/payments/reconciliations/"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            batch = get_object_or_404(PayoutBatch, pk=serializer.validated_data['batch_id'])
            transaction = None
            if 'transaction_id' in serializer.validated_data:
                transaction = get_object_or_404(PaymentTransaction, pk=serializer.validated_data['transaction_id'])
            
            reconciliation = ReconciliationService.create_reconciliation(
                batch=batch,
                reconciled_by=request.user,
                reconciliation_date=serializer.validated_data['reconciliation_date'],
                actual_amount=serializer.validated_data['actual_amount'],
                transaction=transaction,
                notes=serializer.validated_data.get('notes', '')
            )
            
            response_serializer = PaymentReconciliationDetailSerializer(reconciliation)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @decorators.action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """POST /api/payments/reconciliations/{id}/resolve/"""
        reconciliation = get_object_or_404(PaymentReconciliation, pk=pk)
        
        serializer = ReconciliationResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            updated_reconciliation = ReconciliationService.resolve_discrepancy(
                reconciliation=reconciliation,
                actor=request.user,
                resolution_notes=serializer.validated_data['resolution_notes']
            )
            
            response_serializer = PaymentReconciliationDetailSerializer(updated_reconciliation)
            return Response(response_serializer.data)
            
        except PaymentStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PaymentError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @decorators.action(detail=False, methods=['get'], url_path='reports/unreconciled')
    def unreconciled_report(self, request):
        """GET /api/payments/reconciliations/reports/unreconciled/"""
        # Find batches that are RELEASED but have no RECONCILED reconciliation
        from django.db.models import Q, Exists, OuterRef
        
        reconciled_batches = PaymentReconciliation.objects.filter(
            batch=OuterRef('pk'),
            status=PaymentReconciliation.Status.RECONCILED
        )
        
        unreconciled_batches = PayoutBatch.objects.filter(
            status='RELEASED'
        ).exclude(
            Exists(reconciled_batches)
        ).select_related('created_by')
        
        batches_data = []
        for batch in unreconciled_batches:
            transaction_status = 'NO_TRANSACTION'
            if hasattr(batch, 'payment_transaction'):
                transaction_status = batch.payment_transaction.status
            
            batches_data.append({
                'batch_id': batch.id,
                'reference_number': batch.reference_number,
                'released_at': batch.released_at,
                'total_amount': str(batch.payouts.aggregate(total=Sum('total_commission'))['total'] or 0),
                'transaction_status': transaction_status,
                'reconciliation_status': 'PENDING'
            })
        
        return Response({
            'count': len(batches_data),
            'batches': batches_data
        })
    
    @decorators.action(detail=False, methods=['get'], url_path='reports/discrepancies')
    def discrepancies_report(self, request):
        """GET /api/payments/reconciliations/reports/discrepancies/"""
        discrepancies = PaymentReconciliation.objects.filter(
            status=PaymentReconciliation.Status.DISCREPANCY
        ).select_related('batch')
        
        discrepancies_data = []
        for recon in discrepancies:
            discrepancies_data.append({
                'reconciliation_id': recon.id,
                'batch_reference': recon.batch.reference_number,
                'expected_amount': str(recon.expected_amount),
                'actual_amount': str(recon.actual_amount),
                'discrepancy_amount': str(recon.discrepancy_amount),
                'reconciliation_date': recon.reconciliation_date
            })
        
        return Response({
            'count': len(discrepancies_data),
            'discrepancies': discrepancies_data
        })
