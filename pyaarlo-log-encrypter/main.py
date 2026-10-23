import os
import time
import secrets
import re
import pickle
import base64
import json

from flask import Flask, request, jsonify, render_template, Response

try:
    from google.cloud import datastore
except ImportError:
    datastore = None

BEGIN_PYAARLO_DUMP = "-----BEGIN PYAARLO DUMP-----"
END_PYAARLO_DUMP = "-----END PYAARLO DUMP-----"

# PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
# MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1oYXnbQPxREiVPUIRkgk
# h+ehjxHnwz34NsjhjgN1oSKmHpf4cL4L/V4tMnj5NELEmLyTrzAZbeewUMwyiwXO
# 3l+cSjjoDKcPBSj4uxjWsq74Q5TLHGjOtkFwaqqxtvsVn3fGFWBO405xpvp7jPUc
# BOvBQaUBUaR9Tbw5anMOzeavUwUTRp2rjtbWyj2P7PEp49Ixzw0w+RjIVrzzevAo
# AD7SVb6U8P77fht4k9krbIFckC/ByY48HhmF+edh1GZAgLCHuf43tGg2upuH5wf+
# AGv/Xlc+9ScTjEp37uPiCpHcB1ur83AFTjcceDIm+VDKF4zQrj88zmL7JqZy+Upx
# UQIDAQAB
# -----END PUBLIC KEY-----"""
PUBLIC_KEY="""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxzl3k6V+70R3znooqXtr
pN54HrzirF0ogaioOUvL8tK0uE/FLDoeYBJdAGhe9iHYx6wMFUGX9Lp3yduWFr+y
e9azVZTCApLs+DXsofnWN7KoFhb852BeXEHx7qsOqyz7DtahXpJ9HdjW7R50rO48
ZMbKlVjTiQU98ZsbW2E9EKj2Fn3RONjZkO5AaIC2P+9/4dMPn1hKrADH/pNlDQIa
2BKh4BzbDV4wE6o+ZyLozuMEH2Wo/AjTN7mr3xoX+u8/AiGMKel/NdFdp+XayJEZ
x9Q+WOLpRng74qG1lhGFf2l8RQqxVykX0JXxkNiuTckXpfP4ITkYZgaJ5NLZuEns
LwIDAQAB
-----END PUBLIC KEY-----"""


_datastore_client = None


def get_datastore_client():
    global _datastore_client
    if _datastore_client is None:
        if datastore is not None:
            try:
                _datastore_client = datastore.Client()
            except Exception:
                _datastore_client = None
    return _datastore_client

app = Flask(__name__)


def get_arg(arg, default=None):
    value = request.args.get(arg, None)
    if value is None:
        value = request.values.get(arg, default)
    return value


def fixup_email(email):
    if email is not None:
        email = email.replace('@', '.')
        email = email.replace('+', '.')
    return email


def check_admin_token(token):
    if token is None:
        return False

    # get token from env and check for match
    saved_token = os.environ.get('AUTH_TOKEN', None)
    if saved_token is None:
        return False
    return token == saved_token


def get_user_token(fmail):
    if fmail is not None:
        client = get_datastore_client()
        if client is None:
            return None
        query = client.query(kind='tokens')
        query.add_filter('fmail', '=', fmail)
        tokens = list(query.fetch())
        if tokens:
            return tokens[0]['token']
    return None


def create_user_token(fmail):
    if fmail is not None:
        token = secrets.token_hex(24)
        client = get_datastore_client()
        if client is None:
            return None
        entity = datastore.Entity(key=client.key('tokens'))
        entity.update({
            'fmail': fmail,
            'token': token,
            'timestamp': int(time.time())
        })
        client.put(entity)
        return token
    return None


def check_user_token(fmail, token):
    if fmail is None or token is None:
        return False
    return token == get_user_token(fmail)


def is_valid_user(fmail):
    if fmail is None:
        return False
    return get_user_token(fmail) is not None


