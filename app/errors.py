"""One error type for everything the API reports to a client.

Every error leaves the service in the same shape:
    {"error": {"code": "...", "message": "..."}}
"""


class AppError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        extra: dict | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra or {}
        self.headers = headers or {}

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, **self.extra}}
