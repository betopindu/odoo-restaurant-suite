class FiscalCredentialMaterialProvider:
    """Base interface for transient fiscal credential material providers."""

    provider_type = None

    def __init__(self, env):
        self.env = env

    def load_material(self, credential):
        """Return transient credential material for the supplied reference."""
        raise NotImplementedError


class FiscalCredentialProviderRegistry:
    PROVIDERS = {}

    @classmethod
    def register(cls, provider_class):
        provider_type = getattr(provider_class, "provider_type", None)
        if not provider_type:
            raise ValueError("Fiscal credential provider_type is required.")
        cls.PROVIDERS[provider_type] = provider_class
        return provider_class

    @classmethod
    def unregister(cls, provider_type):
        cls.PROVIDERS.pop(provider_type, None)

    @classmethod
    def get_provider_class(cls, provider_type):
        try:
            return cls.PROVIDERS[provider_type]
        except KeyError as error:
            raise LookupError(
                f"No fiscal credential provider is registered for {provider_type}."
            ) from error

    def __init__(self, env):
        self.env = env

    def get_provider(self, credential):
        provider_class = self.get_provider_class(credential.provider_type)
        return provider_class(self.env)