def get_user_code(fmail):
    if fmail is not None:
        client = get_datastore_client()
        if client is None:
            return None
        query = client.query(kind='codes')
        query.add_filter('fmail', '=', fmail)
        codes = list(query.fetch())
        if codes:
            return codes[0]
    return None


def clear_user_code(fmail):
    if fmail is not None:
        client = get_datastore_client()
        if client is None:
            return None
        query = client.query(kind='codes')
        query.add_filter('fmail', '=', fmail)
        codes = query.fetch()
        for old_code in codes:
            client.delete(client.key('codes', old_code.id))


def set_user_code(fmail, code):
    if fmail is not None and code is not None:
        # wipe out old first
        clear_user_code(fmail)

        # add in new
        client = get_datastore_client()
        if client is None:
            return None
        entity = datastore.Entity(key=client.key('codes'))
        entity.update({
            'fmail': fmail,
            'code': code,
            'timestamp': int(time.time())
        })
        client.put(entity)


def has_permission(fmail, token):
    return check_admin_token(token) or check_user_token(fmail, token)


def parse_msg(msg):
    # Sanity check.
    if msg is None:
        return None

    # Search for bits we are interested in
    for line in msg.split(r'\n'):
        line = line.rstrip()

        # look for code
        m = re.match(r'.* (\d{6})\.\W*$', line)
        if m is not None:
            return m.group(1)

    return None


def parse_mail(mail):
    # Sanity check.
    if mail is None:
        return None, None

    # Search for bits we are interested in
    email = None
    code = None
    for line in mail:
        line = line.decode().rstrip()

        # look for fmail
        m = re.match(r'^To:\W+<*(.+?)>*\W*$', line)
        if m is not None:
            email = m.group(1)

        # look for code
        m = re.match(r'^\W*(\d{6})\W*$', line)
        if m is not None:
            code = m.group(1)

    return email, code


@app.route('/enc')
@app.route('/')
def enc():
    return render_template('encrypt.html')


@app.route('/encrypt', methods=['POST'])
def encrypt():
    # fill this with file or pasted contents
    obj = None

    # check file first
    if 'plain_text_file' in request.files:
        obj = ""
        plain_text_file = request.files['plain_text_file']
        for line in plain_text_file:
            obj += line.decode()

    # now check for pasted text
    if obj is None:
        obj = request.form.get('plain_text', None)

    # still nothing, then stop
    if obj is None:
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'no attached file or pasted text'}})

    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_OAEP

    try:
        # encode plain text directly to utf-8 bytes
        obj_bytes = obj.encode("utf-8") if isinstance(obj, str) else bytes(obj)

        # create key and encrypt object with it
        key = get_random_bytes(16)
        aes_cipher = AES.new(key, AES.MODE_EAX)
        ciphertext, tag = aes_cipher.encrypt_and_digest(obj_bytes)
        nonce = aes_cipher.nonce

        # encrypt key with public key
        rsa_cipher = RSA.importKey(PUBLIC_KEY)
        rsa_cipher = PKCS1_OAEP.new(rsa_cipher)
        enc_key = rsa_cipher.encrypt(key)

        # create key/object dictionary as JSON with base64 encoded binary fields
        envelope = {
            "v": 2,
            "k": base64.b64encode(enc_key).decode("ascii"),
            "n": base64.b64encode(nonce).decode("ascii"),
            "o": base64.b64encode(ciphertext).decode("ascii"),
            "t": base64.b64encode(tag).decode("ascii"),
        }
        json_bytes = json.dumps(envelope).encode("utf-8")
        enc_str = "{}\n{}{}\n".format(
            BEGIN_PYAARLO_DUMP,
            base64.encodebytes(json_bytes).decode("ascii"),
            END_PYAARLO_DUMP,
        )
        return render_template("encrypted.html", encrypted=enc_str)
    except ValueError as _err:
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'encryption error'}})
    except Exception as ex:
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': str(ex)}})


