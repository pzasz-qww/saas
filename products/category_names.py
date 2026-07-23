import unicodedata


def clean_category_name(value):
    """Return a display name with surrounding/repeated whitespace removed."""
    return " ".join(str(value or "").split())


def normalize_category_name(value):
    """Build the deterministic, accent- and case-insensitive category key."""
    cleaned_name = clean_category_name(value)
    decomposed_name = unicodedata.normalize("NFD", cleaned_name)
    name_without_accents = "".join(
        character
        for character in decomposed_name
        if not unicodedata.combining(character)
    )
    return name_without_accents.casefold()
