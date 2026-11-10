def mask_account_num(num: str | None) -> str | None:
    """123-4567-8901 -> 123-****-8901"""
    if not num:
        return num
    parts = num.split("-")
    if len(parts) != 3:
        return num
    return f"{parts[0]}-{'*' * len(parts[1])}-{parts[2]}"
