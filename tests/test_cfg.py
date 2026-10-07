import pytest
from pyaarlo import (
    ArloCfg,
    ArloLogger,
)

@pytest.fixture
def log():
    return ArloLogger()

def test_scheme(log):
    cfg = ArloCfg(log=log)
    assert cfg._remove_scheme("abc.com") == "abc.com"
    assert cfg._remove_scheme("https://abc.com") == "abc.com"
    assert cfg._add_scheme("abc.com") == "https://abc.com"
    assert cfg._add_scheme("https://abc.com") == "https://abc.com"
    assert cfg._add_scheme("http://abc.com") == "http://abc.com"
    assert cfg._add_scheme("abc.com", "imap") == "imap://abc.com"
    assert cfg._add_scheme("https://abc.com", "imap") == "https://abc.com"

def test_host_00(log):
    cfg = ArloCfg(log=log)
    assert cfg.tfa_host == "pyaarlo-tfa.appspot.com"
    assert cfg.tfa_host_with_scheme() == "https://pyaarlo-tfa.appspot.com"
    assert cfg.tfa_host_with_scheme("roygbiv") == "https://pyaarlo-tfa.appspot.com"
    assert cfg.tfa_port == 993

def test_host_10(log):
    cfg = ArloCfg(log=log, tfa_host="test.host.com")
    assert cfg.tfa_host == "test.host.com"
    assert cfg.tfa_host_with_scheme() == "https://test.host.com"
    assert cfg.tfa_host_with_scheme("imap") == "imap://test.host.com"
    assert cfg.tfa_port == 993

def test_host_11(log):
    cfg = ArloCfg(log=log, tfa_host="test.host.com:998")
    assert cfg.tfa_host == "test.host.com"
    assert cfg.tfa_host_with_scheme() == "https://test.host.com"
    assert cfg.tfa_host_with_scheme("imap") == "imap://test.host.com"
    assert cfg.tfa_port == 998

def test_host_20(log):
    cfg = ArloCfg(log=log, tfa_host="imap://test.host.com")
    assert cfg.tfa_host == "test.host.com"
    assert cfg.tfa_host_with_scheme() == "imap://test.host.com"
    assert cfg.tfa_host_with_scheme("roygbiv") == "imap://test.host.com"
    assert cfg.tfa_port == 993

def test_host_21(log):
    cfg = ArloCfg(log=log, tfa_host="imap://test.host.com:998")
    assert cfg.tfa_host == "test.host.com"
    assert cfg.tfa_host_with_scheme() == "imap://test.host.com"
    assert cfg.tfa_host_with_scheme("imap") == "imap://test.host.com"
    assert cfg.tfa_port == 998

def test_host_30(log):
    cfg = ArloCfg(log=log, tfa_host="https://test.host.com")
    assert cfg.tfa_host == "test.host.com"
    assert cfg.tfa_host_with_scheme() == "https://test.host.com"
    assert cfg.tfa_host_with_scheme("roygbiv") == "https://test.host.com"
    assert cfg.tfa_port == 993

def test_host_31(log):
    cfg = ArloCfg(log=log, tfa_host="https://test.host.com:998")
    assert cfg.tfa_host == "test.host.com"
    assert cfg.tfa_host_with_scheme() == "https://test.host.com"
    assert cfg.tfa_host_with_scheme("roygbiv") == "https://test.host.com"
    assert cfg.tfa_port == 998

def test_host_40(log):
    cfg = ArloCfg(log=log, host="https://test.host.com", auth_host="https://test.host.com", mqtt_host="https://test.host.com")
    assert cfg.host == "https://test.host.com"
    assert cfg.auth_host == "https://test.host.com"
    assert cfg.mqtt_host == "test.host.com"

def test_host_41(log):
    cfg = ArloCfg(log=log, host="test.host.com", auth_host="test.host.com", mqtt_host="test.host.com")
    assert cfg.host == "https://test.host.com"
    assert cfg.auth_host == "https://test.host.com"
    assert cfg.mqtt_host == "test.host.com"

def test_host_42(log):
    cfg = ArloCfg(log=log, host="http://test.host.com", auth_host="http://test.host.com", mqtt_host="http://test.host.com")
    assert cfg.host == "http://test.host.com"
    assert cfg.auth_host == "http://test.host.com"
    assert cfg.mqtt_host == "test.host.com"
