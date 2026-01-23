"""
API Views for the Commissions Engine.

Implements REST endpoints as specified in Phase 2 API Design.
All business logic delegated to services layer.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.db.models import Sum, Count, Q
from django.core.exceptions import ValidationError as DjangoValidationError

from .models import Commission
from .serializers import (
    CommissionCreateSerializer,
    CommissionReadSerializer,
    CommissionListSerializer,
    CommissionSummarySerializer,
    CommissionAdjustmentSerializer,
    StateTransitionSerializer,
    BulkCommissionCreateSerializer,
)
from .services import (
    CommissionCreationService,
    StateTransitionService,
    AdjustmentService,
)

User = get_user_model()


class IsOwnerOrAdmin(IsAuthenticated):
    """
    Permission: User can access own commissions or admin can access any.
    """
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        return obj.consultant == request.user


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_commission(request):
    """
    POST /api/commissions/create/
    
    Create a base commission with automatic override commissions.
    """
    serializer = CommissionCreateSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    # Extract validated data
    consultant_id = serializer.validated_data['consultant_id']
    consultant = get_object_or_404(User, id=consultant_id)
    
    # Permission check: user can only create for themselves unless admin
    if not request.user.is_staff and consultant != request.user:
        return Response(
            {"detail": "You can only create commissions for yourself."},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        # Call service to create commission + overrides
        result = CommissionCreationService.create_base_commission_with_overrides(
            consultant=consultant,
            transaction_date=serializer.validated_data['transaction_date'],
            sale_amount=serializer.validated_data['sale_amount'],
            gst_rate=serializer.validated_data['gst_rate'],
            commission_rate=serializer.validated_data['commission_rate'],
            reference_number=serializer.validated_data['reference_number'],
            notes=serializer.validated_data.get('notes', ''),
            created_by=request.user
        )
        
        # Serialize response
        base_commission_data = CommissionReadSerializer(result['base_commission']).data
        override_commissions_data = CommissionReadSerializer(
            result['override_commissions'], many=True
        ).data
        
        response_data = {
            "base_commission": base_commission_data,
            "override_commissions": override_commissions_data,
            "total_created": result['total_created']
        }
        
        return Response(response_data, status=status.HTTP_201_CREATED)
        
    except DjangoValidationError as e:
        return Response(
            {"detail": str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )


@api_view(['POST'])
@permission_classes([IsAdminUser])
def bulk_create_commissions(request):
    """
    POST /api/commissions/bulk-create/
    
    Admin-only bulk creation of commissions.
    """
    serializer = BulkCommissionCreateSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    commissions_data = serializer.validated_data['commissions']
    
    results = []
    created_count = 0
    failed_count = 0
    
    for comm_data in commissions_data:
        try:
            consultant = get_object_or_404(User, id=comm_data['consultant_id'])
            
            result = CommissionCreationService.create_base_commission_with_overrides(
                consultant=consultant,
                transaction_date=comm_data['transaction_date'],
                sale_amount=comm_data['sale_amount'],
                gst_rate=comm_data['gst_rate'],
                commission_rate=comm_data['commission_rate'],
                reference_number=comm_data['reference_number'],
                notes=comm_data.get('notes', ''),
                created_by=request.user
            )
            
            results.append({
                "reference_number": comm_data['reference_number'],
                "status": "success",
                "base_commission_id": result['base_commission'].id,
                "override_count": len(result['override_commissions'])
            })
            created_count += result['total_created']
            
        except Exception as e:
            results.append({
                "reference_number": comm_data['reference_number'],
                "status": "failed",
                "error": str(e)
            })
            failed_count += 1
    
    return Response({
        "created": created_count,
        "failed": failed_count,
        "results": results
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_commissions(request):
    """
    GET /api/commissions/my-commissions/
    
    List all commissions for the authenticated user.
    """
    # Filter by user
    queryset = Commission.objects.filter(
        Q(consultant=request.user) | Q(manager=request.user)
    ).select_related('consultant', 'manager', 'created_by', 'approved_by')
    
    # Apply filters from query params
    state = request.query_params.get('state')
    if state:
        queryset = queryset.filter(state=state)
    
    commission_type = request.query_params.get('commission_type')
    if commission_type:
        queryset = queryset.filter(commission_type=commission_type)
    
    start_date = request.query_params.get('start_date')
    if start_date:
        queryset = queryset.filter(transaction_date__gte=start_date)
    
    end_date = request.query_params.get('end_date')
    if end_date:
        queryset = queryset.filter(transaction_date__lte=end_date)
    
    # Pagination (simple implementation)
    page_size = int(request.query_params.get('page_size', 20))
    page = int(request.query_params.get('page', 1))
    
    start_index = (page - 1) * page_size
    end_index = start_index + page_size
    
    total_count = queryset.count()
    paginated_queryset = queryset[start_index:end_index]
    
    serializer = CommissionListSerializer(paginated_queryset, many=True)
    
    return Response({
        "count": total_count,
        "next": f"?page={page + 1}" if end_index < total_count else None,
        "previous": f"?page={page - 1}" if page > 1 else None,
        "results": serializer.data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_team_commissions(request):
    """
    GET /api/commissions/my-team/
    
    Manager views their team's commission summaries.
    """
    # Check if user is a manager (has team members)
    from hierarchy.models import ReportingLine
    
    is_manager = ReportingLine.objects.filter(
        manager=request.user, is_active=True
    ).exists()
    role = getattr(request.user, 'role', '')
    role_value = role.lower().strip() if isinstance(role, str) else role
    has_manager_access = (
        request.user.is_staff
        or request.user.is_superuser
        or role_value in ['manager', 'admin']
        or getattr(request.user, 'is_manager', False)
        or is_manager
    )
    
    if not has_manager_access:
        # Return empty list instead of error
        return Response([])
    
    # Get team members
    team_members = ReportingLine.objects.filter(
        manager=request.user, is_active=True
    ).values_list('consultant_id', flat=True)
    
    # Aggregate commissions by consultant
    # Pre-fetch users to avoid N+1
    user_objects = User.objects.filter(id__in=team_members)
    users_map = {u.id: u for u in user_objects}
    
    team_data = []
    for consultant_id in team_members:
        # Base query for this consultant
        commissions = Commission.objects.filter(
            consultant_id=consultant_id,
            commission_type='base'
        )
        
        # Calculate stats
        total_sales_volume = commissions.aggregate(Sum('sale_amount'))['sale_amount__sum'] or 0
        total_commission = commissions.aggregate(Sum('calculated_amount'))['calculated_amount__sum'] or 0
        pending_qs = commissions.filter(state='submitted')
        pending_count = pending_qs.count()
        pending_val = pending_qs.aggregate(Sum('calculated_amount'))['calculated_amount__sum'] or 0
        
        team_data.append({
            "consultant": {
                "id": consultant_id,
                "username": users_map.get(consultant_id).username if consultant_id in users_map else "Unknown"
            },
            # Metrics
            "total_sales_volume": str(total_sales_volume),      # Gross Revenue (Policy Value)
            "total_commission_earned": str(total_commission),   # Actual Earnings
            "pending_count": pending_count,                     # Number of items to review
            "pending_value": str(pending_val),                  # Potential earnings pending
            
            # Legacy/Debug fields (optional)
            "total_commissions_count": commissions.count(),
        })
    
    return Response({
        "count": len(team_data),
        "results": team_data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_payslips(request):
    """
    GET /api/commissions/my-payslips/
    
    Returns monthly aggregation of PAID commissions.
    Acting as a pseudo-payslip until full payroll module is built.
    """
    from django.db.models.functions import TruncMonth
    from django.db.models import Sum, Count
    
    # Filter for PAID commissions only
    queryset = Commission.objects.filter(
        consultant=request.user,
        state='paid'
    )
    
    # Group by Payment Month (paid_at)
    # If paid_at is null (shouldn't be for paid), fallback to updated_at
    from django.db.models import F
    from django.db.models.functions import Coalesce
    
    summary = queryset.annotate(
        payment_date=Coalesce('paid_at', 'updated_at')
    ).annotate(
        month=TruncMonth('payment_date')
    ).values('month').annotate(
        total_amount=Sum('calculated_amount'),
        count=Count('id')
    ).order_by('-month')
    
    data = []
    for item in summary:
        if item['month']:
            data.append({
                "month_label": item['month'].strftime("%B %Y"), # e.g. December 2025
                "month_id": item['month'].strftime("%Y-%m"),    # e.g. 2025-12
                "amount": str(item['total_amount']),
                "count": item['count'],
                "status": "Available",
                "generated_on": item['month'].date()
            })
            
    return Response(data)

@api_view(['GET'])
@permission_classes([IsAdminUser])
def all_commissions(request):
    """
    GET /api/commissions/
    
    Admin view of all commissions with advanced filtering.
    """
    queryset = Commission.objects.select_related(
        'consultant', 'manager', 'created_by', 'approved_by'
    ).all()
    
    # Apply filters
    consultant_id = request.query_params.get('consultant_id')
    if consultant_id:
        queryset = queryset.filter(consultant_id=consultant_id)
    
    manager_id = request.query_params.get('manager_id')
    if manager_id:
        queryset = queryset.filter(manager_id=manager_id)
    
    state = request.query_params.get('state')
    if state:
        queryset = queryset.filter(state=state)
    
    commission_type = request.query_params.get('commission_type')
    if commission_type:
        queryset = queryset.filter(commission_type=commission_type)
    
    # Pagination
    page_size = int(request.query_params.get('page_size', 20))
    page = int(request.query_params.get('page', 1))
    
    start_index = (page - 1) * page_size
    end_index = start_index + page_size
    
    total_count = queryset.count()
    paginated_queryset = queryset[start_index:end_index]
    
    serializer = CommissionListSerializer(paginated_queryset, many=True)
    
    return Response({
        "count": total_count,
        "results": serializer.data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def commission_detail(request, pk):
    """
    GET /api/commissions/<id>/
    
    View full details of a specific commission.
    """
    commission = get_object_or_404(Commission, pk=pk)
    
    # Permission check: owner or admin
    if not request.user.is_staff and commission.consultant != request.user:
        return Response(
            {"detail": "You do not have permission to view this commission."},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Get related commissions
    related_commissions = []
    if commission.commission_type == 'base':
        related_commissions = Commission.objects.filter(
            parent_commission=commission
        ).select_related('manager')
    
    serializer = CommissionReadSerializer(commission)
    related_serializer = CommissionListSerializer(related_commissions, many=True)
    
    data = serializer.data
    data['related_commissions'] = related_serializer.data
    
    return Response(data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def submit_commission(request, pk):
    """
    PATCH /api/commissions/<id>/submit/
    
    Submit commission for approval.
    """
    commission = get_object_or_404(Commission, pk=pk)
    
    # Permission: owner or admin
    if not request.user.is_staff and commission.consultant != request.user:
        return Response(
            {"detail": "You do not have permission to submit this commission."},
            status=status.HTTP_403_FORBIDDEN
        )
    
    serializer = StateTransitionSerializer(
        data=request.data,
        context={'commission': commission, 'target_state': 'submitted'}
    )
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        updated_commission = StateTransitionService.transition_to_submitted(
            commission,
            actor=request.user,
            notes=serializer.validated_data.get('notes', '')
        )
        
        return Response({
            "id": updated_commission.id,
            "state": updated_commission.state,
            "updated_at": updated_commission.updated_at
        })
        
    except DjangoValidationError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def approve_commission(request, pk):
    """
    PATCH /api/commissions/<id>/approve/
    
    Admin approves commission.
    """
    commission = get_object_or_404(Commission, pk=pk)
    
    serializer = StateTransitionSerializer(
        data=request.data,
        context={'commission': commission, 'target_state': 'approved'}
    )
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        updated_commission = StateTransitionService.transition_to_approved(
            commission,
            actor=request.user,
            notes=serializer.validated_data.get('notes', '')
        )
        
        # Count related overrides that were also approved
        related_count = Commission.objects.filter(
            parent_commission=commission,
            commission_type='override',
            state='approved'
        ).count()
        
        return Response({
            "id": updated_commission.id,
            "state": updated_commission.state,
            "approved_by": {
                "id": request.user.id,
                "username": request.user.username
            },
            "approved_at": updated_commission.approved_at,
            "related_commissions_approved": related_count
        })
        
    except DjangoValidationError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def reject_commission(request, pk):
    """
    PATCH /api/commissions/<id>/reject/
    
    Admin rejects commission.
    """
    commission = get_object_or_404(Commission, pk=pk)
    
    serializer = StateTransitionSerializer(
        data=request.data,
        context={'commission': commission, 'target_state': 'rejected'}
    )
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        updated_commission = StateTransitionService.transition_to_rejected(
            commission,
            actor=request.user,
            rejection_reason=serializer.validated_data.get('rejection_reason', '')
        )
        
        return Response({
            "id": updated_commission.id,
            "state": updated_commission.state,
            "rejection_reason": updated_commission.rejection_reason,
            "updated_at": updated_commission.updated_at
        })
        
    except DjangoValidationError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def mark_paid(request, pk):
    """
    PATCH /api/commissions/<id>/mark-paid/
    
    Admin marks commission as paid.
    """
    commission = get_object_or_404(Commission, pk=pk)
    
    serializer = StateTransitionSerializer(
        data=request.data,
        context={'commission': commission, 'target_state': 'paid'}
    )
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        updated_commission = StateTransitionService.transition_to_paid(
            commission,
            actor=request.user,
            paid_at=serializer.validated_data.get('paid_at')
        )
        
        return Response({
            "id": updated_commission.id,
            "state": updated_commission.state,
            "paid_at": updated_commission.paid_at
        })
        
    except DjangoValidationError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def create_adjustment(request, pk):
    """
    POST /api/commissions/<id>/adjust/
    
    Create adjustment for a paid commission.
    """
    original_commission = get_object_or_404(Commission, pk=pk)
    
    serializer = CommissionAdjustmentSerializer(
        data=request.data,
        context={'original_commission': original_commission}
    )
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        adjustment = AdjustmentService.create_adjustment(
            original_commission=original_commission,
            adjustment_amount=serializer.validated_data['adjustment_amount'],
            notes=serializer.validated_data['notes'],
            created_by=request.user
        )
        
        adjustment_data = CommissionReadSerializer(adjustment).data
        
        return Response(adjustment_data, status=status.HTTP_201_CREATED)
        
    except DjangoValidationError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def commission_history(request, pk):
    """
    GET /api/commissions/<id>/history/
    
    View adjustment history for a commission.
    """
    original_commission = get_object_or_404(Commission, pk=pk)
    
    # Permission check
    if not request.user.is_staff and original_commission.consultant != request.user:
        return Response(
            {"detail": "You do not have permission to view this commission."},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Get all adjustments
    adjustments = Commission.objects.filter(
        adjustment_for=original_commission
    ).order_by('created_at')
    
    # Calculate net amount
    net_amount = original_commission.calculated_amount
    for adj in adjustments:
        if adj.state in ['approved', 'paid']:
            net_amount += adj.calculated_amount
    
    return Response({
        "original_commission": {
            "id": original_commission.id,
            "calculated_amount": str(original_commission.calculated_amount),
            "state": original_commission.state
        },
        "adjustments": CommissionListSerializer(adjustments, many=True).data,
        "net_amount": str(net_amount)
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def commission_summary(request):
    """
    GET /api/commissions/summary/
    
    Dashboard summary of user's earnings.
    """
    # Get date range
    from datetime import datetime, timedelta
    
    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')
    
    if not start_date or not end_date:
        # Default to current month
        today = datetime.now().date()
        start_date = today.replace(day=1)
        end_date = today
    
    # Query user's commissions
    base_commissions = Commission.objects.filter(
        consultant=request.user,
        commission_type='base',
        transaction_date__gte=start_date,
        transaction_date__lte=end_date
    )
    
    override_commissions = Commission.objects.filter(
        manager=request.user,
        commission_type='override',
        transaction_date__gte=start_date,
        transaction_date__lte=end_date
    )
    
    # Aggregate base commissions
    base_data = {
        "count": base_commissions.count(),
        "total": str(base_commissions.aggregate(Sum('calculated_amount'))['calculated_amount__sum'] or 0),
        "draft": str(base_commissions.filter(state='draft').aggregate(Sum('calculated_amount'))['calculated_amount__sum'] or 0),
        "submitted": str(base_commissions.filter(state='submitted').aggregate(Sum('calculated_amount'))['calculated_amount__sum'] or 0),
        "approved": str(base_commissions.filter(state='approved').aggregate(Sum('calculated_amount'))['calculated_amount__sum'] or 0),
        "paid": str(base_commissions.filter(state='paid').aggregate(Sum('calculated_amount'))['calculated_amount__sum'] or 0)
    }
    
    # Aggregate override commissions
    override_data = {
        "count": override_commissions.count(),
        "total": str(override_commissions.aggregate(Sum('calculated_amount'))['calculated_amount__sum'] or 0),
        "approved": str(override_commissions.filter(state='approved').aggregate(Sum('calculated_amount'))['calculated_amount__sum'] or 0),
        "paid": str(override_commissions.filter(state='paid').aggregate(Sum('calculated_amount'))['calculated_amount__sum'] or 0)
    }
    
    # Calculate totals
    total_earnings = float(base_data['total']) + float(override_data['total'])
    pending_approval = float(base_data['submitted'])
    ready_for_payout = float(base_data['approved']) + float(override_data['approved'])
    
    return Response({
        "period": {
            "start_date": str(start_date),
            "end_date": str(end_date)
        },
        "base_commissions": base_data,
        "override_commissions": override_data,
        "total_earnings": str(total_earnings),
        "pending_approval": str(pending_approval),
        "ready_for_payout": str(ready_for_payout)
    })
