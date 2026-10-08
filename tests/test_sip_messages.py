from unittest import TestCase

from pyaarlo.sip import (
    ArloSip,
    ArloSipAuthError,
    ArloSipError,
    ArloSipProtocolError,
    ArloSipTimeout,
    AuthHeader,
    SipMessage,
    SipState,
    build_ack_from_response,
    build_bye_from_response,
    build_invite,
    build_message,
)


class _FakeArlo(object):
    def debug(self, msg):
        pass

    def vdebug(self, msg):
        pass


class _FakeCamera(object):
    device_id = "device-abc"
    model_id = "VMC4070"
    unique_id = "unique-abc"
    xcloud_id = "xcloud-abc"


class _FakeBackend(object):
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, path, params=None, headers=None, **kwargs):
        self.calls.append({"path": path, "params": params, "headers": headers, "kwargs": kwargs})
        return self.response


class _FakeArloWithBackend(_FakeArlo):
    def __init__(self, response):
        self.be = _FakeBackend(response)


class TestSipMessageParsing(TestCase):
    def test_round_trip_request(self):
        original = SipMessage("INVITE sip:callee@example.com SIP/2.0")
        original.add_header("Via", "SIP/2.0/WSS abc.invalid;branch=z9hG4bK1234567")
        original.add_header("Call-ID", "call-id-1")
        original.add_header("CSeq", "1 INVITE")
        original.body = "v=0\r\no=- 1 1 IN IP4 0.0.0.0\r\n"

        parsed = SipMessage.parse(original.to_wire())

        self.assertEqual(parsed.start_line, "INVITE sip:callee@example.com SIP/2.0")
        self.assertEqual(parsed.get_header("Call-ID"), "call-id-1")
        self.assertEqual(parsed.get_header("Via"), "SIP/2.0/WSS abc.invalid;branch=z9hG4bK1234567")
        self.assertEqual(parsed.cseq_number, 1)
        self.assertEqual(parsed.method, "INVITE")
        self.assertEqual(parsed.body, "v=0\r\no=- 1 1 IN IP4 0.0.0.0\r\n")

    def test_parse_response_status_and_method(self):
        raw = (
            "SIP/2.0 407 Proxy Authentication Required\r\n"
            "Call-ID: call-id-1\r\n"
            "CSeq: 1 INVITE\r\n"
            "Proxy-Authenticate: Digest realm=\"arlo.com\", nonce=\"abc123\", algorithm=MD5, qop=\"auth\"\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
        message = SipMessage.parse(raw)
        self.assertTrue(message.is_response)
        self.assertEqual(message.status_code, 407)
        self.assertEqual(message.method, "INVITE")
        self.assertEqual(message.cseq_number, 1)

    def test_content_length_truncates_trailing_frame_padding(self):
        raw = "SIP/2.0 200 OK\r\nCall-ID: x\r\nCSeq: 1 INVITE\r\nContent-Length: 5\r\n\r\nv=0\r\ngarbage-after"
        message = SipMessage.parse(raw)
        self.assertEqual(message.body, "v=0\r\n")

    def test_get_headers_returns_all_matches_in_order(self):
        message = SipMessage("SIP/2.0 200 OK")
        message.add_header("Record-Route", "<sip:a@proxy1>")
        message.add_header("Record-Route", "<sip:b@proxy2>")
        self.assertEqual(message.get_headers("record-route"), ["<sip:a@proxy1>", "<sip:b@proxy2>"])

    def test_repeated_via_headers_survive_round_trip(self):
        message = SipMessage("SIP/2.0 200 OK")
        message.add_header("Via", "SIP/2.0/WSS host1.invalid;branch=b1")
        message.add_header("Via", "SIP/2.0/WSS host2.invalid;branch=b2")
        parsed = SipMessage.parse(message.to_wire())
        self.assertEqual(len(parsed.get_headers("via")), 2)


class TestAuthHeader(TestCase):
    CHALLENGE = 'Digest realm="testrealm@host.com", nonce="dcd98b7102dd2f0e8b11d0f600bade7", algorithm=MD5, qop="auth", opaque="5ccc069c403ebaf9f0171e9517f40e41"'

    def test_parse_extracts_all_params(self):
        header = AuthHeader.parse(self.CHALLENGE)
        self.assertEqual(header.mode, "Digest")
        self.assertEqual(header.params["realm"], "testrealm@host.com")
        self.assertEqual(header.params["nonce"], "dcd98b7102dd2f0e8b11d0f600bade7")
        self.assertEqual(header.params["algorithm"], "MD5")
        self.assertEqual(header.params["qop"], "auth")
        self.assertEqual(header.params["opaque"], "5ccc069c403ebaf9f0171e9517f40e41")

    def test_compute_response_matches_known_vector(self):
        # RFC 2617-style vector, computed independently with the same
        # ha1/ha2/response formula this implementation uses. cnonce/nc are
        # generated when absent from the challenge, so pin them first.
        header = AuthHeader.parse(self.CHALLENGE)
        header.params["cnonce"] = "0a4f113b"
        header.params["nc"] = "00000001"
        response = header.compute_response(
            method="GET",
            uri="/dir/index.html",
            username="Mufasa",
            password="Circle Of Life",
        )
        self.assertEqual(response, "edb1d9656c02b946609ca3aa321bb910")

    def test_compute_response_rejects_non_md5_algorithm(self):
        header = AuthHeader.parse('Digest realm="r", nonce="n", algorithm=SHA-256, qop="auth"')
        with self.assertRaises(ArloSipAuthError):
            header.compute_response("INVITE", "sip:callee@x", "user", "pass")

    def test_compute_response_rejects_missing_qop(self):
        header = AuthHeader.parse('Digest realm="r", nonce="n"')
        with self.assertRaises(ArloSipAuthError):
            header.compute_response("INVITE", "sip:callee@x", "user", "pass")

    def test_serialization_quotes_selectively(self):
        header = AuthHeader("Digest", {
            "username": "bob",
            "realm": "arlo.com",
            "nonce": "abc",
            "uri": "sip:callee@x",
            "response": "deadbeef",
            "algorithm": "MD5",
            "qop": "auth",
            "nc": "00000001",
            "cnonce": "xyz",
        })
        rendered = str(header)
        self.assertTrue(rendered.startswith("Digest "))
        # algorithm/qop/nc must be bare, everything else quoted.
        self.assertIn("algorithm=MD5", rendered)
        self.assertIn("qop=auth", rendered)
        self.assertIn("nc=00000001", rendered)
        self.assertIn('username="bob"', rendered)
        self.assertIn('realm="arlo.com"', rendered)
        self.assertIn('response="deadbeef"', rendered)
        self.assertNotIn('algorithm="MD5"', rendered)
        self.assertNotIn('qop="auth"', rendered)


class TestBuildInvite(TestCase):
    def test_header_shape(self):
        message = build_invite(
            caller_uri="sip:12345@sip.arlo.com:7443",
            callee_uri="sip:device-abc@sip.arlo.com",
            contact_host="abc123def456.invalid",
            device_id="device-abc",
            sdp="v=0\r\n",
            user_agent="SIP.js/0.21.1",
            call_id="call-id-1",
            tag="tag1",
            contact_user="contactuser",
            cseq=1,
            branch="z9hG4bK1234567",
        )
        self.assertEqual(message.start_line, "INVITE sip:device-abc@sip.arlo.com SIP/2.0")
        self.assertEqual(message.get_header("Via"), "SIP/2.0/WSS abc123def456.invalid;branch=z9hG4bK1234567")
        self.assertEqual(message.get_header("From"), '"WebRTC-UDP" <sip:12345@sip.arlo.com:7443>;tag=tag1')
        self.assertEqual(message.get_header("To"), "<sip:device-abc@sip.arlo.com>")
        self.assertEqual(message.get_header("Call-ID"), "call-id-1")
        self.assertEqual(message.get_header("CSeq"), "1 INVITE")
        self.assertEqual(message.get_header("Contact"), "<sip:contactuser@abc123def456.invalid;transport=ws;ob>")
        self.assertEqual(message.get_header("X-extension"), "device-abc; User-Agent: webrtc")
        self.assertEqual(message.get_header("Content-Type"), "application/sdp")
        self.assertIsNone(message.get_header("Proxy-Authorization"))
        self.assertEqual(message.body, "v=0\r\n")

    def test_proxy_authorization_included_when_given(self):
        message = build_invite(
            caller_uri="sip:12345@sip.arlo.com:7443",
            callee_uri="sip:device-abc@sip.arlo.com",
            contact_host="abc123def456.invalid",
            device_id="device-abc",
            sdp="v=0\r\n",
            user_agent="SIP.js/0.21.1",
            call_id="call-id-1",
            tag="tag1",
            contact_user="contactuser",
            cseq=2,
            proxy_authorization='Digest username="12345", realm="arlo.com"',
        )
        self.assertEqual(message.get_header("CSeq"), "2 INVITE")
        self.assertEqual(message.get_header("Proxy-Authorization"), 'Digest username="12345", realm="arlo.com"')


class TestBuildAckAndBye(TestCase):
    def _response(self):
        response = SipMessage("SIP/2.0 200 OK")
        response.add_header("Via", "SIP/2.0/WSS abc123def456.invalid;branch=z9hG4bK1234567")
        response.add_header("From", '"WebRTC-UDP" <sip:12345@sip.arlo.com:7443>;tag=tag1')
        response.add_header("To", "<sip:device-abc@sip.arlo.com>;tag=servertag")
        response.add_header("Call-ID", "call-id-1")
        response.add_header("CSeq", "1 INVITE")
        response.add_header("Record-Route", "<sip:proxy1@sip.arlo.com;lr>")
        response.add_header("Record-Route", "<sip:proxy2@sip.arlo.com;lr>")
        return response

    def test_ack_reuses_dialog_identifiers(self):
        response = self._response()
        ack = build_ack_from_response(response, "sip:device-abc@sip.arlo.com", "abc123def456.invalid", "SIP.js/0.21.1")

        self.assertEqual(ack.start_line, "ACK sip:device-abc@sip.arlo.com SIP/2.0")
        self.assertEqual(ack.get_header("Call-ID"), "call-id-1")
        self.assertEqual(ack.get_header("From"), response.get_header("From"))
        self.assertEqual(ack.get_header("To"), response.get_header("To"))
        self.assertEqual(ack.get_header("CSeq"), "1 ACK")

    def test_ack_reverses_record_route_into_route(self):
        response = self._response()
        ack = build_ack_from_response(response, "sip:device-abc@sip.arlo.com", "abc123def456.invalid", "SIP.js/0.21.1")
        self.assertEqual(
            ack.get_headers("Route"),
            ["<sip:proxy2@sip.arlo.com;lr>", "<sip:proxy1@sip.arlo.com;lr>"],
        )

    def test_ack_uses_a_fresh_branch(self):
        response = self._response()
        ack = build_ack_from_response(response, "sip:device-abc@sip.arlo.com", "abc123def456.invalid", "SIP.js/0.21.1")
        self.assertNotEqual(ack.get_header("Via"), response.get_header("Via"))
        self.assertIn("abc123def456.invalid", ack.get_header("Via"))

    def test_bye_increments_cseq_past_ack(self):
        response = self._response()
        bye = build_bye_from_response(response, "sip:device-abc@sip.arlo.com", "abc123def456.invalid", "SIP.js/0.21.1")
        self.assertEqual(bye.start_line, "BYE sip:device-abc@sip.arlo.com SIP/2.0")
        self.assertEqual(bye.get_header("CSeq"), "2 BYE")
        self.assertEqual(bye.get_header("Call-ID"), "call-id-1")
        self.assertEqual(bye.get_header("From"), response.get_header("From"))
        self.assertEqual(bye.get_header("To"), response.get_header("To"))


class TestBuildMessage(TestCase):
    def test_keepalive_payload_and_content_type(self):
        message = build_message(
            "sip:12345@sip.arlo.com:7443", "sip:device-abc@sip.arlo.com", "abc123def456.invalid", "keepAlive", "SIP.js/0.21.1"
        )
        self.assertEqual(message.start_line, "MESSAGE sip:device-abc@sip.arlo.com SIP/2.0")
        self.assertEqual(message.body, "keepAlive")
        self.assertEqual(message.get_header("Content-Type"), "text/plain")
        self.assertEqual(message.get_header("CSeq"), "1 MESSAGE")

    def test_each_message_gets_a_fresh_dialog(self):
        first = build_message("sip:c@x", "sip:d@x", "host.invalid", "keepAlive", "ua")
        second = build_message("sip:c@x", "sip:d@x", "host.invalid", "keepAlive", "ua")
        self.assertNotEqual(first.get_header("Call-ID"), second.get_header("Call-ID"))
        self.assertNotEqual(first.get_header("From"), second.get_header("From"))


class TestArloSipStateGuards(TestCase):
    def _client(self):
        return ArloSip(_FakeArlo(), _FakeCamera())

    def test_ice_servers_empty_before_connect(self):
        self.assertEqual(self._client().ice_servers, [])

    def test_start_before_connect_raises(self):
        with self.assertRaises(ArloSipError):
            self._client().start("v=0\r\n")

    def test_connect_twice_raises(self):
        sip = self._client()
        sip._state = SipState.CONNECTING  # pretend connect() already ran
        with self.assertRaises(ArloSipError):
            sip.connect()

    def test_close_from_idle_is_a_safe_noop(self):
        sip = self._client()
        sip.close()
        self.assertEqual(sip.state, SipState.CLOSED)
        sip.close()  # idempotent - must not raise or re-run teardown
        self.assertEqual(sip.state, SipState.CLOSED)


class TestArloSipTransactionDispatch(TestCase):
    """Exercises the reader-thread/queue correlation logic without a real socket."""

    def test_dispatch_delivers_final_response_and_skips_provisional(self):
        sip = ArloSip(_FakeArlo(), _FakeCamera())
        message = build_message("sip:c@x", "sip:d@x", "host.invalid", "keepAlive", "ua")

        def fake_send(msg):
            # Stands in for the reader thread: deliver a provisional
            # response first, then the final one - _send_and_wait must
            # skip the former and return the latter.
            trying = SipMessage("SIP/2.0 100 Trying")
            trying.add_header("Call-ID", msg.get_header("Call-ID"))
            trying.add_header("CSeq", msg.get_header("CSeq"))
            sip._dispatch(trying)

            accepted = SipMessage("SIP/2.0 202 Accepted")
            accepted.add_header("Call-ID", msg.get_header("Call-ID"))
            accepted.add_header("CSeq", msg.get_header("CSeq"))
            sip._dispatch(accepted)

        sip._send = fake_send
        response = sip._send_and_wait(message, timeout=1)
        self.assertEqual(response.status_code, 202)

    def test_send_and_wait_times_out_with_no_response(self):
        sip = ArloSip(_FakeArlo(), _FakeCamera())
        sip._send = lambda msg: None
        message = build_message("sip:c@x", "sip:d@x", "host.invalid", "keepAlive", "ua")
        with self.assertRaises(ArloSipTimeout):
            sip._send_and_wait(message, timeout=0.05)

    def test_unmatched_response_is_dropped_not_raised(self):
        sip = ArloSip(_FakeArlo(), _FakeCamera())
        stray = SipMessage("SIP/2.0 200 OK")
        stray.add_header("Call-ID", "nobody-is-waiting")
        stray.add_header("CSeq", "1 INVITE")
        sip._dispatch(stray)

    def test_pending_transaction_cleaned_up_after_completion(self):
        sip = ArloSip(_FakeArlo(), _FakeCamera())
        message = build_message("sip:c@x", "sip:d@x", "host.invalid", "keepAlive", "ua")

        def fake_send(msg):
            accepted = SipMessage("SIP/2.0 202 Accepted")
            accepted.add_header("Call-ID", msg.get_header("Call-ID"))
            accepted.add_header("CSeq", msg.get_header("CSeq"))
            sip._dispatch(accepted)

        sip._send = fake_send
        sip._send_and_wait(message, timeout=1)
        self.assertEqual(sip._pending, {})


class TestFetchSipInfo(TestCase):
    """Regression coverage for the raw=True bug: sipInfo/v2 is wrapped in
    Arlo's {"success": ..., "data": {...}} envelope, which pyaarlo's backend
    unwraps automatically - UNLESS raw=True is passed, in which case
    sipCallInfo silently ends up nested one level too deep and every SIP
    session fails with a misleading "no sipInfo" error.
    """

    VALID_INFO = {
        "sipCallInfo": {"id": "12345", "domain": "sip.arlo.com", "port": 5060, "calleeUri": "sip:d@x", "password": "p"},
        "iceServers": {"data": []},
    }

    def test_does_not_request_raw_mode(self):
        arlo = _FakeArloWithBackend(self.VALID_INFO)
        sip = ArloSip(arlo, _FakeCamera())
        sip._fetch_sip_info()
        self.assertEqual(len(arlo.be.calls), 1)
        self.assertNotIn("raw", arlo.be.calls[0]["kwargs"])

    def test_accepts_already_unwrapped_response(self):
        arlo = _FakeArloWithBackend(self.VALID_INFO)
        sip = ArloSip(arlo, _FakeCamera())
        result = sip._fetch_sip_info()
        self.assertEqual(result, self.VALID_INFO)

    def test_still_wrapped_response_raises_with_diagnostic_detail(self):
        # What raw=True actually produced: sipCallInfo one level too deep.
        wrapped = {"success": True, "data": self.VALID_INFO}
        arlo = _FakeArloWithBackend(wrapped)
        sip = ArloSip(arlo, _FakeCamera())
        with self.assertRaises(ArloSipProtocolError) as ctx:
            sip._fetch_sip_info()
        self.assertIn(_FakeCamera.device_id, str(ctx.exception))
        self.assertIn("success", str(ctx.exception))

    def test_request_params_and_headers(self):
        arlo = _FakeArloWithBackend(self.VALID_INFO)
        sip = ArloSip(arlo, _FakeCamera())
        sip._fetch_sip_info()
        call = arlo.be.calls[0]
        self.assertEqual(call["params"], {
            "cameraId": "device-abc",
            "modelId": "VMC4070",
            "uniqueId": "unique-abc",
        })
        self.assertEqual(call["headers"], {"xcloudId": "xcloud-abc", "cameraId": "device-abc"})

    def test_none_response_raises(self):
        arlo = _FakeArloWithBackend(None)
        sip = ArloSip(arlo, _FakeCamera())
        with self.assertRaises(ArloSipProtocolError):
            sip._fetch_sip_info()


class TestFetchInfoIsRestOnly(TestCase):
    """`fetch_info()` must stay REST-only.

    Callers need `ice_servers` before they can build an offer, and the gap
    between the two is however long their peer connection takes to gather
    ICE candidates. If fetching the credentials also opened the websocket,
    every caller would be holding an idle socket across that window - which
    is exactly what Home Assistant does between `get_client_config` and
    `offer`.
    """

    INFO = {
        "sipCallInfo": {
            "id": "12345",
            "domain": "sip.arlo.com",
            "port": 5060,
            "calleeUri": "sip:d@x",
            "password": "p",
        },
        "iceServers": {
            "data": [
                {"type": "stun", "domain": "stun.arlo.com", "port": 3478},
                {
                    "type": "turn",
                    "domain": "turn.arlo.com",
                    "port": 443,
                    "username": "u",
                    "credential": "c",
                },
            ]
        },
    }

    def _sip(self):
        return ArloSip(_FakeArloWithBackend(self.INFO), _FakeCamera())

    def test_leaves_state_idle_and_websocket_unopened(self):
        sip = self._sip()
        sip.fetch_info()
        self.assertEqual(sip.state, SipState.IDLE)
        self.assertIsNone(sip._ws)

    def test_populates_ice_servers(self):
        sip = self._sip()
        sip.fetch_info()
        self.assertEqual(sip.ice_servers, [
            {"urls": ["stun:stun.arlo.com:3478"], "username": None, "credential": None},
            {"urls": ["turn:turn.arlo.com:443"], "username": "u", "credential": "c"},
        ])

    def test_derives_the_sip_uris(self):
        sip = self._sip()
        sip.fetch_info()
        self.assertEqual(sip._username, "12345")
        self.assertEqual(sip._password, "p")
        self.assertEqual(sip._caller_uri, "sip:12345@sip.arlo.com:7443")
        self.assertEqual(sip._callee_uri, "sip:d@x")

    def test_is_idempotent(self):
        sip = self._sip()
        sip.fetch_info()
        sip.fetch_info()
        self.assertEqual(len(sip._arlo.be.calls), 1)

    def test_a_failed_fetch_does_not_poison_the_cache(self):
        sip = ArloSip(_FakeArloWithBackend(None), _FakeCamera())
        with self.assertRaises(ArloSipProtocolError):
            sip.fetch_info()
        self.assertIsNone(sip._sip_info)

    def test_ensure_connected_is_a_noop_once_connecting(self):
        sip = self._sip()
        sip._set_state(SipState.CONNECTING)
        sip.ensure_connected()
        self.assertIsNone(sip._ws)
