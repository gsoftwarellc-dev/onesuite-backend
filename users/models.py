from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    """
    Custom user model for OneSuite.
    """
    is_manager = models.BooleanField(default=False)
    # Add other fields as needed: roles, account status, etc.

    def __str__(self):
        return self.username
