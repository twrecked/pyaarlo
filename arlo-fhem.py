#!/usr/bin/python3

# arlo-fhem.py / Arlo Daemon for FHEM
# https://github.com/m0urs/arlo-fhem
# Based on https://github.com/twrecked/pyaarlo
# Michael Urspringer

VERSION = "1.0.2"

import pyaarlo
import argparse
import configparser
import datetime
import errno
import logging
import os
import pprint
import socket
import sys
import telnetlib
import time


# Login to Arlo Account, retry if not successfull
def loginToArlo(username, password, tfa_host, tfa_username, tfa_password, max_tries, login_wait):
    count = 0
    arlo = ""
    while count < max_tries:
        count = count + 1 
        print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "- arlo-fhem - Trying to connect ",count," of ",max_tries)
        arlo = pyaarlo.PyArlo(username=username, password=password,tfa_source='imap', tfa_type='email', tfa_host=tfa_host, tfa_username=tfa_username, tfa_password=tfa_password, synchronous_mode=True, refresh_devices_every=3)
        if arlo.is_connected:
            break
        if count == max_tries:
            print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "- arlo-fhem - UNABLE TO CONNECT - aborting")
            sys.exit(-1)
        print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "- arlo-fhem - UNABLE TO CONNECT - retrying after ",login_wait," seconds")
        time.sleep(login_wait)
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "- arlo-fhem - CONNECTED")
    return arlo

# Send a command to FHEM via TELNET
def sendCommandtoFHEM(fhem_host, fhem_port, fhem_password, fhem_command):
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "- arlo-fhem - Send FHEM command: ",fhem_command)
    tn = telnetlib.Telnet(fhem_host,fhem_port)
    tn.read_until(b"Password: ")
    tn.write(fhem_password.encode("ascii") + b"\n")
    tn.write(fhem_command.encode("ascii") + b"\n")
    tn.write(b"quit\n")
    tn.close()

def getDeviceFromName(name, devices):
    for device in devices:
        if device.name == name:
            return(device)
    return("")

print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "- arlo-fhem - version", VERSION)

