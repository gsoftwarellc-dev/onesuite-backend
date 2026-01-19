"""
Centralized encryption utility for sensitive payment data.
Uses Django's cryptography with Fernet symmetric encryption.
"""
from cryptography.fernet import Fernet
from django.conf import settings
import base64
import hashlib


class EncryptionService:
    """
    Handles encryption/decryption of sensitive fields.
    Uses a key derived from Django SECRET_KEY.
    """
    
    @staticmethod
    def _get_cipher():
        """Get Fernet cipher using Django SECRET_KEY"""
        # Derive a 32-byte key from SECRET_KEY
        key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        # Fernet requires base64-encoded 32-byte key
        fernet_key = base64.urlsafe_b64encode(key)
        return Fernet(fernet_key)
    
    @staticmethod
    def encrypt(plaintext: str) -> str:
        """
        Encrypt plaintext string.
        Returns base64-encoded encrypted string.
        """
        if not plaintext:
            return plaintext
        
        cipher = EncryptionService._get_cipher()
        encrypted_bytes = cipher.encrypt(plaintext.encode())
        return encrypted_bytes.decode()
    
    @staticmethod
    def decrypt(ciphertext: str) -> str:
        """
        Decrypt ciphertext string.
        Returns original plaintext.
        """
        if not ciphertext:
            return ciphertext
        
        cipher = EncryptionService._get_cipher()
        decrypted_bytes = cipher.decrypt(ciphertext.encode())
        return decrypted_bytes.decode()
    
    @staticmethod
    def mask_account_number(encrypted_value: str) -> str:
        """
        Decrypt and mask account number (show last 4 digits).
        Returns masked string like ****1234
        """
        if not encrypted_value:
            return "****"
        
        try:
            plaintext = EncryptionService.decrypt(encrypted_value)
            if len(plaintext) >= 4:
                return f"****{plaintext[-4:]}"
            return "****"
        except Exception:
            return "****"
    
    @staticmethod
    def mask_tin(encrypted_value: str) -> str:
        """
        Decrypt and mask TIN (show last 4 digits).
        Returns masked string like ***-**-1234
        """
        if not encrypted_value:
            return "***-**-****"
        
        try:
            plaintext = EncryptionService.decrypt(encrypted_value)
            if len(plaintext) >= 4:
                return f"***-**-{plaintext[-4:]}"
            return "***-**-****"
        except Exception:
            return "***-**-****"
