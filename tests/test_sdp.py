from unittest import TestCase

from pyaarlo.sdp import clean_answer, filter_offer_candidates


class TestFilterOfferCandidates(TestCase):
    def test_keeps_ipv4_host_candidate(self):
        sdp = (
            "v=0\r\n"
            "a=candidate:1467250027 1 udp 2122260223 192.168.1.5 51673 typ host generation 0\r\n"
        )
        out = filter_offer_candidates(sdp)
        self.assertIn("a=candidate:1467250027 1 udp 2122260223 192.168.1.5 51673 typ host generation 0", out)

    def test_drops_ipv6_candidate(self):
        sdp = (
            "v=0\r\n"
            "a=candidate:1 1 udp 2122260223 2001:db8::1 51673 typ host generation 0\r\n"
            "a=candidate:2 1 udp 2122260223 192.168.1.5 51673 typ host generation 0\r\n"
        )
        out = filter_offer_candidates(sdp)
        self.assertNotIn("2001:db8::1", out)
        self.assertIn("192.168.1.5", out)

    def test_drops_mdns_local_candidate(self):
        sdp = (
            "v=0\r\n"
            "a=candidate:1 1 udp 2122260223 8f3ecc46-1234-4a2f-9999-abcdefabcdef.local 51673 typ host generation 0\r\n"
            "a=candidate:2 1 udp 2122260223 192.168.1.5 51673 typ host generation 0\r\n"
        )
        out = filter_offer_candidates(sdp)
        self.assertNotIn(".local", out)
        self.assertIn("192.168.1.5", out)

    def test_keeps_non_candidate_lines_untouched(self):
        sdp = "v=0\r\no=- 123 456 IN IP4 0.0.0.0\r\ns=-\r\n"
        out = filter_offer_candidates(sdp)
        self.assertIn("o=- 123 456 IN IP4 0.0.0.0", out)
        self.assertIn("s=-", out)

    def test_normalizes_bare_lf_to_crlf(self):
        sdp = "v=0\no=- 123 456 IN IP4 0.0.0.0\n"
        out = filter_offer_candidates(sdp)
        self.assertEqual(out, "v=0\r\no=- 123 456 IN IP4 0.0.0.0\r\n")

    def test_ends_with_a_trailing_crlf(self):
        # RFC 4566 terminates every line, including the last, with CRLF.
        # Chrome's SDP parser enforces this - an unterminated last line
        # gets rejected outright ("Invalid SDP line"), which is exactly
        # what happened before this was fixed.
        sdp = "v=0\r\na=candidate:1 1 udp 2122260223 192.168.1.5 51673 typ host generation 0\r\n"
        out = filter_offer_candidates(sdp)
        self.assertTrue(out.endswith("\r\n"))
        self.assertFalse(out.endswith("\r\n\r\n"))

    def test_empty_input(self):
        self.assertEqual(filter_offer_candidates(""), "")


class TestCleanAnswer(TestCase):
    ARLO_ANSWER = (
        "v=0\r\n"
        "o=- 123 456 IN IP4 0.0.0.0\r\n"
        "s=-\r\n"
        "t=0 0\r\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        "c=IN IP4 0.0.0.0\r\n"
        "a=rtpmap:111 opus/48000/2\r\n"
        "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
        "c=IN IP4 0.0.0.0\r\n"
        "a=rtpmap:96 H264/90000\r\n"
    )

    def test_inserts_missing_mid_and_direction(self):
        out = clean_answer(self.ARLO_ANSWER)
        lines = out.split("\r\n")

        audio_idx = lines.index("m=audio 9 UDP/TLS/RTP/SAVPF 111")
        self.assertEqual(lines[audio_idx + 1], "a=mid:0")
        self.assertEqual(lines[audio_idx + 2], "a=sendrecv")

        video_idx = lines.index("m=video 9 UDP/TLS/RTP/SAVPF 96")
        self.assertEqual(lines[video_idx + 1], "a=mid:1")
        self.assertEqual(lines[video_idx + 2], "a=sendonly")

    def test_leaves_existing_mid_untouched(self):
        sdp = (
            "v=0\r\n"
            "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
            "a=mid:0\r\n"
            "a=sendrecv\r\n"
            "a=rtpmap:111 opus/48000/2\r\n"
        )
        out = clean_answer(sdp)
        # Only one a=mid:0 and one a=sendrecv should be present - no duplicate insertion.
        self.assertEqual(out.count("a=mid:0"), 1)
        self.assertEqual(out.count("a=sendrecv"), 1)

    def test_leaves_existing_direction_untouched(self):
        sdp = (
            "v=0\r\n"
            "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
            "a=recvonly\r\n"
            "a=rtpmap:96 H264/90000\r\n"
        )
        out = clean_answer(sdp)
        self.assertIn("a=recvonly", out)
        self.assertNotIn("a=sendonly", out)
        self.assertIn("a=mid:1", out)

    def test_preamble_lines_untouched(self):
        out = clean_answer(self.ARLO_ANSWER)
        self.assertTrue(out.startswith("v=0\r\no=- 123 456 IN IP4 0.0.0.0\r\ns=-\r\nt=0 0\r\n"))

    def test_audio_only_answer(self):
        sdp = "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=rtpmap:111 opus/48000/2\r\n"
        out = clean_answer(sdp)
        lines = out.split("\r\n")
        audio_idx = lines.index("m=audio 9 UDP/TLS/RTP/SAVPF 111")
        self.assertEqual(lines[audio_idx + 1], "a=mid:0")
        self.assertEqual(lines[audio_idx + 2], "a=sendrecv")

    def test_drops_end_of_candidates_at_session_level(self):
        # Real-world case: Arlo's answer rejected by Chrome with
        # "Failed to parse SessionDescription. a=end-of-candidates Invalid SDP line."
        sdp = "v=0\r\na=end-of-candidates\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=rtpmap:111 opus/48000/2\r\n"
        out = clean_answer(sdp)
        self.assertNotIn("a=end-of-candidates", out)

    def test_drops_end_of_candidates_at_media_level(self):
        sdp = (
            "v=0\r\n"
            "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
            "a=rtpmap:111 opus/48000/2\r\n"
            "a=end-of-candidates\r\n"
            "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
            "a=rtpmap:96 H264/90000\r\n"
            "a=end-of-candidates\r\n"
        )
        out = clean_answer(sdp)
        self.assertNotIn("a=end-of-candidates", out)
        # the rest of each section must survive the drop
        self.assertIn("a=rtpmap:111 opus/48000/2", out)
        self.assertIn("a=rtpmap:96 H264/90000", out)

    def test_empty_input(self):
        self.assertEqual(clean_answer(""), "")

    def test_ends_with_a_trailing_crlf(self):
        # Real-world case: Arlo's video section ends with its host
        # candidate as the very last line of the entire SDP, with no
        # terminator. Chrome's parser rejected exactly that line -
        # "Failed to parse SessionDescription. a=candidate:... Invalid
        # SDP line." - because it was left unterminated by a bare
        # "\r\n".join(...).
        sdp = (
            "v=0\r\n"
            "m=video 30264 UDP/TLS/RTP/SAVPF 102\r\n"
            "a=mid:1\r\n"
            "a=sendonly\r\n"
            "a=ice-ufrag:NZtDjwDqBKiMQhEE\r\n"
            "a=candidate:4124236056 1 udp 2130706431 34.245.199.120 30264 typ host generation 0"
        )
        out = clean_answer(sdp)
        self.assertTrue(out.endswith("typ host generation 0\r\n"))
        self.assertFalse(out.endswith("\r\n\r\n"))
