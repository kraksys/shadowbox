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
    # Raised when there is an error initializing a component.
    pass


class FileNotFoundError(StorageError):
    # raised if a file not found in storage
    pass


class UserNotFoundError(ShadowBoxError):
    # Raised when a user is not found in the database.
    pass


class UserExistsError(ShadowBoxError):
    # Raised when trying to create a user that already exists.
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
    # Raised when a file's hash does not match its expected value.
    pass


class InvalidPathError(StorageError):
    # raised when path DNE
    pass
