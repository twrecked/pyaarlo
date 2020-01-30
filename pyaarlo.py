#!/usr/bin/env python
#

import sys
import click
import pprint
import logging
import base64

from pyaarlo import PyArlo

logging.basicConfig(level=logging.ERROR)
_LOGGER = logging.getLogger('pyaarlo')


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
    "verbose": 0,
}


def _vpprint(obj):
    if opts["verbose"] > 2:
        _LOGGER.debug("\n" + pprint.pformat(obj,indent=1))

def _pprint(obj):
    _LOGGER.debug("\n" + pprint.pformat(obj,indent=1))

def _vverbose(args):
    if opts["verbose"] > 2:
        _LOGGER.debug("{}".format(args))

def _verbose(args):
    _LOGGER.debug("{}".format(args))

def _info(args):
    _LOGGER.info("{}".format(args))

def _exit(args):
    sys.exit("ERROR:{}".format(args))


def encrypt_RSA(message):
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_OAEP
    rsakey = RSA.importKey(PUBLIC_KEY)
    rsakey = PKCS1_OAEP.new(rsakey)
    encrypted = rsakey.encrypt(message)
    return base64.encodebytes(encrypted)

def decrypt_RSA(private_key_loc, encrypted):
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_OAEP
    encrypted = base64.b64decode(encrypted)
    key = open(private_key_loc, "r").read()
    rsakey = RSA.importKey(key)
    rsakey = PKCS1_OAEP.new(rsakey)
    message = rsakey.decrypt(encrypted)
    return message

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


@click.group()
@click.option('-u','--username',required=True,
              help="Arlo username")
@click.option('-p','--password',required=True,
              help="Arlo password")
@click.option('--compact/--no-compact',default=False,
              help="Minimize lists")
@click.option('-s','--storage-dir',
              default="./", show_default='current dir',
              help="Where to store Arlo state and packet dump")
@click.option("-v", "--verbose", count=True,
              help="Be chatty. More is more chatty!")
def cli( username,password,compact,storage_dir,verbose ):
    opts['username'] = username
    opts['password'] = password
    if compact is not None:
        opts['compact'] = compact
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
@click.argument('item', default='raw',
                type=click.Choice(['raw', 'all', 'cameras', 'bases', 'lights', 'doorbells'], case_sensitive=False))
def dump(item):

    ar = login()

    out = ""
    if item == 'raw':
        out = pprint.pformat( ar._devices )

    print( encrypt_RSA(out.encode()))


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


if __name__ == '__main__':
    cli()
