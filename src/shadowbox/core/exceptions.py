"""
Exceptions for ShadowBox core module
This is placed such that there is a general error catcher
"""


class ShadbowBoxError(Exception):
    # general container for errors
    pass


class StorageError(ShadowBoxError):
    # raised if storage fails in some way (defined later)
    pass


class FileNotFoundError(StorageError):
    # raised if a file not found in storage
    pass


class FileAlreadyExistsError(StorageError):
    # raised when creating an existing file
    pass


class InvalidFileError(ShadowBoxError):
    # raised when an invalid or malformed file is uploaded
    pass


class PermissionError(ShadowBoxError):
    # raised when user lacks permissions to do sth
    pass


class QuotaExceededError(StorageError):
    # raised when storage cap is exceeded (i.e. existing local capacity)
    pass


class InvalidPathError(StorageError):
    # raised when path DNE
    pass
