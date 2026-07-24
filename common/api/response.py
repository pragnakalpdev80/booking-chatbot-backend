from rest_framework.response import Response


class ApiResponse(Response):
    def __init__(self, data=None, message="Success", status=200, **kwargs):
        payload = {
            "success": status < 400,
            "message": message,
            "data": data,
        }
        super().__init__(data=payload, status=status, **kwargs)
