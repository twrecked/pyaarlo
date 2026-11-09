import asyncio
import unittest

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


class _FakeLog:
    def debug(self, msg):
        pass

    def vdebug(self, msg):
        pass


class _FakeCamera:
    device_id = "device-abc"
    model_id = "VMC4070"
    unique_id = "unique-abc"
    xcloud_id = "xcloud-abc"


class _FakeBackend:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get(self, path, params=None, headers=None, **kwargs):
        self.calls.append({"path": path, "params": params, "headers": headers, "kwargs": kwargs})
        return self.response


class _FakeCore:
    def __init__(self, response=None):
        self.log = _FakeLog()
        self.be = _FakeBackend(response)
        self.cfg = None


class TestSipMessageParsing(unittest.TestCase):
    def test_round_trip_request(self):
        original = SipMessage("INVITE sip:callee@example.com SIP/2.0")
        original.add_header("Via", "SIP/2.0/WSS abc.invalid;branch=z9hG4bK1234567")
        original.add_header("Call-ID", "call-id-1")
        original.add_header("CSeq", "1 INVITE")
        original.body = "v=0\r\n"

        wire = original.to_wire()
        self.assertIn("Content-Length: 5", wire)

        parsed = SipMessage.parse(wire)
        self.assertEqual(parsed.start_line, "INVITE sip:callee@example.com SIP/2.0")
        self.assertEqual(parsed.get_header("Via"), "SIP/2.0/WSS abc.invalid;branch=z9hG4bK1234567")
        self.assertEqual(parsed.get_header("Call-ID"), "call-id-1")
        self.assertEqual(parsed.get_header("CSeq"), "1 INVITE")
        self.assertEqual(parsed.body, "v=0\r\n")
        self.assertFalse(parsed.is_response)
        self.assertEqual(parsed.method, "INVITE")
        self.assertIsNone(parsed.status_code)

    def test_round_trip_response(self):
        wire = (
            "SIP/2.0 200 OK\r\n"
            "Via: SIP/2.0/WSS abc.invalid;branch=z9hG4bK1234567\r\n"
            "Call-ID: call-id-1\r\n"
            "CSeq: 1 INVITE\r\n"
            "Content-Type: application/sdp\r\n"
            "Content-Length: 4\r\n"
            "\r\n"
            "body"
        )
        parsed = SipMessage.parse(wire)
        self.assertTrue(parsed.is_response)
        self.assertEqual(parsed.status_code, 200)
        self.assertEqual(parsed.method, "INVITE")
        self.assertEqual(parsed.cseq_number, 1)
        self.assertEqual(parsed.body, "body")

    def test_case_insensitive_header_lookup(self):
        msg = SipMessage("INVITE sip:a@b SIP/2.0")
        msg.add_header("Content-Type", "application/sdp")
        self.assertEqual(msg.get_header("content-type"), "application/sdp")
        self.assertEqual(msg.get_header("CONTENT-TYPE"), "application/sdp")
        self.assertIsNone(msg.get_header("missing"))

    def test_multiple_headers_preserved_in_order(self):
        msg = SipMessage("INVITE sip:a@b SIP/2.0")
        msg.add_header("Via", "first")
        msg.add_header("Via", "second")
        msg.add_header("Record-Route", "<sip:proxy1>")
        msg.add_header("Record-Route", "<sip:proxy2>")
        self.assertEqual(msg.get_headers("Via"), ["first", "second"])
        self.assertEqual(msg.get_headers("Record-Route"), ["<sip:proxy1>", "<sip:proxy2>"])

    def test_content_length_slices_body(self):
        wire = (
            "SIP/2.0 200 OK\r\n"
            "Content-Length: 3\r\n"
            "\r\n"
            "abcdef"
        )
        parsed = SipMessage.parse(wire)
        self.assertEqual(parsed.body, "abc")

    def test_empty_message_raises_protocol_error(self):
        with self.assertRaises(ArloSipProtocolError):
            SipMessage.parse("")


