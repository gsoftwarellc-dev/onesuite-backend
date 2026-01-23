from rest_framework import views, status, permissions
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db import transaction
from commissions.models import Commission, CommissionApproval, ApprovalHistory
from commissions.serializers import (
    CommissionReadSerializer,
    CommissionApprovalSerializer,
    ApprovalHistorySerializer,
    ApprovalRejectSerializer,
    ApprovalPaySerializer,
    ApprovalActionBaseSerializer
)
from commissions.approvals.services import (
    ApprovalSubmissionService,
    ApprovalDecisionService,
    ApprovalPaymentService,
    ApprovalError
)

class PendingApprovalsListView(views.APIView):
    """
    GET /api/commissions/approvals/pending/
    Returns commissions pending approval for the current user (Manager/Admin).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        
        # Admins see everything submitted
        if user.is_staff or user.groups.filter(name='Admins').exists():
            queryset = Commission.objects.filter(state='submitted')
        else:
        # Status Filter Logic
        status_param = request.query_params.get('status', 'submitted')
        
        # Managers see what is assigned to them OR what belongs to their team
        from django.db.models import Q
        from hierarchy.models import ReportingLine
        
        # 1. Direct assignments via Approval record
        filter_q = Q(approval__assigned_approver=user)
        
        # 2. Team members (fallback based on hierarchy)
        # Find all consultants who report to this user
        team_member_ids = ReportingLine.objects.filter(
            manager=user, 
            is_active=True
        ).values_list('consultant_id', flat=True)
        
        if team_member_ids:
            filter_q |= Q(consultant_id__in=team_member_ids)
            
        # 3. Also include commissions where user is explicitly set as 'manager' field (for overrides)
        filter_q |= Q(manager=user)
        
        queryset = Commission.objects.filter(filter_q).distinct()
        
        # Apply Status Filter
        if status_param != 'all':
            queryset = queryset.filter(state=status_param)
            
        serializer = CommissionReadSerializer(queryset, many=True)
        return Response(serializer.data)


class CommissionApprovalDetailView(views.APIView):
    """
    GET /api/commissions/<id>/approval/
    Returns current approval state + nested history.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        commission = get_object_or_404(Commission, pk=pk)
        
        # Security: Owner, Assigned Approver, or Admin
        is_owner = commission.consultant == request.user
        is_approver = hasattr(commission, 'approval') and commission.approval.assigned_approver == request.user
        is_admin = request.user.is_staff or request.user.groups.filter(name='Admins').exists()
        
        if not (is_owner or is_approver or is_admin):
            return Response({"detail": "Not authorized to view this approval."}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            serializer = CommissionApprovalSerializer(commission.approval)
            return Response(serializer.data)
        except CommissionApproval.DoesNotExist:
            return Response({"detail": "Approval process not started for this commission."}, status=status.HTTP_404_NOT_FOUND)


class CommissionSubmitView(views.APIView):
    """
    POST /api/commissions/<id>/submit/
    Moves commission from Draft -> Submitted.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        commission = get_object_or_404(Commission, pk=pk)
        
        # Security: Only owner or Admin
        if commission.consultant != request.user and not request.user.is_staff:
             return Response({"detail": "Only the consultant can submit this commission."}, status=status.HTTP_403_FORBIDDEN)
             
        serializer = ApprovalActionBaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            ApprovalSubmissionService.submit(
                commission, 
                request.user, 
                notes=serializer.validated_data.get('notes', "")
            )
            return Response({"detail": "Commission submitted successfully."}, status=status.HTTP_200_OK)
        except ApprovalError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)


class CommissionApproveView(views.APIView):
    """
    POST /api/commissions/<id>/approve/
    Moves commission from Submitted -> Approved.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        commission = get_object_or_404(Commission, pk=pk)
        
        serializer = ApprovalActionBaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            ApprovalDecisionService.approve(
                commission, 
                request.user, 
                notes=serializer.validated_data.get('notes', "")
            )
            return Response({"detail": "Commission approved successfully."}, status=status.HTTP_200_OK)
        except ApprovalError as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN if "authorized" in str(e).lower() else status.HTTP_409_CONFLICT)


class CommissionRejectView(views.APIView):
    """
    POST /api/commissions/<id>/reject/
    Moves commission from Submitted -> Rejected.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        commission = get_object_or_404(Commission, pk=pk)
        
        serializer = ApprovalRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            ApprovalDecisionService.reject(
                commission, 
                request.user, 
                rejection_reason=serializer.validated_data['rejection_reason']
            )
            return Response({"detail": "Commission rejected successfully."}, status=status.HTTP_200_OK)
        except ApprovalError as e:
             return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN if "authorized" in str(e).lower() else status.HTTP_409_CONFLICT)


class CommissionPayView(views.APIView):
    """
    POST /api/commissions/<id>/mark-paid/
    Moves commission from Approved -> Paid.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        commission = get_object_or_404(Commission, pk=pk)
        
        serializer = ApprovalPaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            ApprovalPaymentService.mark_as_paid(
                commission, 
                request.user, 
                notes=serializer.validated_data.get('notes', "")
            )
            return Response({"detail": "Commission marked as paid."}, status=status.HTTP_200_OK)
        except ApprovalError as e:
             return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN if "Only Admins" in str(e) else status.HTTP_409_CONFLICT)


class CommissionTimelineView(views.APIView):
    """
    GET /api/commissions/<id>/timeline/
    Returns chronological audit history.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        commission = get_object_or_404(Commission, pk=pk)
        
        # Security: Owner, Manager, or Admin
        is_owner = commission.consultant == request.user
        is_manager = commission.manager == request.user
        is_admin = request.user.is_staff or request.user.groups.filter(name='Admins').exists()
        
        if not (is_owner or is_manager or is_admin):
            return Response({"detail": "Not authorized to view timeline."}, status=status.HTTP_403_FORBIDDEN)
            
        try:
            history = commission.approval.history.all().order_by('timestamp')
            serializer = ApprovalHistorySerializer(history, many=True)
            return Response(serializer.data)
        except (CommissionApproval.DoesNotExist, AttributeError):
            return Response([], status=status.HTTP_200_OK)
