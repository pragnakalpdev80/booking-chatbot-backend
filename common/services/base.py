from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.accounts.models import User
else:
    from django.contrib.auth.models import AbstractBaseUser as User


class BaseService:
    def __init__(self, actor: "User"):
        self.actor = actor
