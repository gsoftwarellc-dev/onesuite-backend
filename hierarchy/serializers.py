from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import ReportingLine

User = get_user_model()


class UserBasicSerializer(serializers.ModelSerializer):
    """Minimal user representation for hierarchy responses"""
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = fields


class ReportingLineSerializer(serializers.ModelSerializer):
    """Full reporting line with nested user data"""
    consultant = UserBasicSerializer(read_only=True)
    manager = UserBasicSerializer(read_only=True)
    
    consultant_id = serializers.IntegerField(write_only=True)
    manager_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = ReportingLine
        fields = [
            'id', 'consultant', 'manager', 'consultant_id', 'manager_id',
            'start_date', 'end_date', 'is_active', 'notes',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'is_active']
    
    def validate(self, attrs):
        """Validate business rules"""
        consultant_id = attrs.get('consultant_id')
        manager_id = attrs.get('manager_id')
        
        # Prevent self-management
        if consultant_id == manager_id:
            raise serializers.ValidationError({
                "error": "self_assignment",
                "detail": "A user cannot be their own manager."
            })
        
        # Check if users exist
        if not User.objects.filter(id=consultant_id).exists():
            raise serializers.ValidationError({
                "consultant_id": "User not found."
            })
        
        if not User.objects.filter(id=manager_id).exists():
            raise serializers.ValidationError({
                "manager_id": "User not found."
            })
        
        # Check for circular hierarchy (basic check)
        # Prevent assigning a manager who reports to the consultant
        existing_relationship = ReportingLine.objects.filter(
            consultant_id=manager_id,
            manager_id=consultant_id,
            is_active=True
        ).exists()
        
        if existing_relationship:
            raise serializers.ValidationError({
                "error": "circular_hierarchy",
                "detail": "This assignment would create a circular reporting structure."
            })
        
        # Check for existing active manager
        if not self.instance:  # Only on creation
            existing_active = ReportingLine.objects.filter(
                consultant_id=consultant_id,
                is_active=True
            ).exists()
            
            if existing_active:
                raise serializers.ValidationError({
                    "error": "active_manager_exists",
                    "detail": "This consultant already has an active manager. Use change-manager endpoint instead."
                })
        
        return attrs
    
    def create(self, validated_data):
        """Create new reporting line"""
        consultant_id = validated_data.pop('consultant_id')
        manager_id = validated_data.pop('manager_id')
        
        # Get user instances
        consultant = User.objects.get(id=consultant_id)
        manager = User.objects.get(id=manager_id)
        
        # Create reporting line
        reporting_line = ReportingLine.objects.create(
            consultant=consultant,
            manager=manager,
            **validated_data
        )
        
        return reporting_line


class ReportingLineListSerializer(serializers.ModelSerializer):
    """Simpler serializer for list views"""
    consultant = UserBasicSerializer(read_only=True)
    manager = UserBasicSerializer(read_only=True)
    
    class Meta:
        model = ReportingLine
        fields = [
            'id', 'consultant', 'manager', 'start_date', 
            'end_date', 'is_active', 'created_at'
        ]


class ChangeManagerSerializer(serializers.Serializer):
    """Serializer for changing a consultant's manager"""
    consultant_id = serializers.IntegerField()
    new_manager_id = serializers.IntegerField()
    transition_date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, attrs):
        consultant_id = attrs['consultant_id']
        new_manager_id = attrs['new_manager_id']
        
        # Validate users exist
        if not User.objects.filter(id=consultant_id).exists():
            raise serializers.ValidationError({"consultant_id": "User not found."})
        
        if not User.objects.filter(id=new_manager_id).exists():
            raise serializers.ValidationError({"new_manager_id": "User not found."})
        
        # Prevent self-management
        if consultant_id == new_manager_id:
            raise serializers.ValidationError({
                "error": "self_assignment",
                "detail": "A user cannot be their own manager."
            })
        
        # Check if consultant HAS an active manager
        current_manager = ReportingLine.objects.filter(
            consultant_id=consultant_id,
            is_active=True
        ).first()
        
        if not current_manager:
            raise serializers.ValidationError({
                "detail": "This consultant does not have an active manager."
            })
        
        # Check if new manager is same as current
        if current_manager.manager_id == new_manager_id:
            raise serializers.ValidationError({
                "error": "no_change",
                "detail": "The new manager is the same as the current manager."
            })
        
        attrs['current_manager'] = current_manager
        return attrs


class DeactivateReportingLineSerializer(serializers.Serializer):
    """Serializer for deactivating a reporting line"""
    end_date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_end_date(self, value):
        # Ensure end_date is not in the future (optional business rule)
        from django.utils import timezone
        if value > timezone.now().date():
            # Allow future dates for planned transitions
            pass
        return value


class HierarchyTreeSerializer(serializers.Serializer):
    """Recursive serializer for full team hierarchy"""
    consultant = UserBasicSerializer()
    start_date = serializers.DateField()
    is_active = serializers.BooleanField()
    team = serializers.ListField(child=serializers.DictField(), required=False)
