"""
repositories/storage_backend.py
-------------------------------
Abstract Storage Backend interface and LocalStorageBackend implementation.
Provides isolated data/<user_id>/<session_id>/ storage layout.
"""
import os
import shutil
from typing import BinaryIO, Optional, Union
from abc import ABC, abstractmethod
import config

class StorageBackend(ABC):
    """Abstract file storage backend (LocalStorage, S3, MinIO)."""

    @abstractmethod
    def save(self, user_id: str, session_id: str, filename: str, data: Union[bytes, BinaryIO]) -> str:
        """Saves file data and returns the stored relative or absolute path."""
        pass

    @abstractmethod
    def open(self, user_id: str, session_id: str, filename: str) -> BinaryIO:
        """Opens a file for reading."""
        pass

    @abstractmethod
    def get_path(self, user_id: str, session_id: str, filename: str) -> str:
        """Returns the local filesystem path if available, or a resolved URI."""
        pass

    @abstractmethod
    def exists(self, user_id: str, session_id: str, filename: str) -> bool:
        """Checks if a file exists."""
        pass

    @abstractmethod
    def delete(self, user_id: str, session_id: str, filename: str) -> bool:
        """Deletes an individual file."""
        pass

    @abstractmethod
    def delete_session_dir(self, user_id: str, session_id: str) -> int:
        """Deletes all files within a session directory, returns count of deleted files."""
        pass

    @abstractmethod
    def get_user_storage_size(self, user_id: str) -> int:
        """Calculates total disk usage in bytes for a given user."""
        pass


class LocalStorageBackend(StorageBackend):
    """
    Local filesystem storage provider organized as:
    data/<user_id>/<session_id>/...
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = os.path.abspath(base_dir or os.path.join(os.getcwd(), 'data'))
        os.makedirs(self.base_dir, exist_ok=True)

    def _sanitize_segment(self, segment: Optional[str], default: str = 'anonymous') -> str:
        if not segment:
            return default
        return os.path.basename(str(segment).strip()) or default

    def _get_session_dir(self, user_id: Optional[str], session_id: str) -> str:
        clean_user = self._sanitize_segment(user_id, default='unowned')
        clean_session = self._sanitize_segment(session_id, default='unknown_session')
        return os.path.join(self.base_dir, clean_user, clean_session)

    def get_path(self, user_id: Optional[str], session_id: str, filename: str) -> str:
        clean_name = os.path.basename(filename)
        session_dir = self._get_session_dir(user_id, session_id)
        return os.path.join(session_dir, clean_name)

    def save(self, user_id: Optional[str], session_id: str, filename: str, data: Union[bytes, BinaryIO]) -> str:
        path = self.get_path(user_id, session_id, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        if isinstance(data, bytes):
            with open(path, 'wb') as f:
                f.write(data)
        elif hasattr(data, 'read'):
            with open(path, 'wb') as f:
                shutil.copyfileobj(data, f)
        return path

    def open(self, user_id: Optional[str], session_id: str, filename: str) -> BinaryIO:
        path = self.get_path(user_id, session_id, filename)
        return open(path, 'rb')

    def exists(self, user_id: Optional[str], session_id: str, filename: str) -> bool:
        path = self.get_path(user_id, session_id, filename)
        return os.path.exists(path)

    def delete(self, user_id: Optional[str], session_id: str, filename: str) -> bool:
        path = self.get_path(user_id, session_id, filename)
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except OSError:
                return False
        return False

    def delete_session_dir(self, user_id: Optional[str], session_id: str) -> int:
        session_dir = self._get_session_dir(user_id, session_id)
        count = 0
        if os.path.exists(session_dir):
            for root, _, files in os.walk(session_dir):
                count += len(files)
            try:
                shutil.rmtree(session_dir)
            except OSError:
                pass
        return count

    def get_user_storage_size(self, user_id: str) -> int:
        clean_user = self._sanitize_segment(user_id, default='unowned')
        user_dir = os.path.join(self.base_dir, clean_user)
        total = 0
        if os.path.exists(user_dir):
            for root, _, files in os.walk(user_dir):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        return total


_storage_instance = None

def get_storage_backend(base_dir: Optional[str] = None) -> StorageBackend:
    global _storage_instance
    if _storage_instance is not None and base_dir is None:
        return _storage_instance
    storage = LocalStorageBackend(base_dir)
    if base_dir is None:
        _storage_instance = storage
    return storage
