#!/usr/bin/env python
#

import sys
import click
import pprint
import logging
import base64
import pickle

from . import PyArlo

logging.basicConfig(level=logging.ERROR)
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

    "compact": False,
    "encrypt": False,
    "public-key": None,
    "private-key": "./rsa.private",
    "pass-phrase": None,
    "verbose": 0,
}


def _debug(args):
    _LOGGER.debug("{}".format(args))

def _vdebug(args):
    if opts["verbose"] > 2:
        _debug(args)

def _info(args):
    _LOGGER.info("{}".format(args))

def _fatal(args):
    sys.exit("FATAL-ERROR:{}".format(args))

def _pprint(msg,obj):
    print("{}\n{}".format(msg,pprint.pformat(obj,indent=1)) )

def _epprint(msg,obj):
    if opts["encrypt"]:
        print("-----BEGIN PYAARLO DATA-----")
        print(encrypt_to_string(obj))
        print("-----END PYAARLO DATA-----")
    else:
        _pprint(msg,obj)


def encrypt_to_string(obj):
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_OAEP

    try:
        # pickle and resize object
        obj = pickle.dumps( obj )
        obj += b' ' * (16 - len(obj) % 16)

        # create nonce and encrypt pickled object with it
        nonce = get_random_bytes(16)
        cipher = AES.new(nonce)
        obj = cipher.encrypt(obj)

        # encrypt nonce with public key
        if opts["public-key"] is None:
            key = RSA.importKey(PUBLIC_KEY)
        else:
            key = open(opts["public-key"], 'r').read()
            key = RSA.importKey(key)
        key = PKCS1_OAEP.new(key)
        nonce = key.encrypt(nonce)

        # create nonce/object dictionary, pickle and base64 encode
        nonce_obj = pickle.dumps( { "n":nonce, "o":obj } )
        return base64.encodebytes( nonce_obj ).decode().rstrip()
    except ValueError as err:
        _fatal("encrypt error {}".format(err))
    except:
        _fatal("unexpected encrypt error:", sys.exc_info()[0])


def decrypt_from_string(nonce_obj):
    from Crypto.Cipher import AES
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_OAEP

    try:
        # decode nonce/object dictionary then unpickle it
        nonce_obj = base64.b64decode(nonce_obj)
        nonce_obj = pickle.loads( nonce_obj )

        # import private key and decrypt nonce
        key = open(opts["private-key"], "r").read()
        rsakey = RSA.importKey(key,passphrase=opts["pass-phrase"])
        rsakey = PKCS1_OAEP.new(rsakey)
        nonce = rsakey.decrypt(nonce_obj["n"])

        # decrypt object and unpickle
        cipher = AES.new(nonce)
        obj = cipher.decrypt(nonce_obj["o"])
        obj = pickle.loads(obj)
        return obj
    except ValueError as err:
        _fatal("decrypt error {}".format(err))
    except:
        _fatal("unexpected decrypt error:", sys.exc_info()[0])


def login():
    _info("logging in")
    if opts["username"] is None or opts["password"] is None:
        _fatal("please supply a username and password")
    ar = PyArlo( username=opts["username"], password=opts["password"],
                    storage_dir=opts["storage-dir"], save_state=opts['save-state'], dump=opts['dump-packets'] )
    if ar is None:
        _fatal("unable to login to Arlo")
    return ar


def print_item(name,item):
    if opts["compact"]:
        print( " {};did={};mid={}/{};sno={}".format(item.name,item.device_id,item.model_id,item.hw_version,item.serial_number))
    else:
        print( " {}".format(item.name))
        print( "  device-id:{}".format(item.device_id))
        print( "  model-id:{}/{}".format(item.model_id,item.hw_version))
        print( "  serial-number:{}".format(item.serial_number))

def list_items(name,items):
    print("{}:".format(name))
    if items is not None:
        for item in items:
            print_item(name,item)


# list [all|cameras|bases]
# describe device
# capture [encrpyted|to-file|wait]
#   all devices logs events
# encrypt [from-file|to-file]
#   encrypt 
# decrypt [from-file|to-file]
#   decrypt 

@click.group()
@click.option('-u','--username',required=False,
              help="Arlo username")
@click.option('-p','--password',required=False,
              help="Arlo password")
@click.option('-c','--compact/--no-compact',default=False,
              help="Minimize lists")
@click.option('-e','--encrypt/--no-encrypt',default=False,
              help="Where possible, encrypt output")
@click.option('-k','--public-key',required=False,
              help="Public key for encryption")
@click.option('-K','--private-key',required=False,
              help="Private key for decryption")
@click.option('-P','--pass-phrase',required=False,
              help="Pass phrase for private key")
@click.option('-s','--storage-dir',
              default="./", show_default='current dir',
              help="Where to store Arlo state and packet dump")
@click.option("-v", "--verbose", count=True,
              help="Be chatty. More is more chatty!")
def cli( username,password,compact,encrypt,public_key,private_key,pass_phrase,storage_dir,verbose ):
    if username is not None:
        opts['username'] = username
    if password is not None:
        opts['password'] = password
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
    if verbose is not None:
        opts["verbose"] = verbose
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

    _epprint(item,out)


@cli.command()
@click.argument('item', type=click.Choice(['all', 'cameras', 'bases', 'lights', 'doorbells'], case_sensitive=False))
def list(item):

    ar = login()

    if item == "all" or item == "bases":
        list_items("bases",ar.base_stations)
    if item == "all" or item == "cameras":
        list_items("cameras",ar.cameras)
    if item == "all" or item == "lights":
        list_items("lights",ar.lights)
    if item == "all" or item == "doorbells":
        list_items("doorbells",ar.doorbells)


@cli.command()
def encrypt():
    in_text = sys.stdin.read()
    enc_text = encrypt_to_string(in_text).rstrip()
    print("{}\n{}\n{}".format(BEGIN_PYAARLO_DUMP,enc_text,END_PYAARLO_DUMP))

@cli.command()
def decrypt():
    in_text = sys.stdin.read()
    dec_text = decrypt_from_string(in_text)
    print("{}".format(dec_text))


@cli.command()
def test():
    print("**encrypting")
    ins = {"testing123":"this is a quick test" }
    pprint.pprint(ins)
    msg = encrypt_to_string( ins )
    print("msg\n{}".format(msg))
    print("**decrypting")
    out = decrypt_from_string(msg)
    pprint.pprint(out)

def main_func():
    cli()

if __name__ == '__main__':
    cli()
