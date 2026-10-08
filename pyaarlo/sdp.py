"""Pure SDP repair helpers for the SIP/WebRTC signaling path.

Arlo's SIP proxy is fussy about the offers it accepts and sloppy about the
answers it returns. These functions patch both directions. They do no I/O and
have no dependency on the rest of pyaarlo, so they're plain unit-testable.
"""

CANDIDATE_PREFIX = "a=candidate:"
MID_PREFIX = "a=mid:"
DIRECTION_PREFIXES = ("a=send", "a=recv")
END_OF_CANDIDATES_LINE = "a=end-of-candidates"


def _split_lines(sdp):
    return [line.strip() for line in sdp.replace("\r\n", "\n").split("\n") if line.strip() != ""]


def _join_lines(lines):
    # RFC 4566 terminates every line, including the last, with CRLF. A
    # bare "\r\n".join(...) leaves the final line unterminated - harmless
    # to most parsers, but Chrome's rejects exactly that line outright
    # ("Failed to parse SessionDescription... Invalid SDP line") when it's
    # also the last line of the whole message.
    if not lines:
        return ""
    return "\r\n".join(lines) + "\r\n"


def filter_offer_candidates(sdp):
    """Strip ICE candidates Arlo's SIP proxy rejects.

    Removes IPv6 candidates (recognized by a second `:` beyond the
    `a=candidate:` prefix) and mDNS `.local` candidates. Without this filter
    the INVITE is accepted but negotiation silently fails to connect.
    """
    lines = []
    for line in _split_lines(sdp):
        if line.startswith(CANDIDATE_PREFIX):
            if line.count(":") <= 1 and ".local" not in line:
                lines.append(line)
        else:
            lines.append(line)
    return _join_lines(lines)


def clean_answer(sdp):
    """Repair the SDP answer Arlo's SIP proxy returns.

    Arlo omits `a=mid` and direction attributes on its answer, which most
    WebRTC peers reject outright. This inserts, immediately after each `m=`
    line, whatever of `a=mid:<n>` / `a=sendrecv` (audio) / `a=sendonly`
    (video) is missing.

    Also drops `a=end-of-candidates` (RFC 8840): it signals that trickle
    ICE has finished sending candidates, which is meaningless here - this
    module never trickles, it exchanges one complete offer/answer pair -
    and Chrome's SDP parser rejects it outright wherever Arlo places it.
    """
    result = []
    section = None
    section_lines = []

    def flush_section():
        if section is None:
            return
        has_mid = any(line.startswith(MID_PREFIX) for line in section_lines)
        has_direction = any(
            line.startswith(DIRECTION_PREFIXES) for line in section_lines
        )
        if not has_mid:
            result.append(MID_PREFIX + ("0" if section == "audio" else "1"))
        if not has_direction:
            result.append("a=sendrecv" if section == "audio" else "a=sendonly")
        result.extend(section_lines)

    for line in _split_lines(sdp):
        if line == END_OF_CANDIDATES_LINE:
            continue
        if line.startswith("m="):
            flush_section()
            section_lines = []
            if line.startswith("m=audio"):
                section = "audio"
            elif line.startswith("m=video"):
                section = "video"
            else:
                section = None
            result.append(line)
        elif section is not None:
            section_lines.append(line)
        else:
            result.append(line)
    flush_section()

    return _join_lines(result)