@app.route('/register')
def register():
    return render_template('register.html')


@app.route('/register_done')
def register_done():
    email = request.args.get('email', None)
    if email is None:
        return jsonify({'success': False, 'error': 'no email supplied'})

    fmail = fixup_email(email)
    if not is_valid_user(fmail):
        token = create_user_token(fmail)
        return jsonify({'success': True,
                        'email': email,
                        'fwd-to': "pyaarlo@thewardrobe.ca",
                        'token': token})
    else:
        return jsonify({'success': False, 'error': 'email already registered'})


@app.route('/get')
def get():
    # get args
    email = request.args.get('email', None)
    fmail = fixup_email(email)
    token = request.args.get('token', None)

    # validate email/token
    if not has_permission(fmail, token):
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'permission denied', 'code': None}})
    if not is_valid_user(fmail):
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'no valid email found', 'code': None}})

    # should be 0 or 1 entries
    code = get_user_code(fmail)
    if code is None:
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'no valid code found', 'code': None}})

    return jsonify({'meta': {'code': 200},
                    'data': {'success': True, 'email': email, 'code': code['code'], 'timestamp': code['timestamp']}})


@app.route('/clear')
def clear():
    # get args
    email = request.args.get('email', None)
    fmail = fixup_email(email)
    token = request.args.get('token', None)

    # validate email/token
    if not has_permission(fmail, token):
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'permission denied'}})
    if not is_valid_user(fmail):
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'no valid email found', 'code': None}})

    # clear code
    clear_user_code(fmail)
    return jsonify({'meta': {'code': 200},
                    'data': {'success': True, 'email': email}})


@app.route('/add', methods=['GET', 'POST'])
def add():
    # get args
    email = get_arg('email')
    fmail = fixup_email(email)
    token = get_arg('token')

    # validate email/token
    if not has_permission(fmail, token):
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'permission denied'}})
    if not is_valid_user(fmail):
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'no valid email found', 'code': None}})

    # read code if passed directly or parse from sms
    code = get_arg('code')
    if code is None:
        code = parse_msg(get_arg('msg'))
        if code is None:
            return jsonify({'meta': {'code': 400},
                            'data': {'success': False, 'error': 'please provide code', 'code': None}})

    set_user_code(fmail, code)
    return jsonify({'meta': {'code': 200},
                    'data': {'success': True, 'email': email, 'code': code}})


@app.route('/mail', methods=['POST'])
def mail():
    # check token to start
    token = request.args.get('token', None)
    if token is None:
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'no token supplied'}})

    # check file is there
    if 'file' not in request.files:
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'no attached email'}})
    mail = request.files['file']
    if mail.filename != 'email.txt':
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'incorrectly attached email'}})

    # Search for bits we are interested in
    email, code = parse_mail(mail)
    fmail = fixup_email(email)
    if email is None or code is None:
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'unable to parse email'}})

    # permission? can be admin or user level
    if not has_permission(fmail, token):
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'permission denied'}})
    if not is_valid_user(fmail):
        return jsonify({'meta': {'code': 400},
                        'data': {'success': False, 'error': 'unknown email', 'code': None}})

    # update and indicate success
    set_user_code(fmail, code)
    return jsonify({'meta': {'code': 200},
                    'data': {'success': True, 'email': email, 'code': code}})


@app.route('/sign-in')
def sign_in():
    return render_template('authenticate.html')


if __name__ == '__main__':
    # This is used when running locally only. When deploying to Google App
    # Engine, a webserver process such as Gunicorn will serve the app. This
    # can be configured by adding an `entrypoint` to app.yaml.

    # Flask's development server will automatically serve static files in
    # the "static" directory. See:
    # http://flask.pocoo.org/docs/1.0/quickstart/#static-files. Once deployed,
    # App Engine itself will serve those files as configured in app.yaml.
    app.run(host='127.0.0.1', port=8080, debug=True)
