from rest_framework.response import Response
from rest_framework.views import exception_handler


class ApplicationError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if isinstance(exc, ApplicationError):
        return Response(
            {"success": False, "message": str(exc), "data": None}, status=exc.status_code
        )

    if response is not None:
        message = "Validation Error" if response.status_code == 400 else "Error"
        response.data = {"success": False, "message": message, "data": response.data}
    return response
