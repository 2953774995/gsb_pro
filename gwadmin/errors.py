"""Controlled HTTP errors."""


class HTTPError(Exception):
    def __init__(self, status=500, message="Internal Server Error", headers=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = headers or {}


class BadRequest(HTTPError):
    def __init__(self, message="Bad Request", headers=None, request=None):
        super().__init__(400, message, headers)
        self.request = request


class PayloadTooLarge(HTTPError):
    def __init__(self, message="Payload Too Large", headers=None, request=None):
        super().__init__(413, message, headers)
        self.request = request