class TestAuthHeader(unittest.TestCase):
    def test_parse_challenge(self):
        header = (
            'Digest realm="arlo.com", nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093", '
            'algorithm=MD5, qop="auth"'
        )
        parsed = AuthHeader.parse(header)
        self.assertEqual(parsed.mode, "Digest")
        self.assertEqual(parsed.params["realm"], "arlo.com")
        self.assertEqual(parsed.params["nonce"], "dcd98b7102dd2f0e8b11d0f600bfb0c093")
        self.assertEqual(parsed.params["algorithm"], "MD5")
        self.assertEqual(parsed.params["qop"], "auth")

    def test_missing_challenge_raises(self):
        with self.assertRaises(ArloSipProtocolError):
            AuthHeader.parse(None)

    def test_renders_unquoted_and_quoted_params(self):
        auth = AuthHeader("Digest", {
            "realm": "arlo.com",
            "algorithm": "MD5",
            "qop": "auth",
            "nc": "00000001",
            "cnonce": "xyz",
            "response": "abc",
        })
        rendered = str(auth)
        self.assertIn('realm="arlo.com"', rendered)
        self.assertIn("algorithm=MD5", rendered)
        self.assertIn("qop=auth", rendered)
        self.assertIn("nc=00000001", rendered)

    CHALLENGE = 'Digest realm="testrealm@host.com", nonce="dcd98b7102dd2f0e8b11d0f600bade7", algorithm=MD5, qop="auth", opaque="5ccc069c403ebaf9f0171e9517f40e41"'

    def test_compute_response_rfc_2617_vectors(self):
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

    def test_unsupported_algorithm_raises(self):
        auth = AuthHeader("Digest", {"realm": "r", "nonce": "n", "algorithm": "SHA-256", "qop": "auth"})
        with self.assertRaises(ArloSipAuthError):
            auth.compute_response("INVITE", "sip:d@x", "u", "p")

    def test_unsupported_qop_raises(self):
        auth = AuthHeader("Digest", {"realm": "r", "nonce": "n", "qop": "auth-int"})
        with self.assertRaises(ArloSipAuthError):
            auth.compute_response("INVITE", "sip:d@x", "u", "p")

    def test_missing_nonce_raises(self):
        auth = AuthHeader("Digest", {"realm": "r", "qop": "auth"})
        with self.assertRaises(ArloSipAuthError):
            auth.compute_response("INVITE", "sip:d@x", "u", "p")


class TestBuildInvite(unittest.TestCase):
    def test_build_invite_headers_and_body(self):
        invite = build_invite(
            caller_uri="sip:user@domain.com:7443",
            callee_uri="sip:device@domain.com",
            contact_host="contact.invalid",
            device_id="cam-123",
            sdp="v=0\r\n",
            user_agent="TestUA/1.0",
            call_id="call-1",
            tag="tag-1",
            contact_user="contact-user",
            cseq=1,
            branch="branch-1",
            proxy_authorization='Digest username="u"',
        )
        self.assertEqual(invite.start_line, "INVITE sip:device@domain.com SIP/2.0")
        self.assertEqual(invite.get_header("Via"), "SIP/2.0/WSS contact.invalid;branch=branch-1")
        self.assertEqual(invite.get_header("X-extension"), "cam-123; User-Agent: webrtc")
        self.assertEqual(invite.get_header("Contact"), "<sip:contact-user@contact.invalid;transport=ws;ob>")
        self.assertEqual(invite.get_header("Proxy-Authorization"), 'Digest username="u"')
        self.assertEqual(invite.body, "v=0\r\n")


class TestBuildAckAndBye(unittest.TestCase):
    def setUp(self):
        self.resp = SipMessage("SIP/2.0 200 OK")
        self.resp.add_header("From", '"Caller" <sip:c@x>;tag=123')
        self.resp.add_header("To", '<sip:callee@x>;tag=456')
        self.resp.add_header("Call-ID", "call-id-1")
        self.resp.add_header("CSeq", "1 INVITE")
        self.resp.add_header("Record-Route", "<sip:proxy1;lr>")
        self.resp.add_header("Record-Route", "<sip:proxy2;lr>")

    def test_build_ack(self):
        ack = build_ack_from_response(self.resp, "sip:callee@x", "host.invalid", "UA")
        self.assertEqual(ack.start_line, "ACK sip:callee@x SIP/2.0")
        self.assertEqual(ack.get_header("From"), '"Caller" <sip:c@x>;tag=123')
        self.assertEqual(ack.get_header("To"), '<sip:callee@x>;tag=456')
        self.assertEqual(ack.get_header("Call-ID"), "call-id-1")
        self.assertEqual(ack.get_header("CSeq"), "1 ACK")
        # Route set is reversed Record-Route
        self.assertEqual(ack.get_headers("Route"), ["<sip:proxy2;lr>", "<sip:proxy1;lr>"])

    def test_build_bye(self):
        bye = build_bye_from_response(self.resp, "sip:callee@x", "host.invalid", "UA")
        self.assertEqual(bye.start_line, "BYE sip:callee@x SIP/2.0")
        self.assertEqual(bye.get_header("CSeq"), "2 BYE")
        self.assertEqual(bye.get_header("Call-ID"), "call-id-1")


