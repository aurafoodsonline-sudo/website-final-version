from django.conf import settings


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("X-Frame-Options", "DENY")
        response.setdefault("Referrer-Policy", getattr(settings, "REFERRER_POLICY", "strict-origin-when-cross-origin"))
        policy = getattr(settings, "CSP_REPORT_ONLY_POLICY", "")
        report_uri = getattr(settings, "CSP_REPORT_URI", "")
        if policy:
            if report_uri and "report-uri" not in policy:
                policy = f"{policy}; report-uri {report_uri}"
            header = (
                "Content-Security-Policy-Report-Only"
                if getattr(settings, "CSP_REPORT_ONLY", True)
                else "Content-Security-Policy"
            )
            response.setdefault(header, policy)
        return response
