from cryptography.fernet import Fernet
from fastapi import logger

from app.core.config import settings


class EncryptionManager:
    def __init__(self):
        self.master_key = settings.encryption_master_key

        if not self.master_key:
            logger.warning("ENCRYPTION_MASTER_KEY hasn't been set")
            self.master_key = Fernet.generate_key().decode()
        self.cipher_suite = Fernet(self.master_key.encode())

    def encrypt_key(self, plain_text_key: str) -> str:
        try:
            encrypted_bytes = self.cipher_suite.encrypt(
                plain_text_key.encode("utf-8")
            )
            return encrypted_bytes.decode("utf-8")

        except Exception as e:
            logger.error("Encryption failed: {}", e)
            raise ValueError("Failed to encrypt key")

    def decrypt_key(self, encrypted_key: str) -> str:
        try:
            decrypted_bytes = self.cipher_suite.decrypt(
                encrypted_key.encode("utf-8")
            )
            return decrypted_bytes.decode("utf-8")

        except Exception as e:
            logger.error("Decryption failed: {}", e)
            raise ValueError("Failed to decrypt key")

crypto_manager = EncryptionManager()
