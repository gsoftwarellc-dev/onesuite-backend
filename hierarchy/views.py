from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Q

from .models import ReportingLine
from .serializers import (
    ReportingLineSerializer,
    ReportingLineListSerializer,
    ChangeManagerSerializer,
    DeactivateReportingLineSerializer,
    UserBasicSerializer,
)

User = get_user_model()


class ReportingLineViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing reporting lines.
    Admin-only for create/update/delete operations.
    """
    queryset = ReportingLine.objects.select_related('consultant', 'manager').all()
    permission_classes = [IsAdminUser]
    
    def get_serializer_class(self):
        if self.action == 'list':
            return ReportingLineListSerializer
        return ReportingLineSerializer
    
    def get_queryset(self):
        """Filter based on query parameters"""
        queryset = super().get_queryset()
        
        # Filter by active status
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        # Filter by consultant
        consultant_id = self.request.query_params.get('consultant_id')
        if consultant_id:
            queryset = queryset.filter(consultant_id=consultant_id)
        
        # Filter by manager
        manager_id = self.request.query_params.get('manager_id')
        if manager_id:
            queryset = queryset.filter(manager_id=manager_id)
        
        # Filter by date range
        start_date_after = self.request.query_params.get('start_date_after')
        if start_date_after:
            queryset = queryset.filter(start_date__gte=start_date_after)
        
        end_date_before = self.request.query_params.get('end_date_before')
        if end_date_before:
            queryset = queryset.filter(
                Q(end_date__lte=end_date_before) | Q(end_date__isnull=True)
            )
        
        return queryset
    
    def perform_create(self, serializer):
        """Track who created the relationship"""
        serializer.save(created_by=self.request.user)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_manager(request):
    """Get the current user's active manager"""
    reporting_line = ReportingLine.objects.filter(
        consultant=request.user,
        is_active=True
    ).select_related('manager').first()
    
    if not reporting_line:
        return Response(
            {"detail": "You currently have no assigned manager."},
            status=status.HTTP_404_NOT_FOUND
        )
    
    serializer = ReportingLineSerializer(reporting_line)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_team(request):
    """Get the current user's direct reports"""
    reporting_lines = ReportingLine.objects.filter(
        manager=request.user,
        is_active=True
    ).select_related('consultant')
    
    # Pagination
    from rest_framework.pagination import PageNumberPagination
    paginator = PageNumberPagination()
    paginator.page_size = request.query_params.get('page_size', 20)
    paginator.max_page_size = 100
    
    # Search
    search = request.query_params.get('search')
    if search:
        reporting_lines = reporting_lines.filter(
            Q(consultant__first_name__icontains=search) |
            Q(consultant__last_name__icontains=search) |
            Q(consultant__username__icontains=search)
        )
    
    page = paginator.paginate_queryset(reporting_lines, request)
    if page is not None:
        serializer = ReportingLineListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
    
    serializer = ReportingLineListSerializer(reporting_lines, many=True)
    return Response({
        "count": reporting_lines.count(),
        "results": serializer.data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_team_full(request):
    """Get the current user's full downstream hierarchy (recursive)"""
    # Check if user is a manager or admin
    if not (request.user.is_staff or ReportingLine.objects.filter(
        manager=request.user, is_active=True
    ).exists()):
        return Response(
            {"detail": "You do not have any team members."},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Build tree structure
    def build_tree(manager_id, max_depth=None, current_depth=0):
        if max_depth is not None and current_depth >= max_depth:
            return []
        
        team_members = ReportingLine.objects.filter(
            manager_id=manager_id,
            is_active=True
        ).select_related('consultant')
        
        tree = []
        for line in team_members:
            member_data = {
                "consultant": UserBasicSerializer(line.consultant).data,
                "start_date": line.start_date,
                "is_active": line.is_active,
                "team": build_tree(
                    line.consultant.id,
                    max_depth,
                    current_depth + 1
                )
            }
            tree.append(member_data)
        
        return tree
    
    max_depth_param = request.query_params.get('max_depth')
    max_depth = int(max_depth_param) if max_depth_param else None
    
    team_tree = build_tree(request.user.id, max_depth)
    
    return Response({
        "manager": UserBasicSerializer(request.user).data,
        "team": team_tree
    })


@api_view(['POST'])
@permission_classes([IsAdminUser])
def assign_manager(request):
    """Admin endpoint to assign a manager to a consultant"""
    serializer = ReportingLineSerializer(data=request.data)
    
    if serializer.is_valid():
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def change_manager(request):
    """Admin endpoint to change a consultant's manager"""
    serializer = ChangeManagerSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    current_manager = data['current_manager']
    transition_date = data['transition_date']
    
    # Deactivate old relationship
    from datetime import timedelta
    current_manager.end_date = transition_date - timedelta(days=1)
    current_manager.is_active = False
    current_manager.save()
    
    # Create new relationship
    new_relationship = ReportingLine.objects.create(
        consultant_id=data['consultant_id'],
        manager_id=data['new_manager_id'],
        start_date=transition_date,
        is_active=True,
        notes=data.get('notes', ''),
        created_by=request.user
    )
    
    return Response({
        "old_relationship": {
            "id": current_manager.id,
            "manager": UserBasicSerializer(current_manager.manager).data,
            "end_date": current_manager.end_date,
            "is_active": False
        },
        "new_relationship": ReportingLineSerializer(new_relationship).data
    }, status=status.HTTP_200_OK)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def deactivate_reporting_line(request, pk):
    """Admin endpoint to deactivate a reporting line"""
    try:
        reporting_line = ReportingLine.objects.get(pk=pk)
    except ReportingLine.DoesNotExist:
        return Response(
            {"detail": "Not found."},
            status=status.HTTP_404_NOT_FOUND
        )
    
    if not reporting_line.is_active:
        return Response(
            {"detail": "This reporting line is already inactive."},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    serializer = DeactivateReportingLineSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    # Deactivate
    reporting_line.is_active = False
    reporting_line.end_date = serializer.validated_data['end_date']
    if serializer.validated_data.get('notes'):
        reporting_line.notes = serializer.validated_data['notes']
    reporting_line.save()
    
    return Response({
        "id": reporting_line.id,
        "is_active": False,
        "end_date": reporting_line.end_date,
        "notes": reporting_line.notes
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def historical_hierarchy(request):
    """Admin endpoint to view hierarchy on a specific date"""
    target_date = request.query_params.get('date')
    
    if not target_date:
        return Response(
            {"detail": "Date parameter is required (format: YYYY-MM-DD)"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Query relationships active on that date
    relationships = ReportingLine.objects.filter(
        start_date__lte=target_date,
    ).filter(
        Q(end_date__gte=target_date) | Q(end_date__isnull=True)
    ).select_related('consultant', 'manager')
    
    # Optional: filter by specific user
    user_id = request.query_params.get('user_id')
    if user_id:
        relationships = relationships.filter(consultant_id=user_id)
    
    serializer = ReportingLineListSerializer(relationships, many=True)
    
    return Response({
        "snapshot_date": target_date,
        "relationships": serializer.data
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def user_manager_history(request, user_id):
    """Admin endpoint to get a user's manager history"""
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response(
            {"detail": "User not found."},
            status=status.HTTP_404_NOT_FOUND
        )
    
    history = ReportingLine.objects.filter(
        consultant=user
    ).select_related('manager').order_by('-start_date')
    
    serializer = ReportingLineListSerializer(history, many=True)
    
    return Response({
        "user": UserBasicSerializer(user).data,
        "manager_history": serializer.data
    })
