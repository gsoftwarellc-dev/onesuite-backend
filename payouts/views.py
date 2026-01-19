from rest_framework import viewsets, status, permissions, decorators, mixins
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db import transaction

from .models import PayoutBatch, Payout, PayoutPeriod
from .serializers import (
    PayoutBatchSerializer, PayoutBatchDetailSerializer, PayoutBatchCreateSerializer,
    PayoutListSerializer, PayoutDetailSerializer, BatchActionSerializer
)
from .services import (
    PayoutCalculationService, 
    PayoutLifecycleService, 
    PayoutError,
    PayoutPermissionError,
    PayoutStateError,
    PayoutValidationError
)

class IsFinanceAdmin(permissions.BasePermission):
    """
    Check if user is Admin or part of Finance group.
    """
    def has_permission(self, request, view):
        return (
            request.user.is_staff or 
            request.user.groups.filter(name__in=['Admins', 'Finance']).exists()
        )

class PayoutBatchViewSet(viewsets.ModelViewSet):
    """
    Admin/Finance endpoint for managing Payout Batches.
    """
    queryset = PayoutBatch.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsFinanceAdmin]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return PayoutBatchCreateSerializer
        if self.action == 'retrieve':
            return PayoutBatchDetailSerializer
        return PayoutBatchSerializer

    def create(self, request, *args, **kwargs):
        """
        POST /api/payouts/batches/
        Generate a new DRAFT batch.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        period_id = serializer.validated_data['period_id']
        period = get_object_or_404(PayoutPeriod, id=period_id)
        
        try:
            batch = PayoutCalculationService.create_batch_for_period(
                period=period,
                created_by=request.user,
                run_date=serializer.validated_data.get('run_date'),
                notes=serializer.validated_data.get('notes', '')
            )
            
            # Return details
            response_serializer = PayoutBatchSerializer(batch)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            
        except PayoutPermissionError as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except PayoutStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PayoutValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except PayoutError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @decorators.action(detail=True, methods=['post'])
    def lock(self, request, pk=None):
        """
        POST /api/payouts/batches/{id}/lock/
        Draft -> Locked
        """
        batch = self.get_object()
        try:
            updated_batch = PayoutLifecycleService.lock_batch(batch, request.user)
            return Response(PayoutBatchSerializer(updated_batch).data)
        except PayoutStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PayoutValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except PayoutError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @decorators.action(detail=True, methods=['post'])
    def release(self, request, pk=None):
        """
        POST /api/payouts/batches/{id}/release/
        Locked -> Released (Pays commissions)
        """
        batch = self.get_object()
        try:
            updated_batch = PayoutLifecycleService.release_batch(batch, request.user)
            return Response(PayoutBatchSerializer(updated_batch).data)
        except PayoutStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PayoutError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @decorators.action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        """
        POST /api/payouts/batches/{id}/void/
        Draft/Locked -> Void (Unlinks commissions)
        """
        batch = self.get_object()
        try:
            updated_batch = PayoutLifecycleService.void_batch(batch, request.user)
            return Response(PayoutBatchSerializer(updated_batch).data)
        except PayoutStateError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except PayoutError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PayoutViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Endpoint for individual payouts. 
    Users see own history. Admins see all.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PayoutDetailSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Payout.objects.all().select_related('batch', 'consultant').order_by('-paid_at', '-batch__created_at')
        
        # Admin can seeing everything, normal users only own
        if user.is_staff or user.groups.filter(name__in=['Admins', 'Finance']).exists():
            return qs
        return qs.filter(consultant=user)

    @decorators.action(detail=False, methods=['get'], url_path='my-history')
    def my_history(self, request):
        """
        GET /api/payouts/my-history/
        Convenience endpoint for consultants.
        """
        qs = self.get_queryset().filter(status='PAID') # Show only Paid ones? or all? Assuming all for history.
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = PayoutListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = PayoutListSerializer(qs, many=True)
        return Response(serializer.data)

    @decorators.action(detail=False, methods=['get'], url_path='team-summary')
    def team_summary(self, request):
        """
        GET /api/payouts/team-summary/?period_id=123
        Manager endpoint to view team payout summaries.
        """
        from hierarchy.models import ReportingLine
        from django.db.models import Sum
        
        user = request.user
        
        # Check permissions: Manager or Admin
        is_admin = user.is_staff or user.groups.filter(name__in=['Admins', 'Finance']).exists()
        
        if not is_admin:
            # Check if user is a manager (has direct reports)
            has_reports = ReportingLine.objects.filter(manager=user, is_active=True).exists()
            if not has_reports:
                return Response(
                    {"detail": "Only managers can access team summaries."},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Get period filter
        period_id = request.query_params.get('period_id')
        if not period_id:
            return Response(
                {"detail": "period_id query parameter is required."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        
        try:
            period = PayoutPeriod.objects.get(id=period_id)
        except PayoutPeriod.DoesNotExist:
            return Response(
                {"detail": "Period not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get team members
        if is_admin:
            # Admin sees all
            team_payouts = Payout.objects.filter(
                batch__period=period
            ).select_related('consultant', 'batch')
        else:
            # Manager sees only direct reports
            direct_reports = ReportingLine.objects.filter(
                manager=user,
                is_active=True
            ).values_list('consultant_id', flat=True)
            
            team_payouts = Payout.objects.filter(
                batch__period=period,
                consultant_id__in=direct_reports
            ).select_related('consultant', 'batch')
        
        # Aggregate by consultant
        summary = team_payouts.values('consultant__id', 'consultant__username').annotate(
            total_amount=Sum('net_amount')
        ).order_by('consultant__username')
        
        # Calculate team total
        team_total = team_payouts.aggregate(Sum('net_amount'))['net_amount__sum'] or 0
        
        return Response({
            'period': period.name,
            'team_total': team_total,
            'members': [
                {
                    'name': member['consultant__username'],
                    'net_amount': member['total_amount'],
                    'status': 'PAID'  # Simplified - could enhance to show actual status
                }
                for member in summary
            ]
        })

