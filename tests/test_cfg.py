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

def test_extra_device_states(log):
    cfg1 = ArloCfg(log=log)
    assert cfg1.extra_device_states == []

    cfg2 = ArloCfg(log=log, extra_device_states="deactivated")
    assert cfg2.extra_device_states == ["deactivated"]

    cfg3 = ArloCfg(log=log, extra_device_states=["Deactivated", "OFFLINE"])
    assert cfg3.extra_device_states == ["deactivated", "offline"]


def test_mqtt_config(log):
    cfg = ArloCfg(log=log, mqtt_host="my-custom-host.com", mqtt_port=8883)
    assert cfg.mqtt_host == "my-custom-host.com"
    assert cfg.mqtt_port == 8883
    assert cfg.mqtt_transport == "websockets"


def test_update_mqtt_from_url(log):
    cfg = ArloCfg(log=log)
    assert cfg.event_backend == "auto"
    cfg.update_mqtt_from_url("wss://mqtt-cluster-v2-z2-1.arloxcld.com:8084")
    assert cfg.event_backend == "mqtt"
    assert cfg.mqtt_host == "mqtt-cluster-v2-z2-1.arloxcld.com"
    assert cfg.mqtt_port == 8084
    assert cfg.mqtt_transport == "websockets"


def test_update_mqtt_from_url_default_port(log):
    cfg = ArloCfg(log=log)
    cfg.update_mqtt_from_url("wss://mqtt-cluster-v2-z2-1.arloxcld.com")
    assert cfg.mqtt_port == 443


def test_inline_mode_and_deprecation(log):
    # Default is False
    cfg_default = ArloCfg(log=log)
    assert cfg_default.inline_mode is False
    assert cfg_default.synchronous_mode is False

    # New inline_mode kwarg
    cfg_inline = ArloCfg(log=log, inline_mode=True)
    assert cfg_inline.inline_mode is True
    assert cfg_inline.synchronous_mode is True

    # Legacy synchronous_mode kwarg
    cfg_legacy = ArloCfg(log=log, synchronous_mode=True)
    assert cfg_legacy.inline_mode is True
    assert cfg_legacy.synchronous_mode is True


def test_start_background_config(log):
    # Default is True
    cfg_default = ArloCfg(log=log)
    assert cfg_default.start_background is True

    # Disabled
    cfg_no_bg = ArloCfg(log=log, start_background=False)
    assert cfg_no_bg.start_background is False


def test_update_mqtt_from_url_overrides_legacy_defaults(log):
    from pyaarlo.constant import MQTT_HOST
    cfg = ArloCfg(log=log, mqtt_host=MQTT_HOST, mqtt_transport="tcp")
    assert cfg.mqtt_host == MQTT_HOST
    assert cfg.mqtt_transport == "tcp"
    cfg.update_mqtt_from_url("wss://mqtt-cluster-v2-z2-1.arloxcld.com:8084")
    assert cfg.mqtt_host == "mqtt-cluster-v2-z2-1.arloxcld.com"
    assert cfg.mqtt_port == 8084
    assert cfg.mqtt_transport == "websockets"

