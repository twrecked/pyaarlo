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


def test_tfa_single_property_config(log):
    # Push
    cfg_push = ArloCfg(log=log, tfa="push")
    assert cfg_push.tfa == "push"
    assert cfg_push.tfa_type == "push"
    assert cfg_push.tfa_source == "push"

    # Email IMAP
    cfg_imap = ArloCfg(log=log, tfa="email:imap")
    assert cfg_imap.tfa == "email:imap"
    assert cfg_imap.tfa_type == "email"
    assert cfg_imap.tfa_source == "imap"

    # SMS
    cfg_sms = ArloCfg(log=log, tfa="sms")
    assert cfg_sms.tfa == "sms"
    assert cfg_sms.tfa_type == "sms"
    assert cfg_sms.tfa_source == "console"

    # Legacy fallback: tfa_type + tfa_source kwargs
    cfg_legacy = ArloCfg(log=log, tfa_type="email", tfa_source="imap")
    assert cfg_legacy.tfa == "email:imap"
    assert cfg_legacy.tfa_type == "email"
    assert cfg_legacy.tfa_source == "imap"


def test_arlo_logger_packet_sublogger(caplog):
    import logging
    from pyaarlo.core.logger import ArloLogger

    packet_logger = logging.getLogger("pyaarlo.packet")

    # By default, packet logger is not DEBUG
    packet_logger.setLevel(logging.INFO)
    logger = ArloLogger(verbose=False)
    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        logger.vdebug("packet_test_hidden")
        assert "packet_test_hidden" not in caplog.text

    # When pyaarlo.packet is set to DEBUG
    packet_logger.setLevel(logging.DEBUG)
    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        logger.vdebug("packet_test_visible")
        assert "packet_test_visible" in caplog.text

    # When verbose=True is passed
    logger_verbose = ArloLogger(verbose=True)
    assert packet_logger.level == logging.DEBUG


def test_cfg_numeric_and_boolean_coercion(log):
    cfg = ArloCfg(
        log=log,
        recent_time="45",
        max_days="180",
        db_motion_time="15",
        db_ding_time="5",
        request_timeout="30",
        stream_timeout="10",
        refresh_devices_every="2",
        refresh_modes_every="5",
        snapshot_timeout="50",
        tfa_delay="2",
        tfa_retries="5",
        tfa_timeout="4",
        tfa_total_timeout="120",
        dump="true",
        no_media_upload="1",
        refresh_devices="yes",
        wait_for_initial_setup="false",
        save_state="0",
    )
    assert cfg.recent_time == 45
    assert cfg.max_days == 180
    assert cfg.db_motion_time == 15
    assert cfg.db_ding_time == 5
    assert cfg.request_timeout == 30
    assert cfg.stream_timeout == 10
    assert cfg.refresh_devices_every == 2 * 60 * 60
    assert cfg.refresh_modes_every == 5 * 60
    assert cfg.snapshot_timeout == 50
    assert cfg.tfa_delay == 2
    assert cfg.tfa_retries == 5
    assert cfg.tfa_timeout == 4
    assert cfg.tfa_total_timeout == 120
    assert cfg.dump is True
    assert cfg.no_media_upload is True
    assert cfg.refresh_devices is True
    assert cfg.wait_for_initial_setup is False
    assert cfg.save_state is False


@pytest.mark.asyncio
async def test_task_manager_string_delay_coercion(log):
    import asyncio
    from unittest.mock import MagicMock
    from pyaarlo.core.task_manager import ArloTaskManager

    tm = ArloTaskManager(log)
    cb = MagicMock()
    tm.run_in(cb, "0.01")
    await asyncio.sleep(0.05)
    assert cb.called
    tm.stop()


