from unittest.mock import patch
from click.testing import CliRunner

from pyaarlo.cli.diagnostics import (
    DebugReportCapture,
    anonymize_text,
    decrypt_from_string,
    encrypt_to_string,
)
from pyaarlo.cli.main_cmd import cli as pyaarlo_cli


def test_anonymize_text_privacy():
    raw_log = "User test@arlo.com password secretpass device 4N71687207851 owner USR999"
    devices = [{"deviceId": "4N71687207851", "owner": {"ownerId": "USR999"}}]

    anon = anonymize_text(
        raw_log,
        devices=devices,
        username="test@arlo.com",
        password="secretpass",
    )

    assert "test@arlo.com" not in anon
    assert "secretpass" not in anon
    assert "4N71687207851" not in anon
    assert "USR999" not in anon
    assert "USERNAME" in anon
    assert "PASSWORD" in anon
    assert "DEV_01_ID" in anon
    assert "OWNER_01_ID" in anon


def test_debug_report_capture_lifecycle(tmp_path):
    report_file = tmp_path / "debug.enc"
    capture = DebugReportCapture(filename=str(report_file))

    capture.start(username="myuser@example.com", password="mypassword")

    import logging
    log = logging.getLogger("pyaarlo")
    log.debug("Step 1: connecting to test endpoint")
    log.info("Step 2: connected successfully")

    out_path = capture.finish(output_filename=str(report_file))
    assert out_path is not None
    assert report_file.is_file()

    content = report_file.read_text(encoding="utf-8")
    assert "-----BEGIN PYAARLO DUMP-----" in content
    assert "-----END PYAARLO DUMP-----" in content


def test_debug_report_with_exception(tmp_path):
    report_file = tmp_path / "crash_debug.enc"
    capture = DebugReportCapture(filename=str(report_file))
    capture.start()

    try:
        raise RuntimeError("simulated Arlo cloud failure")
    except RuntimeError as e:
        capture.finish(output_filename=str(report_file), exception=e)

    assert report_file.is_file()
    content = report_file.read_text(encoding="utf-8")
    assert "-----BEGIN PYAARLO DUMP-----" in content


def test_pyaarlo_cli_debug_report_flag(tmp_path):
    runner = CliRunner()
    report_file = tmp_path / "cli_report.enc"

    result = runner.invoke(pyaarlo_cli, ["--debug-report", str(report_file), "login", "--status"])
    assert report_file.is_file()
    assert "PyArlo Debug Report Generated" in result.output


def test_encrypt_decrypt_v2_json_roundtrip(tmp_path):
    import json
    import base64
    from Crypto.PublicKey import RSA

    key = RSA.generate(2048)
    priv_file = tmp_path / "rsa.private"
    pub_file = tmp_path / "rsa.public"
    priv_file.write_text(key.export_key().decode("ascii"))
    pub_file.write_text(key.publickey().export_key().decode("ascii"))

    # Test string round-trip
    secret_text = "diagnostics: error at line 42 with token ABC"
    enc = encrypt_to_string(secret_text, public_key_file=str(pub_file))

    # Verify envelope is v2 JSON
    envelope = json.loads(base64.b64decode(enc).decode("utf-8"))
    assert envelope["v"] == 2
    assert all(k in envelope for k in ("k", "n", "o", "t"))

    # Decrypt and verify
    decrypted = decrypt_from_string(enc, private_key_file=str(priv_file))
    assert decrypted == secret_text

    # Test dict round-trip
    secret_dict = {"status": "ok", "devices": [1, 2, 3]}
    enc_dict = encrypt_to_string(secret_dict, public_key_file=str(pub_file))
    dec_dict = decrypt_from_string(enc_dict, private_key_file=str(priv_file))
    assert dec_dict == secret_dict


def test_decrypt_legacy_v1_pickle_backwards_compatible(tmp_path):
    import pickle
    import base64
    from Crypto.Cipher import AES, PKCS1_OAEP
    from Crypto.PublicKey import RSA
    from Crypto.Random import get_random_bytes

    key = RSA.generate(2048)
    priv_file = tmp_path / "rsa.private"
    priv_file.write_text(key.export_key().decode("ascii"))

    # Construct legacy v1 envelope using pickle
    msg = "legacy pickled secret payload"
    pickled_obj = pickle.dumps(msg)
    aes_key = get_random_bytes(16)
    cipher = AES.new(aes_key, AES.MODE_EAX)
    ciphertext, tag = cipher.encrypt_and_digest(pickled_obj)

    rsa_cipher = PKCS1_OAEP.new(key.publickey())
    enc_key = rsa_cipher.encrypt(aes_key)

    v1_envelope = pickle.dumps({"k": enc_key, "n": cipher.nonce, "o": ciphertext, "t": tag})
    v1_b64 = base64.encodebytes(v1_envelope).decode().rstrip()

    # Ensure decrypt_from_string still decrypts legacy v1 pickle
    decrypted = decrypt_from_string(v1_b64, private_key_file=str(priv_file))
    assert decrypted == msg

