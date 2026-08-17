from typing import cast, Optional, TYPE_CHECKING, Union

try:  # Robot Framework 7.4 and later
    from robot.api.types import Secret
except ImportError:  # pragma: no cover - Robot Framework 6.1 through 7.3, which have no Secret type
    Secret = None

if TYPE_CHECKING:
    from robot.api.types import Secret as _Secret

    # A credential, given either as plain text or as a Robot Framework ``Secret``.
    Credential = Union[str, _Secret]
    OptionalCredential = Optional[Credential]
else:
    # Built at import so the annotation names a type Robot Framework can convert to.
    # Below 7.4 there is no Secret to accept, and no way for a suite to produce one, so the
    # argument is a plain string.
    Credential = Union[str, Secret] if Secret is not None else str
    OptionalCredential = Optional[Credential]


def reveal(credential: OptionalCredential) -> Optional[str]:
    """Return the text of a credential, unwrapping a Robot Framework ``Secret``.

    Everything downstream needs the plain value: it goes into an Authorization header, and
    into the client cache key. Two ``Secret`` objects holding the same token are still
    different objects, so leaving one wrapped would make every alias miss the cache and open
    its own connection pool.

    :param credential: Token as plain text, as a ``Secret``, or None
    :return: The plain text token, or None
    """
    if Secret is not None and isinstance(credential, Secret):
        return cast(str, credential.value)
    return credential
