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
    

class InitializationError(ShadowboxError):
    #Raised when there is an error initializing a component.
    pass


class FileNotFoundError(StorageError):
    # raised if a file not found in storage
    pass


class UserNotFoundError(ShadowboxError):
    # Raised when a user is not found in the database.
    pass


class UserExistsError(ShadowboxError):
    # Raised when trying to create a user that already exists.
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
    
    
class IntegrityCheckFailedError(ShadowboxError):
    # Raised when a file's hash does not match its expected value.
    pass
    

class InvalidPathError(StorageError):
    # raised when path DNE
    pass
