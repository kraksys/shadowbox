import os
from typing import Dict

from argon2.low_level import Type, hash_secret_raw


def generate_salt(length: int = 16) -> bytes:
    """Return a cryptographically secure random salt."""
    return os.urandom(length)


def derive_master_key(
    password: bytes,
    salt: bytes,
    time_cost: int = 3,
    memory_cost: int = 65536,
    parallelism: int = 1,
    key_len: int = 32,
) -> bytes:
    """
    Derive a master key from a password using Argon2id.
    Returns raw derived key bytes.
    """
    if isinstance(password, str):
        password = password.encode("utf-8")

    return hash_secret_raw(
        secret=password,
        salt=salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=key_len,
        type=Type.ID,
    )


def kdf_params_to_dict(salt: bytes, time_cost: int, memory_cost: int, parallelism: int) -> Dict:
    return {
        "algo": "argon2id",
        "salt": salt.hex(),
        "time": time_cost,
        "memory": memory_cost,
        "parallelism": parallelism,
    }
