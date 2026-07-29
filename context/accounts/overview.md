# Context — `apps/accounts/`

## Purpose

The `accounts` app handles identity, registration, authentication, and profile management for Providers (doctors/admins). It is exclusively used for the admin portal side of the application; patients/users who book via the chatbot are anonymous and do not use this app.

## Key models (`models.py`)

- `UserProfile` — A One-to-One extension of Django's built-in `User` model.
  - Stores additional fields such as `phone` and `date_of_birth`.
  - Created automatically via a `post_save` signal whenever a new `User` is instantiated.

## Key endpoints (`/api/accounts/`)

- `POST /register/` (`RegisterView`) — Allows a new provider to sign up. Creates the Django `User`. (`AllowAny`)
- `POST /login/` (`TokenObtainPairView`) — Standard simplejwt endpoint to exchange username/password for access/refresh JWT tokens. (`AllowAny`)
- `POST /token/refresh/` (`TokenRefreshView`) — Standard simplejwt endpoint to refresh a JWT. (`AllowAny`)
- `GET /me/` (`MeView`) — Retrieves the currently authenticated provider's user data and profile. (`IsAuthenticated`)
- `GET /providers/` (`ProviderListView`) — Returns a public list of available providers, utilized by the frontend to route chatbot requests to the correct doctor. Only returns providers with valid settings. (`AllowAny`)

## Design decisions

- **Decoupled User Identity**: The system strictly separates provider identities (who log in to the dashboard via JWT) from patient identities (who interact anonymously via UUID sessions and emails).
- **Auto-Provisioning**: The `post_save` receiver on `User` ensures `UserProfile` is never missing, removing the need to handle `ObjectDoesNotExist` in views when serializing the profile.
