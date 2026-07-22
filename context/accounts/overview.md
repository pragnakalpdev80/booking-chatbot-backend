# Accounts App Overview

> **Namespace:** `apps.accounts`
> **Purpose:** Handles user self-registration, user profile management, and JWT-based authentication.

---

## 1. Core Responsibilities

The `accounts` app strictly handles identity and access management for **Users** interacting with the chatbot booking system. It extends the default Django `User` model with a `UserProfile` for additional application-specific fields without tightly coupling auth logic to business logic.

---

## 2. Models

### `UserProfile`
A one-to-one extension of the default Django `User` model.

```python
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="user_profile")
    phone = models.CharField(max_length=20, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Key Behaviors:**
- **Auto-creation:** A Django `post_save` signal automatically creates a blank `UserProfile` instance whenever a new `User` is created. This ensures `user.user_profile` never raises a `DoesNotExist` exception for newly registered users.

```python
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)
```

---

## 3. Endpoints & Views

### Authentication (JWT)
The system relies on `djangorestframework-simplejwt` for authentication. 

| Endpoint | Action | Payload | Response |
|----------|--------|---------|----------|
| `POST /api/accounts/login/` | Validates credentials | `{"username": "...", "password": "..."}` | `{"access": "<jwt>", "refresh": "<jwt>"}` |
| `POST /api/accounts/token/refresh/` | Issues new access token | `{"refresh": "<jwt>"}` | `{"access": "<jwt>"}` |

### Registration & Profile

#### `POST /api/accounts/register/` (Public)
Creates a new User and their associated UserProfile.
- **Expected Payload:**
  ```json
  {
      "first_name": "John",
      "last_name": "Doe",
      "username": "johndoe",
      "email": "john@example.com",
      "password": "SecurePassword123!",
      "password2": "SecurePassword123!",
      "phone": "555-1234"
  }
  ```
- **Response (201 Created):**
  ```json
  {
      "message": "Registration successful.",
      "user_id": 1,
      "username": "johndoe"
  }
  ```

#### `GET /api/accounts/me/` (JWT Required)
Retrieves the authenticated user's profile information.
- **Response (200 OK):**
  ```json
  {
      "id": 1,
      "username": "johndoe",
      "email": "john@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "profile": {
          "phone": "555-1234",
          "date_of_birth": null
      }
  }
  ```

---

## 4. Dependencies & Interactions
- Inherits core JWT configuration from `djangorestframework-simplejwt` initialized in `config/settings/base.py`.
- Generates the base User objects that the `apps.calendar_app.Booking` and `apps.chatbot.ConversationSession` models link to via ForeignKeys.
