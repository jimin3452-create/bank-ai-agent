def mask_account_num(num: str | None) -> str | None:
    """123-4567-8901 -> 123-****-8901"""
    if not num:
        return num
    parts = num.split("-")
    if len(parts) != 3:
        return num
    return f"{parts[0]}-{'*' * len(parts[1])}-{parts[2]}"


def mask_name(name: str | None) -> str | None:
    """박서준 -> 박*준, 김수 -> 김*"""
    if not name:
        return name
    if len(name) == 1:
        return "*"
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]
