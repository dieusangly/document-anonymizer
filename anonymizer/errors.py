class AnonymizerError(ValueError):
    """A safe, user-facing error. Never include source content in messages."""


class UnsupportedDocument(AnonymizerError):
    pass


class MappingError(AnonymizerError):
    pass
