from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from .serializers import UserSerializer
from django.contrib.auth import get_user_model

User = get_user_model()

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer


# JWT Login View
class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]


# JWT Refresh View
class RefreshView(TokenRefreshView):
    permission_classes = [AllowAny]


# JWT Logout View (Blacklist refresh token)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    try:
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        token = RefreshToken(refresh_token)
        token.blacklist()
        
        return Response({"detail": "Logged out successfully."}, status=status.HTTP_200_OK)
    except Exception:
        # Even if token is invalid/already blacklisted, return success
        # Client should delete tokens anyway
        return Response({"detail": "Logged out successfully."}, status=status.HTTP_200_OK)


# Get current user profile
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me_view(request):
    user = request.user
    serializer = UserSerializer(user)
    return Response(serializer.data)
