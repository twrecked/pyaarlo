#!/usr/bin/env python
#

import sys
import click
import pprint
import logging

from pyaarlo import PyArlo

logging.basicConfig(level=logging.ERROR)
_LOGGER = logging.getLogger('pyaarlo')

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
def dump():
    _info("logging in")
    #ar = PyArlo( username=opts["username"], password=opts["password"], storage_dir=opts["storage-dir"], dump=True )
    #_pprint( ar._devices )
    #_pprint(opts)
    print("** device list")
    #pprint(ar._devices)
    print("")


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
