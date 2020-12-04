#!/usr/bin/env python
#

import base64
import io
import logging
import os
import pickle
import pprint
import sys

import click

from . import PyArlo
from .util import to_b64

logging.basicConfig(level=logging.ERROR,
                    format='%(asctime)s:%(name)s:%(levelname)s: %(message)s')
_LOGGER = logging.getLogger('pyaarlo')

BEGIN_PYAARLO_DUMP = "-----BEGIN PYAARLO DUMP-----"
END_PYAARLO_DUMP = "-----END PYAARLO DUMP-----"

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1oYXnbQPxREiVPUIRkgk
h+ehjxHnwz34NsjhjgN1oSKmHpf4cL4L/V4tMnj5NELEmLyTrzAZbeewUMwyiwXO
3l+cSjjoDKcPBSj4uxjWsq74Q5TLHGjOtkFwaqqxtvsVn3fGFWBO405xpvp7jPUc
BOvBQaUBUaR9Tbw5anMOzeavUwUTRp2rjtbWyj2P7PEp49Ixzw0w+RjIVrzzevAo
AD7SVb6U8P77fht4k9krbIFckC/ByY48HhmF+edh1GZAgLCHuf43tGg2upuH5wf+
AGv/Xlc+9ScTjEp37uPiCpHcB1ur83AFTjcceDIm+VDKF4zQrj88zmL7JqZy+Upx
UQIDAQAB
-----END PUBLIC KEY-----"""

opts = {
    "username": None,
    "password": None,

    "storage-dir": "./",
    "save-state": False,
    "dump-packets": False,
    "wait-for-initial-setup": True,

    "anonymize": False,
    "compact": False,
    "encrypt": False,
    "public-key": None,
    "private-key": "./rsa.private",
    "pass-phrase": None,
    "verbose": 0,
}

# where we store before encrypting or anonymizing
_out = None

# Arlo instance...
_arlo = None


def _debug(args):
    _LOGGER.debug("{}".format(args))


def _vdebug(args):
    if opts["verbose"] > 2:
        _debug(args)


def _info(args):
    _LOGGER.info("{}".format(args))


def _fatal(args):
    sys.exit("FATAL-ERROR:{}".format(args))


def _print_start():
    if opts['anonymize'] or opts['encrypt']:
        global _out
        _out = io.StringIO()


def _print(msg):
    if _out is None:
        print("{}".format(msg))
    else:
        _out.write(msg)
        _out.write("\n")


def _pprint(msg, obj):
    _print("{}\n{}".format(msg, pprint.pformat(obj, indent=1)))


def _print_end():
    if _out is not None:
        _out.seek(0, 0)
        out_text = _out.read()

        if opts['anonymize']:
            out_text = anonymize_from_string(out_text)
        if opts['encrypt']:
            print(BEGIN_PYAARLO_DUMP)
            out_text = encrypt_to_string(out_text)
        print(out_text)
        if opts['encrypt']:
            print(END_PYAARLO_DUMP)


def _casecmp(s1, s2):
    if s1 is None or s2 is None:
        return False
    return str(s1).lower() == str(s2).lower()


def encrypt_to_string(obj):
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_OAEP

    try:
        # pickle and resize object
        obj = pickle.dumps(obj)
        obj += b' ' * (16 - len(obj) % 16)

        # create key and encrypt pickled object with it
        key = get_random_bytes(16)
        aes_cipher = AES.new(key, AES.MODE_EAX)
        obj, tag = aes_cipher.encrypt_and_digest(obj)
        nonce = aes_cipher.nonce

        # encrypt key with public key
        if opts["public-key"] is None:
            rsa_cipher = RSA.importKey(PUBLIC_KEY)
        else:
            rsa_cipher = open(opts["public-key"], 'r').read()
            rsa_cipher = RSA.importKey(rsa_cipher)
        rsa_cipher = PKCS1_OAEP.new(rsa_cipher)
        key = rsa_cipher.encrypt(key)

        # create key/object dictionary, pickle and base64 encode
        key_obj = pickle.dumps({'k': key, 'n': nonce, 'o': obj, 't': tag})
        return base64.encodebytes(key_obj).decode().rstrip()
    except ValueError as err:
        _fatal("encrypt error: {}".format(err))
    except Exception:
        _fatal("unexpected encrypt error: {}".format(sys.exc_info()[0]))


def decrypt_from_string(key_obj):
    from Crypto.Cipher import AES
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_OAEP

    try:
        # decode key/object dictionary then unpickle it
        key_obj = base64.b64decode(key_obj)
        key_obj = pickle.loads(key_obj)

        # import private key and decrypt nonce
        key = open(opts["private-key"], "r").read()
        rsa_cipher = RSA.importKey(key, passphrase=opts["pass-phrase"])
        rsa_cipher = PKCS1_OAEP.new(rsa_cipher)
        key = rsa_cipher.decrypt(key_obj["k"])

        # decrypt object and unpickle
        aes_cipher = AES.new(key, AES.MODE_EAX, nonce=key_obj['n'])
        obj = aes_cipher.decrypt_and_verify(key_obj['o'], key_obj['t'])
        obj = pickle.loads(obj)
        return obj
    except ValueError as err:
        _fatal("decrypt error {}".format(err))
    except Exception:
        _fatal("unexpected decrypt error: {}".format(sys.exc_info()[0]))


def anonymize_from_string(obj):
    # get device list
    keys = ['deviceId', 'uniqueId', 'userId', 'xCloudId']
    valuables = {}
    for device in _arlo._devices:
        for key in keys:
            value = device.get(key, None)
            if value and value not in valuables:
                valuables[value] = "X" * len(value)
        owner_id = device.get('owner', {}).get('ownerId', None)
        if owner_id:
            valuables[owner_id] = "X" * len(owner_id)
    if opts["username"] is not None:
        valuables[opts["username"]] = "USERNAME"
    if opts["password"] is not None:
        valuables[to_b64(opts["password"])] = "PASSWORD"

    anon = obj
    for valuable in valuables:
        anon = anon.replace(valuable, valuables[valuable])
    return anon


def login():
    _info("logging in")
    if opts["username"] is None or opts["password"] is None:
        _fatal("please supply a username and password")
    global _arlo
    _arlo = PyArlo(username=opts["username"], password=opts["password"],
                   storage_dir=opts["storage-dir"],
                   save_state=opts['save-state'],
                   wait_for_initial_setup=opts['wait-for-initial-setup'],
                   dump=opts['dump-packets']
                   )
    if _arlo is None:
        _fatal("unable to login to Arlo")
    return _arlo


def print_item(_name, item):
    if opts["compact"]:
        _print(" {};did={};mid={}/{};sno={}".format(item.name, item.device_id, item.model_id, item.hw_version,
                                                    item.serial_number))
    else:
        _print(" {}".format(item.name))
        _print("  device-id:{}".format(item.device_id))
        _print("  model-id:{}/{}".format(item.model_id, item.hw_version))
        _print("  serial-number:{}".format(item.serial_number))


def list_items(name, items):
    _print("{}:".format(name))
    if items is not None:
        for item in items:
            print_item(name, item)


# list [all|cameras|bases]
# describe device
# capture [encrpyted|to-file|wait]
#   all devices logs events
# encrypt [from-file|to-file]
#   encrypt 
# decrypt [from-file|to-file]
#   decrypt 

@click.group()
@click.option('-u', '--username', required=False,
              help="Arlo username")
@click.option('-p', '--password', required=False,
              help="Arlo password")
@click.option('-a', '--anonymize/--no-anonymize', default=False,
              help="Anonimize ids")
@click.option('-c', '--compact/--no-compact', default=False,
              help="Minimize lists")
@click.option('-e', '--encrypt/--no-encrypt', default=False,
              help="Where possible, encrypt output")
@click.option('-k', '--public-key', required=False,
              help="Public key for encryption")
@click.option('-K', '--private-key', required=False,
              help="Private key for decryption")
@click.option('-P', '--pass-phrase', required=False,
              help="Pass phrase for private key")
@click.option('-s', '--storage-dir',
              default="./", show_default='current dir',
              help="Where to store Arlo state and packet dump")
@click.option('-w', '--wait/--no-wait', default=True,
              help="Wait for all information to arrive starting up")
@click.option("-v", "--verbose", count=True,
              help="Be chatty. More is more chatty!")
def cli(username, password, anonymize, compact, encrypt, public_key, private_key, pass_phrase, storage_dir, wait,
        verbose):
    if username is not None:
        opts['username'] = username
    if password is not None:
        opts['password'] = password
    if anonymize is not None:
        opts['anonymize'] = anonymize
    if compact is not None:
        opts['compact'] = compact
    if encrypt is not None:
        opts['encrypt'] = encrypt
    if public_key is not None:
        opts['public-key'] = public_key
    if private_key is not None:
        opts['private-key'] = private_key
    if pass_phrase is not None:
        opts['pass-phrase'] = pass_phrase
    if storage_dir is not None:
        opts['storage-dir'] = storage_dir
    if wait is not None:
        opts['wait-for-initial-setup'] = wait
    if verbose is not None:
        opts['verbose'] = verbose
        if verbose == 0:
            _LOGGER.setLevel(logging.ERROR)
        if verbose == 1:
            _LOGGER.setLevel(logging.INFO)
        if verbose > 1:
            _LOGGER.setLevel(logging.DEBUG)


@cli.command()
@click.argument('item', default='all',
                type=click.Choice(['all', 'cameras', 'bases', 'lights', 'doorbells'], case_sensitive=False))
def dump(item):
    out = {}
    ar = login()

    if item == 'all':
        out = ar._devices

    _print_start()
    _pprint(item, out)
    _print_end()


@cli.command()
@click.argument('item', type=click.Choice(['all', 'cameras', 'bases', 'lights', 'doorbells'], case_sensitive=False))
def list(item):
    ar = login()
    _print_start()
    if item == "all" or item == "bases":
        list_items("bases", ar.base_stations)
    if item == "all" or item == "cameras":
        list_items("cameras", ar.cameras)
    if item == "all" or item == "lights":
        list_items("lights", ar.lights)
    if item == "all" or item == "doorbells":
        list_items("doorbells", ar.doorbells)
    _print_end()


@cli.command()
def encrypt():
    in_text = sys.stdin.read()
    enc_text = encrypt_to_string(in_text).rstrip()
    print("{}\n{}\n{}".format(BEGIN_PYAARLO_DUMP, enc_text, END_PYAARLO_DUMP))


@cli.command()
def decrypt():
    lines = ""
    save_lines = False
    for line in sys.stdin.readlines():
        if line.startswith(BEGIN_PYAARLO_DUMP):
            save_lines = True
        elif line.startswith(END_PYAARLO_DUMP):
            save_lines = False
        elif save_lines:
            lines += line
    if lines == "":
        _fatal('no encrypted input found')
    else:
        dec_text = decrypt_from_string(lines)
        print("{}".format(dec_text), end='')


@cli.command()
def anonymize():
    login()
    in_text = sys.stdin.read()
    print(anonymize_from_string(in_text))


@cli.command()
@click.option('-n', '--name', required=False,
              help='camera name')
@click.option('-d', '--device-id', required=False,
              help='camera device id')
@click.option('-f', '--start-ffmpeg/--no-start-ffmpeg', required=False, default=False,
              help='start ffmpeg for stream')
@click.argument('action', type=click.Choice(['start-stream', 'stop-stream', 'last-thumbnail'], case_sensitive=False))
def camera(name, device_id, start_ffmpeg, action):
    camera = None
    ar = login()
    for c in ar.cameras:
        if _casecmp(c.name, name) or _casecmp(c.device_id, device_id):
            camera = c
            break
    if camera is None:
        print('cannot find camera')
        return 0

    if action == 'start-stream':
        print('starting a stream')
        stream_url = camera.get_stream()
        if stream_url is None:
            print(' failed to start stream')
            return 0
        print("stream-url={}".format(stream_url))

        if start_ffmpeg:
            print('starting ffmpeg')
            os.system("mkdir video_dir")
            os.system("ffmpeg -i '{}' ".format(stream_url) +
                      "-fflags flush_packets -max_delay 2 -flags -global_header " +
                      "-hls_time 2 -hls_list_size 3 -vcodec copy -y video_dir/video.m3u8")

    elif action == 'stop-stream':
        pass

    elif action == 'last-thumbnail':
        last_thumbnail = camera.last_thumbnail
        if last_thumbnail:
            print("last-thumbnail={}".format(last_thumbnail))
        else:
            print(' error getting thumbnail')


def main_func():
    cli()


if __name__ == '__main__':
    cli()
