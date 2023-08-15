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
        self.assertEqual(arlo.cfg.tfa_host_with_scheme(), "https://pyaarlo-tfa.appspot.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme("roygbiv"), "https://pyaarlo-tfa.appspot.com")
        self.assertEqual(arlo.cfg.tfa_port, 993)

    def test_host_10(self):
        arlo = tests.arlo.PyArlo(tfa_host="test.host.com")
        self.assertEqual(arlo.cfg.tfa_host, "test.host.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme(), "https://test.host.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme("imap"), "imap://test.host.com")
        self.assertEqual(arlo.cfg.tfa_port, 993)

    def test_host_11(self):
        arlo = tests.arlo.PyArlo(tfa_host="test.host.com:998")
        self.assertEqual(arlo.cfg.tfa_host, "test.host.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme(), "https://test.host.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme("imap"), "imap://test.host.com")
        self.assertEqual(arlo.cfg.tfa_port, 998)

    def test_host_20(self):
        arlo = tests.arlo.PyArlo(tfa_host="imap://test.host.com")
        self.assertEqual(arlo.cfg.tfa_host, "test.host.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme(), "imap://test.host.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme("roygbiv"), "imap://test.host.com")
        self.assertEqual(arlo.cfg.tfa_port, 993)

    def test_host_21(self):
        arlo = tests.arlo.PyArlo(tfa_host="imap://test.host.com:998")
        self.assertEqual(arlo.cfg.tfa_host, "test.host.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme(), "imap://test.host.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme("imap"), "imap://test.host.com")
        self.assertEqual(arlo.cfg.tfa_port, 998)

    def test_host_30(self):
        arlo = tests.arlo.PyArlo(tfa_host="https://test.host.com")
        self.assertEqual(arlo.cfg.tfa_host, "test.host.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme(), "https://test.host.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme("roygbiv"), "https://test.host.com")
        self.assertEqual(arlo.cfg.tfa_port, 993)

    def test_host_31(self):
        arlo = tests.arlo.PyArlo(tfa_host="https://test.host.com:998")
        self.assertEqual(arlo.cfg.tfa_host, "test.host.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme(), "https://test.host.com")
        self.assertEqual(arlo.cfg.tfa_host_with_scheme("roygbiv"), "https://test.host.com")
        self.assertEqual(arlo.cfg.tfa_port, 998)

    def test_host_40(self):
        arlo = tests.arlo.PyArlo(host="https://test.host.com", auth_host="https://test.host.com", mqtt_host="https://test.host.com")
        self.assertEqual(arlo.cfg.host, "https://test.host.com")
        self.assertEqual(arlo.cfg.auth_host, "https://test.host.com")
        self.assertEqual(arlo.cfg.mqtt_host, "test.host.com")

    def test_host_41(self):
        arlo = tests.arlo.PyArlo(host="test.host.com", auth_host="test.host.com", mqtt_host="test.host.com")
        self.assertEqual(arlo.cfg.host, "https://test.host.com")
        self.assertEqual(arlo.cfg.auth_host, "https://test.host.com")
        self.assertEqual(arlo.cfg.mqtt_host, "test.host.com")

    def test_host_42(self):
        arlo = tests.arlo.PyArlo(host="http://test.host.com", auth_host="http://test.host.com", mqtt_host="http://test.host.com")
        self.assertEqual(arlo.cfg.host, "http://test.host.com")
        self.assertEqual(arlo.cfg.auth_host, "http://test.host.com")
        self.assertEqual(arlo.cfg.mqtt_host, "test.host.com")
