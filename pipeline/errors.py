class ConfigError(RuntimeError):
    """Missing setup (an API key, a search engine ID) rather than a
    data-availability problem -- retrying elsewhere won't fix this, so
    the caller should surface it immediately instead of trying another
    region."""
