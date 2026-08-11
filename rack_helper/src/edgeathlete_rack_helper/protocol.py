"""Parse the fixed custom protocol without interpreting it as a general URL."""

LAUNCH_URI_BYTES = b"edgeathlete-rack:launch"


class ProtocolArgumentError(ValueError):
    pass


def parse_arguments(arguments):
    if len(arguments) == 0:
        return "manual"
    if len(arguments) != 1:
        raise ProtocolArgumentError("invalid protocol arguments")
    try:
        encoded = arguments[0].encode("ascii", "strict")
    except (UnicodeEncodeError, AttributeError):
        raise ProtocolArgumentError("invalid protocol arguments") from None
    if encoded != LAUNCH_URI_BYTES:
        raise ProtocolArgumentError("invalid protocol arguments")
    return "launch"
