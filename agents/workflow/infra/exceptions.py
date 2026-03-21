class ProviderError(Exception):
    def __init__(self, message="", provider=None, model=None, details=None):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.details = details

    def __str__(self):
        return f"{self.__class__.__name__}: {self.args[0]} (provider={self.provider}, model={self.model})"

    def to_dict(self):
        return {
            "type": self.__class__.__name__,
            "message": self.args[0],
            "provider": self.provider,
            "model": self.model,
            "details": self.details,
        }


class RateLimitError(ProviderError):
    def __init__(self, retry_after=None, **kwargs):
        super().__init__(**kwargs)
        self.retry_after = retry_after


class ModelUnavailableError(ProviderError):
    pass


class ContextExhaustedError(ProviderError):
    pass


class ProviderQuotaExhaustedError(ProviderError):
    pass