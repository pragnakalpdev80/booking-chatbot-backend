from rest_framework.response import Response


class ApiResponse(Response):
    def __init__(self, data=None, message="Success", status=200, **kwargs):
        payload = {
            "success": status < 400,
            "message": message,
            "data": data,
        }
        super().__init__(data=payload, status=status, **kwargs)

    @classmethod
    def paginated_response(
        cls, paginator, data, request, message="Success", status_code=200, **kwargs
    ):
        """
        Builds a consistent ApiResponse for paginated datasets.
        The pagination metadata (count, next, previous) are included
        as top-level siblings to 'data'.
        """
        payload = {
            "success": status_code < 400,
            "message": message,
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "page": paginator.page.number,
            "page_size": paginator.page_size,
            "data": data,
        }
        return Response(data=payload, status=status_code, **kwargs)
