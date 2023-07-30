from unittest import TestCase
import tests.arlo


class TestArloCfg(TestCase):
    def test_scheme(self):
        arlo = tests.arlo.PyArlo()
        self.assertEqual(arlo.cfg._remove_scheme("abc.com"), "abc.com")
        self.assertEqual(arlo.cfg._remove_scheme("https://abc.com"), "abc.com")
        self.assertEqual(arlo.cfg._add_scheme("abc.com"), "https://abc.com")
        self.assertEqual(arlo.cfg._add_scheme("https://abc.com"), "https://abc.com")
        self.assertEqual(arlo.cfg._add_scheme("http://abc.com"), "http://abc.com")
        self.assertEqual(arlo.cfg._add_scheme("abc.com", "imap"), "imap://abc.com")
        self.assertEqual(arlo.cfg._add_scheme("https://abc.com", "imap"), "https://abc.com")

    def test_host_00(self):
        arlo = tests.arlo.PyArlo()
        self.assertEqual(arlo.cfg.tfa_host, "pyaarlo-tfa.appspot.com")
        self.assertEqual(arlo.cfg.tfa_port, 993)

    def test_host_10(self):
        arlo = tests.arlo.PyArlo(tfa_host="imap.gmail.com")
        self.assertEqual(arlo.cfg.tfa_host, "imap.gmail.com")
        self.assertEqual(arlo.cfg.tfa_port, 993)

    def test_host_11(self):
        arlo = tests.arlo.PyArlo(tfa_host="imap://imap.gmail.com")
        self.assertEqual(arlo.cfg.tfa_host, "imap.gmail.com")
        self.assertEqual(arlo.cfg.tfa_port, 993)

    def test_host_20(self):
        arlo = tests.arlo.PyArlo(tfa_host="imap.gmail.com:998")
        self.assertEqual(arlo.cfg.tfa_host, "imap.gmail.com")
        self.assertEqual(arlo.cfg.tfa_port, 998)

    def test_host_21(self):
        arlo = tests.arlo.PyArlo(tfa_host="imap://imap.gmail.com:998")
        self.assertEqual(arlo.cfg.tfa_host, "imap.gmail.com")
        self.assertEqual(arlo.cfg.tfa_port, 998)

    def test_host_30(self):
        arlo = tests.arlo.PyArlo(tfa_host="https://imap.gmail.com")
        self.assertEqual(arlo.cfg.tfa_host, "imap.gmail.com")
        self.assertEqual(arlo.cfg.tfa_port, 993)

    def test_host_31(self):
        arlo = tests.arlo.PyArlo(tfa_host="https://imap.gmail.com:998")
        self.assertEqual(arlo.cfg.tfa_host, "imap.gmail.com")
        self.assertEqual(arlo.cfg.tfa_port, 998)

    def test_host_40(self):
        arlo = tests.arlo.PyArlo(host="https://testhost.com", auth_host="https://testhost.com", mqtt_host="https://testhost.com")
        self.assertEqual(arlo.cfg.host, "https://testhost.com")
        self.assertEqual(arlo.cfg.auth_host, "https://testhost.com")
        self.assertEqual(arlo.cfg.mqtt_host, "testhost.com")

    def test_host_41(self):
        arlo = tests.arlo.PyArlo(host="testhost.com", auth_host="testhost.com", mqtt_host="testhost.com")
        self.assertEqual(arlo.cfg.host, "https://testhost.com")
        self.assertEqual(arlo.cfg.auth_host, "https://testhost.com")
        self.assertEqual(arlo.cfg.mqtt_host, "testhost.com")

    def test_host_42(self):
        arlo = tests.arlo.PyArlo(host="http://testhost.com", auth_host="http://testhost.com", mqtt_host="http://testhost.com")
        self.assertEqual(arlo.cfg.host, "http://testhost.com")
        self.assertEqual(arlo.cfg.auth_host, "http://testhost.com")
        self.assertEqual(arlo.cfg.mqtt_host, "testhost.com")
