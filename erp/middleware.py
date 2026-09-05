from __future__ import annotations

import secrets

from django.conf import settings


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(18)
        response = self.get_response(request)
        response.setdefault("Referrer-Policy", getattr(settings, "REFERRER_POLICY", "strict-origin-when-cross-origin"))
        response.setdefault("Permissions-Policy", getattr(settings, "PERMISSIONS_POLICY", "geolocation=(), microphone=(), camera=()"))
        csp = getattr(settings, "CONTENT_SECURITY_POLICY", "")
        if csp:
            header = "Content-Security-Policy-Report-Only" if getattr(settings, "CSP_REPORT_ONLY", False) else "Content-Security-Policy"
            response.setdefault(header, csp.format(nonce=request.csp_nonce))
        return response


def csp_nonce(request):
    return {"csp_nonce": getattr(request, "csp_nonce", "")}
