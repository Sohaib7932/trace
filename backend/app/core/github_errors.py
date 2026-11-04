"""Sanitized provider-independent Project Learning failures."""

from app.core.errors import ApplicationError


def unavailable() -> ApplicationError:
    return ApplicationError("github_unavailable", "GitHub connection is unavailable.", 503)
