# Context — `common/`

## Purpose

The `common` module provides shared, feature-agnostic utilities, constants, and baseline API response structures used across all applications in the project. It ensures a consistent developer experience and uniform API contracts.

## Key Components

### 1. Permissions (`permissions.py`)
- **`IsProviderUser`**: A custom DRF permission class that ensures the requester is authenticated and their `UserProfile` has `is_provider = True`. This explicitly protects the React dashboard and Calendar settings endpoints from regular non-provider users without exposing the built-in Django Admin panel.

### 2. `ApiResponse` (`common/api/response.py`)
A custom subclass of DRF's `Response` that standardizes all JSON outputs across the backend.
- Wraps output in a standard envelope: `{"success": bool, "message": str, "data": Any}`.
- Provides a `paginated_response` classmethod that hoists pagination metadata (`count`, `next`, `previous`, `page`, `page_size`) to the top level alongside `data` and `success`.

### 3. Exception Handling (`common/api/exceptions.py` & `config/exception_handler.py`)
- **`ApplicationError`**: A base exception class for predictable business-logic errors, accepting a message and standard HTTP status code (defaults to 400).
- **`custom_exception_handler`**: Plugs into DRF's global exception handler. It catches `ApplicationError` and normal DRF validation errors, forcing them into the standard `{"success": False, "message": "...", "data": ...}` envelope.
- This ensures the frontend never receives unstructured raw HTML or bare error traces on anticipated failures.

### 3. Caching & Core Services
- Contains placeholders and base classes (`BaseService`, `BaseSelector`) enforcing the separation-of-concerns pattern where business logic lives in services/selectors, not views.
- Cache utilities like `read_through` and TTL constants (`CacheTTL.HOUR`) are defined here for system-wide performance tuning.
