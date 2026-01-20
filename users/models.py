from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    """
    Custom user model for OneSuite.
    """
    CONSULTANT = 'consultant'
    MANAGER = 'manager'
    FINANCE = 'finance'
    DIRECTOR = 'director'
    ADMIN = 'admin'
    
    ROLE_CHOICES = [
        (CONSULTANT, 'Consultant'),
        (MANAGER, 'Manager'),
        (FINANCE, 'Finance'),
        (DIRECTOR, 'Director'),
        (ADMIN, 'Admin'),
    ]
    
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=CONSULTANT,
        help_text='User role for access control'
    )
    is_manager = models.BooleanField(default=False)
    # Add other fields as needed: roles, account status, etc.

    def __str__(self):
        return self.username
