from shop.models import AdminActivityLog


SECRET_KEYS = {"password", "pass", "secret", "token", "key", "credential", "mfa", "otp"}


def request_ip(request):
    if not request:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    value = (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or ""
    return value or None


def sanitized_value(value):
    if value is None:
        return None
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(secret_key in key_text for secret_key in SECRET_KEYS):
                cleaned[key] = "[redacted]"
            else:
                cleaned[key] = sanitized_value(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [sanitized_value(item) for item in value]
    return value


def log_admin_activity(
    request=None,
    actor=None,
    action="",
    model_name="",
    object_id="",
    object_repr="",
    old_value=None,
    new_value=None,
    severity=AdminActivityLog.SEVERITY_INFO,
):
    if actor is None and request is not None:
        user = getattr(request, "user", None)
        actor = user if getattr(user, "is_authenticated", False) else None
    return AdminActivityLog.objects.create(
        actor=actor,
        action=action,
        model_name=model_name or "Admin",
        object_id=str(object_id or ""),
        object_repr=str(object_repr or "")[:300],
        old_value=sanitized_value(old_value),
        new_value=sanitized_value(new_value),
        ip_address=request_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:500] if request else ""),
        severity=severity,
    )
