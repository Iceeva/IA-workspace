"""Format d'erreur unique : {success:false, error:{code,message}}."""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _body(code: str, message: str) -> dict:
    return {"success": False, "error": {"code": code, "message": message}}


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app(_: Request, e: AppError):
        return JSONResponse(_body(e.code, e.message), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, e: RequestValidationError):
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first["loc"] if x != "body")
        return JSONResponse(_body("VALIDATION_ERROR", f"{loc}: {first['msg']}"), status_code=422)

    @app.exception_handler(Exception)
    async def _any(_: Request, e: Exception):
        return JSONResponse(_body("INTERNAL_ERROR", "Erreur interne"), status_code=500)
