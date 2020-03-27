# pyaarlo
Asynchronous Arlo Component for Python

Python Aarlo is a library that provides asynchronous access to  Netgear Arlo cameras.

It is based on the [pyarlo library](https://github.com/tchellomello/python-arlo) and aims to provide a similar interface.

### Installation

```bash
pip install git+https://github.com/twrecked/pyaarlo
```

### 2FA

Support is mostly there, it just needs testing. Pass the following parameters Aarlo to try:

```python
tfa_source='imap',tfa_type='email',
imap_host='imap.host.com',imap_username='your-user-name',imap_password='your-imap-password'
```

If you're just doing quick testing from the console you're good to go, see [here](https://github.com/twrecked/pyaarlo/blob/master/example.py).


### Usage

**This needs updating...**

Start by looking at [here](https://github.com/tchellomello/python-arlo/blob/master/README.rst) at the docs for the original project.

And this [code](https://github.com/twrecked/pyaarlo/blob/master/example.py) shows how to login and set up motion monitoring.



