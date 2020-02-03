#!/usr/bin/env python
#

import sys
import click
import pprint
import logging
import base64
import pickle

from pyaarlo import PyArlo

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

    "compact": False,
    "encrypt": False,
    "verbose": 0,
}

def encrypt_to_string(obj):
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_OAEP

    # pickle and resize object
    obj = pickle.dumps( obj )
    obj += b' ' * (16 - len(obj) % 16)

    # create nonce and encrypt pickled object with it
    nonce = get_random_bytes(16)
    cipher = AES.new(nonce)
    obj = cipher.encrypt(obj)

    # encrypt nonce with public key
    key = RSA.importKey(PUBLIC_KEY)
    key = PKCS1_OAEP.new(key)
    nonce = key.encrypt(nonce)

    # create nonce/object dictionary, pickle and base64 encode
    nonce_obj = pickle.dumps( { "n":nonce, "o":obj } )
    return base64.encodebytes( nonce_obj ).decode().rstrip()


def decrypt_from_string(private_key_loc, nonce_obj):
    from Crypto.Cipher import AES
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_OAEP

    # decode nonce/object dictionary then unpickle it
    nonce_obj = base64.b64decode(nonce_obj)
    nonce_obj = pickle.loads( nonce_obj )

    # import private key and decrypt nonce
    key = open(private_key_loc, "r").read()
    rsakey = RSA.importKey(key)
    rsakey = PKCS1_OAEP.new(rsakey)
    nonce = rsakey.decrypt(nonce_obj["n"])

    # decrypt object and unpickle
    cipher = AES.new(nonce)
    obj = cipher.decrypt(nonce_obj["o"])
    obj = pickle.loads(obj)
    return obj


def _debug(args):
    _LOGGER.debug("{}".format(args))

def _vdebug(args):
    if opts["verbose"] > 2:
        _debug(args)

def _info(args):
    _LOGGER.info("{}".format(args))

def _exit(args):
    sys.exit("ERROR:{}".format(args))


def _pprint(msg,obj):
    print("{}\n{}".format(msg,pprint.pformat(obj,indent=1)) )

def _epprint(msg,obj):
    if opts["encrypt"]:
        print("-----BEGIN PYAARLO DATA-----")
        print(encrypt_to_string(obj))
        print("-----END PYAARLO DATA-----")
    else:
        _pprint(msg,obj)


def login():
    _info("logging in")
    ar = PyArlo( username=opts["username"], password=opts["password"], storage_dir=opts["storage-dir"], dump=True )
    if ar is None:
        _exit("unable to login to Arlo")
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
@click.option('-u','--username',required=True,
              help="Arlo username")
@click.option('-p','--password',required=True,
              help="Arlo password")
@click.option('-c','--compact/--no-compact',default=False,
              help="Minimize lists")
@click.option('-e','--encrypt/--no-encrypt',default=False,
              help="Where possible, encrypt output")
@click.option('-s','--storage-dir',
              default="./", show_default='current dir',
              help="Where to store Arlo state and packet dump")
@click.option("-v", "--verbose", count=True,
              help="Be chatty. More is more chatty!")
def cli( username,password,compact,encrypt,storage_dir,verbose ):
    opts['username'] = username
    opts['password'] = password
    if compact is not None:
        opts['compact'] = compact
    if encrypt is not None:
        opts['encrypt'] = encrypt
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
def test():
    print("**encrypting")
    ins = {"testing123":"this is a quick test" }
    pprint.pprint(ins)
    msg = encrypt_to_string( ins )
    print("msg\n{}".format(msg))
    print("**decrypting")
    out = decrypt_from_string("./rsa.private",msg)
    pprint.pprint(out)


if __name__ == '__main__':
    cli()
