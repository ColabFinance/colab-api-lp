from typing import Any


def sanitize_for_mongo(value: Any) -> Any:
    """
    Recursively sanitize values so they are acceptable by MongoDB/BSON.

    - ints maiores que 8 bytes viram string
    - dicts e listas são tratados recursivamente
    """
    from math import inf

    if isinstance(value, int):
        # MongoDB suporta apenas int64
        min_int64 = -(2**63)
        max_int64 = 2**63 - 1
        if min_int64 <= value <= max_int64:
            return value
        # Se ultrapassar o limite, salva como string
        return str(value)

    if isinstance(value, dict):
        return {k: sanitize_for_mongo(v) for k, v in value.items()}

    if isinstance(value, list):
        return [sanitize_for_mongo(v) for v in value]

    if isinstance(value, tuple):
        return tuple(sanitize_for_mongo(v) for v in value)

    # Outros tipos (str, float, None, bool, etc.) passam direto
    return value
