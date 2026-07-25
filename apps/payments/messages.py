from django.utils.translation import gettext_lazy as _

EMAIL_NOT_COLLECTED = _("Email must be collected before initiating payment.")
SLOT_LOCK_NOT_FOUND = _("No active slot lock found. Please select a time slot again.")
SLOT_LOCK_EXPIRED = _("Your slot reservation has expired. Please select a time again.")
ORDER_NOT_FOUND = _("Payment order not found.")
ORDER_EXPIRED = _("Payment order has expired. Please start a new booking.")
INVALID_SIGNATURE = _("Invalid payment signature.")
ORDER_ALREADY_PAID = _("This order has already been paid.")
PAYMENT_FAILED = _("Payment failed. Your slot has been released.")
