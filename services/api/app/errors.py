from fastapi import HTTPException


class ProviderError(Exception):
    def __init__(self, code: str, provider_id: str, message: str):
        self.code = code
        self.provider_id = provider_id
        self.safe_message = message
        super().__init__(message)


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})