# set up logging, change ERROR or INFO to DEBUG for a *lot* more information
logging.basicConfig(level=logging.ERROR,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
_LOGGER = logging.getLogger('arlo-fhem')

# Check command line parameters
parser = argparse.ArgumentParser()
parser.add_argument('--configfile', '-c', default='./arlo-fhem.cfg', help='Path to config file, use ./arlo-fhem.cfg if empty')
args = parser.parse_args()

configfile=args.configfile

# Initialize config file
if not os.path.isfile(configfile):
    print("Error: Config file "+configfile+" not found")
    sys.exit(errno.ENOENT)

config = configparser.ConfigParser()
config.read(configfile)

# Credentials for Arlo
USERNAME = config.get("CREDENTIALS", "USERNAME")
PASSWORD = config.get("CREDENTIALS", "PASSWORD")

# Credentials for 2FA via IMAP
IMAPSERVER = config.get("2FA", "IMAPSERVER")
IMAPUSER = config.get("2FA", "IMAPUSER")
IMAPPASSWORD = config.get("2FA", "IMAPPASSWORD")

# Definitions for Communication Socket
TCP_IP = config.get("SOCKET", "TCP_IP")
TCP_PORT = int(config.get("SOCKET", "TCP_PORT"))
BUFFER_SIZE = int(config.get("SOCKET", "BUFFER_SIZE"))

# Misc parameters
MAX_TRIES = int(config.get("MISC", "MAX_TRIES"))
LOGIN_WAIT = int(config.get("MISC", "LOGIN_WAIT"))

# FHEM parameters
FHEM_HOST = config.get("FHEM", "FHEM_HOST")
FHEM_PORT = int(config.get("FHEM", "FHEM_PORT"))
FHEM_PASSWORD = config.get("FHEM", "FHEM_PASSWORD")


# Login to Arlo, use 2FA via IMAP Mail if required
arlo = loginToArlo(USERNAME,PASSWORD,IMAPSERVER,IMAPUSER,IMAPPASSWORD,MAX_TRIES,LOGIN_WAIT)

while True:

    # Open a TCPIP socket for communication with FHEM
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((TCP_IP, TCP_PORT))
    s.listen(1)
    conn, addr = s.accept()
    # print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "- arlo-fhem - Connection address: ",addr)

    while True:

        received_command = conn.recv(BUFFER_SIZE)
        if not received_command: break

        received_command = received_command.decode('utf8').replace("\n", "")
        print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "- arlo-fhem - Received command: ",received_command)

        received_command = received_command.split(" ")
        try:
            command = received_command[0]
        except IndexError:
            command = ""
        try:
            parameter1 = received_command[1]
        except IndexError:
            parameter1 = ""
        try:
            parameter2 = received_command[2]
        except IndexError:
            parameter2 = ""
        
        if command == 'list-cameras':
            # List all cameras
            for camera in arlo.cameras:
                print("camera: name={},device_id={},state={}".format(camera.name, camera.device_id, camera.state))

        elif command == 'list-lights':
            # List all lights
            for light in arlo.lights:
                print("light: name={},device_id={},state={}".format(light.name, light.device_id, light.state))

        elif command == 'list-base':
            # List all base stations
            for base in arlo.base_stations:
                print("base: name={},device_id={},state={},mode={}".format(base.name, base.device_id, base.state, base.mode))
                # pprint.pprint(base.available_modes)
                pprint.pprint(base.available_modes_with_ids)

        elif command == 'set-mode' and parameter1 == 'deaktiviert':
            base = getDeviceFromName("Home",arlo.base_stations)
            base.mode = 'disarmed'
            base = getDeviceFromName("Bridge_AZMichael",arlo.base_stations)
            base.mode = 'disarmed'
            base = getDeviceFromName("Bridge_AZSabine",arlo.base_stations)
            base.mode = 'disarmed'

        elif command == 'set-mode' and parameter1 == 'aktiviert':
            base = getDeviceFromName("Home",arlo.base_stations)
            base.mode = 'armed'
            base = getDeviceFromName("Bridge_AZMichael",arlo.base_stations)
            base.mode = 'armed'
            base = getDeviceFromName("Bridge_AZSabine",arlo.base_stations)
            base.mode = 'armed'

        elif command == 'set-mode' and parameter1 == 'aktiviert_tag':
            base = getDeviceFromName("Home",arlo.base_stations)
            base.mode = 'aktiviert_tag'
            base = getDeviceFromName("Bridge_AZMichael",arlo.base_stations)
            base.mode = 'aktiviert_tag'
            base = getDeviceFromName("Bridge_AZSabine",arlo.base_stations)
            base.mode = 'aktiviert_tag'

        elif command == 'set-mode' and parameter1 == 'garten':
            base = getDeviceFromName("Home",arlo.base_stations)
            base.mode = 'garten_alle'
            base = getDeviceFromName("Bridge_AZMichael",arlo.base_stations)
            base.mode = 'garten'
            base = getDeviceFromName("Bridge_AZSabine",arlo.base_stations)
            base.mode = 'armed'

        elif command == 'set-mode' and parameter1 == 'garten_hinten':
            base = getDeviceFromName("Home",arlo.base_stations)
            base.mode = 'garten_2'
            base = getDeviceFromName("Bridge_AZMichael",arlo.base_stations)
            base.mode = 'disarmed'
            base = getDeviceFromName("Bridge_AZSabine",arlo.base_stations)
            base.mode = 'armed'

        elif command == 'get-mode':
            base = getDeviceFromName("Home",arlo.base_stations)
            sendCommandtoFHEM(FHEM_HOST, FHEM_PORT, FHEM_PASSWORD, "setreading Arlo_Cam.dum status-Home "+base.mode)
            base = getDeviceFromName("Bridge_AZMichael",arlo.base_stations)
            sendCommandtoFHEM(FHEM_HOST, FHEM_PORT, FHEM_PASSWORD, "setreading Arlo_Cam.dum status-Bridge_AZMichael "+base.mode)
            base = getDeviceFromName("Bridge_AZSabine",arlo.base_stations)
            sendCommandtoFHEM(FHEM_HOST, FHEM_PORT, FHEM_PASSWORD, "setreading Arlo_Cam.dum status-Bridge_AZSabine "+base.mode)

        elif command == 'set-brightness':
            print(command,parameter1,parameter2,"is currently not supported")
            #camera = getDeviceFromName(parameter1,arlo.cameras)
            #camera.brightness = int(parameter2)

        elif command == 'quit':
            print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "- arlo-fhem - quit command received ... exiting!")
            arlo.stop()
            conn.close()
            sys.exit(0)

        else:
            # Should not happen ...
            print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "- arlo-fhem - Unknown command - ignoring")

    # print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "- arlo-fhem - Connection closed ")
    conn.close()
