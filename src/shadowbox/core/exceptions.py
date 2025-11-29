"""
Exceptions for ShadowBox core module
This is placed such that there is a general error catcher
"""


class ShadowBoxError(Exception):
    # general container for errors
    pass


class StorageError(ShadowBoxError):
    # raised if storage fails in some way (defined later)
    pass


class InitializationError(ShadowBoxError):
    # raised when initialization fails (anywhere)
    pass


class FileNotFoundError(StorageError):
    # raised if a file not found in storage
    pass


class UserNotFoundError(ShadowBoxError):
    # raised when the user DNE in the DB
    pass


class UserExistsError(ShadowBoxError):
    # raised when creating an existing user
    pass


class FileAlreadyExistsError(StorageError):
    # raised when creating an existing file
    pass


class InvalidFileError(ShadowBoxError):
    # raised when an invalid or malformed file is uploaded
    pass


class QuotaExceededError(StorageError):
    # raised when storage cap is exceeded (i.e. existing local capacity)
    pass


class IntegrityCheckFailedError(ShadowBoxError):
    # raised on a hash mismatch
    pass


class InvalidPathError(StorageError):
    # raised when path DNE
    pass


class BoxNotFoundError(ShadowBoxError):
    # raised when box not found
    pass


class BoxExistsError(ShadowBoxError):
    # raised when a box already exists
    pass


class AccessDeniedError(ShadowBoxError):
    # raised when a user doesn't have proper acccess perms
    pass