class TestBuildMessage(unittest.TestCase):
    def test_build_message(self):
        msg = build_message("sip:c@x", "sip:d@x", "host.invalid", "keepAlive", "UA")
        self.assertEqual(msg.start_line, "MESSAGE sip:d@x SIP/2.0")
        self.assertEqual(msg.get_header("Content-Type"), "text/plain")
        self.assertEqual(msg.body, "keepAlive")
        self.assertEqual(msg.get_header("CSeq"), "1 MESSAGE")


class TestArloSipStateGuards(unittest.TestCase):
    def test_cannot_start_from_idle(self):
        sip = ArloSip(_FakeCore(), _FakeCamera())
        with self.assertRaises(ArloSipError) as ctx:
            asyncio.run(sip.start("v=0\r\n"))
        self.assertIn("cannot start from state idle", str(ctx.exception))

    def test_cannot_connect_when_not_idle(self):
        sip = ArloSip(_FakeCore(), _FakeCamera())
        sip._set_state(SipState.CONNECTING)
        with self.assertRaises(ArloSipError) as ctx:
            asyncio.run(sip.connect())
        self.assertIn("cannot connect from state connecting", str(ctx.exception))


class TestArloSipTransactionDispatch(unittest.IsolatedAsyncioTestCase):
    async def test_send_and_wait_dispatch(self):
        sip = ArloSip(_FakeCore(), _FakeCamera())
        message = build_message("sip:c@x", "sip:d@x", "host.invalid", "keepAlive", "ua")

        async def fake_send(msg):
            # Send provisional 100 Trying, then 202 Accepted
            trying = SipMessage("SIP/2.0 100 Trying")
            trying.add_header("Call-ID", msg.get_header("Call-ID"))
            trying.add_header("CSeq", msg.get_header("CSeq"))
            sip._dispatch(trying)

            accepted = SipMessage("SIP/2.0 202 Accepted")
            accepted.add_header("Call-ID", msg.get_header("Call-ID"))
            accepted.add_header("CSeq", msg.get_header("CSeq"))
            sip._dispatch(accepted)

        sip._send = fake_send
        resp = await sip._send_and_wait(message, timeout=1)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(sip._pending, {})

    async def test_send_and_wait_timeout(self):
        sip = ArloSip(_FakeCore(), _FakeCamera())
        message = build_message("sip:c@x", "sip:d@x", "host.invalid", "keepAlive", "ua")

        async def fake_send(msg):
            pass

        sip._send = fake_send
        with self.assertRaises(ArloSipTimeout):
            await sip._send_and_wait(message, timeout=0.05)

    async def test_full_start_handshake_with_digest_auth(self):
        sip = ArloSip(_FakeCore(), _FakeCamera())
        sip._set_state(SipState.CONNECTING)
        sip._caller_uri = "sip:user@domain.com:7443"
        sip._callee_uri = "sip:callee@domain.com"
        sip._username = "user"
        sip._password = "password"

        sent_messages = []

        async def fake_send(msg):
            sent_messages.append(msg)
            if msg.method == "INVITE" and not msg.get_header("Proxy-Authorization"):
                challenge = SipMessage("SIP/2.0 407 Proxy Authentication Required")
                challenge.add_header("Call-ID", msg.get_header("Call-ID"))
                challenge.add_header("CSeq", msg.get_header("CSeq"))
                challenge.add_header(
                    "Proxy-Authenticate",
                    'Digest realm="domain.com", nonce="nonce123", algorithm=MD5, qop="auth"',
                )
                sip._dispatch(challenge)
            elif msg.method == "INVITE" and msg.get_header("Proxy-Authorization"):
                ok = SipMessage("SIP/2.0 200 OK")
                ok.add_header("Call-ID", msg.get_header("Call-ID"))
                ok.add_header("CSeq", msg.get_header("CSeq"))
                ok.add_header("Content-Type", "application/sdp")
                ok.body = "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\nc=IN IP4 0.0.0.0\r\na=rtpmap:96 H264/90000\r\n"
                sip._dispatch(ok)

        sip._send = fake_send
        offer_sdp = "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=candidate:1 1 udp 2122260223 192.168.1.5 51673 typ host generation 0\r\n"
        answer_sdp = await sip.start(offer_sdp)

        self.assertEqual(sip.state, SipState.ESTABLISHED)
        self.assertIn("a=mid:1", answer_sdp)
        self.assertIn("a=sendonly", answer_sdp)

        # Verify sent sequence: INVITE -> ACK -> INVITE (with auth) -> ACK
        methods = [m.method for m in sent_messages]
        self.assertEqual(methods, ["INVITE", "ACK", "INVITE", "ACK"])
        self.assertIsNotNone(sent_messages[2].get_header("Proxy-Authorization"))

        # Now test close() sends BYE
        await sip.close()
        self.assertEqual(sip.state, SipState.CLOSED)
        self.assertEqual(sent_messages[-1].method, "BYE")



