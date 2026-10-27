"""Omnibasket v1 service: cache, solve, and page-read events."""

__all__ = ["create_app"]


def create_app():
    from api.app import create_app as _create

    return _create()
