class BusinessError(Exception):
    """A user-visible business conflict or exhausted execution budget."""


class ModelError(Exception):
    """A sanitized model transport or protocol error."""


class BudgetExceeded(BusinessError):
    """Persisted execution limits prevent another call."""