class TestFetchSipInfo(unittest.IsolatedAsyncioTestCase):
    VALID_INFO = {
        "sipCallInfo": {
            "id": "12345",
            "domain": "sip.arlo.com",
            "port": 5060,
            "calleeUri": "sip:d@x",
            "password": "p",
        },
        "iceServers": {"data": []},
    }

    async def test_does_not_request_raw_mode(self):
        core = _FakeCore(self.VALID_INFO)
        sip = ArloSip(core, _FakeCamera())
        await sip._fetch_sip_info()
        self.assertEqual(len(core.be.calls), 1)
        self.assertNotIn("raw", core.be.calls[0]["kwargs"])

    async def test_accepts_already_unwrapped_response(self):
        core = _FakeCore(self.VALID_INFO)
        sip = ArloSip(core, _FakeCamera())
        result = await sip._fetch_sip_info()
        self.assertEqual(result, self.VALID_INFO)

    async def test_still_wrapped_response_raises_with_diagnostic_detail(self):
        wrapped = {"success": True, "data": self.VALID_INFO}
        core = _FakeCore(wrapped)
        sip = ArloSip(core, _FakeCamera())
        with self.assertRaises(ArloSipProtocolError) as ctx:
            await sip._fetch_sip_info()
        self.assertIn(_FakeCamera.device_id, str(ctx.exception))
        self.assertIn("success", str(ctx.exception))

    async def test_request_params_and_headers(self):
        core = _FakeCore(self.VALID_INFO)
        sip = ArloSip(core, _FakeCamera())
        await sip._fetch_sip_info()
        call = core.be.calls[0]
        self.assertEqual(call["params"], {
            "cameraId": "device-abc",
            "modelId": "VMC4070",
            "uniqueId": "unique-abc",
        })
        self.assertEqual(call["headers"], {"xcloudId": "xcloud-abc", "cameraId": "device-abc"})

    async def test_none_response_raises(self):
        core = _FakeCore(None)
        sip = ArloSip(core, _FakeCamera())
        with self.assertRaises(ArloSipProtocolError):
            await sip._fetch_sip_info()


class TestFetchInfoIsRestOnly(unittest.IsolatedAsyncioTestCase):
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
        return ArloSip(_FakeCore(self.INFO), _FakeCamera(), ws_port=7443)

    async def test_leaves_state_idle_and_websocket_unopened(self):
        sip = self._sip()
        await sip.fetch_info()
        self.assertEqual(sip.state, SipState.IDLE)
        self.assertIsNone(sip._ws)

    async def test_populates_ice_servers(self):
        sip = self._sip()
        await sip.fetch_info()
        self.assertEqual(sip.ice_servers, [
            {"urls": ["stun:stun.arlo.com:3478"], "username": None, "credential": None},
            {"urls": ["turn:turn.arlo.com:443"], "username": "u", "credential": "c"},
        ])

    async def test_derives_the_sip_uris(self):
        sip = self._sip()
        await sip.fetch_info()
        self.assertEqual(sip._username, "12345")
        self.assertEqual(sip._password, "p")
        self.assertEqual(sip._caller_uri, "sip:12345@sip.arlo.com:7443")
        self.assertEqual(sip._callee_uri, "sip:d@x")

    async def test_is_idempotent(self):
        sip = self._sip()
        await sip.fetch_info()
        await sip.fetch_info()
        self.assertEqual(len(sip._core.be.calls), 1)

    async def test_a_failed_fetch_does_not_poison_the_cache(self):
        sip = ArloSip(_FakeCore(None), _FakeCamera())
        with self.assertRaises(ArloSipProtocolError):
            await sip.fetch_info()
        self.assertIsNone(sip._sip_info)

    async def test_ensure_connected_is_a_noop_once_connecting(self):
        sip = self._sip()
        sip._set_state(SipState.CONNECTING)
        await sip.ensure_connected()
        self.assertIsNone(sip._ws)
