# PyArlo Log Encrypter

A lightweight web service and API that allows users to securely encrypt debug logs and diagnostic reports before sharing them in public GitHub issues.

Hosted service available at: **[https://aarlo-dot-twrecked-tools.nn.r.appspot.com](https://aarlo-dot-twrecked-tools.nn.r.appspot.com)**

---

## Overview

When reporting issues with Arlo hardware or library integration, full debug logs often contain device serial numbers, local network details, and account metadata. 

This service provides:
1. **Web Interface (`/` or `/enc`)**: Users can paste plain text logs or upload a log file, click **Submit**, and receive an encrypted text block with a single-click "Copy to Clipboard" button.
2. **API Endpoint (`POST /encrypt`)**: Programmatically accepts plain text logs via form data or file upload and returns an encrypted `v2` envelope.

---

## How It Works

The service uses a standard **hybrid encryption** scheme:
1. **AES-128-EAX**: Generates a random one-time symmetric key to encrypt the payload with authenticated encryption (ciphertext + authentication tag + nonce).
2. **RSA-2048 PKCS1_OAEP**: Encrypts the random AES key using the maintainer's public RSA key.
3. **Envelope Packaging**: Encapsulates the encrypted key, nonce, ciphertext, and tag in a `v2` base64 JSON envelope wrapped between standard delimiters:
   ```text
   -----BEGIN PYAARLO DUMP-----
   ...
   -----END PYAARLO DUMP-----
   ```
4. Only the repository maintainer holding the matching private key (`rsa.private`) can decrypt the logs using `pyaarlo-utils decrypt`.

---

## Running Locally

To run the web service locally for development or testing:

### 1. Requirements
* Python 3.10+
* Virtual environment (recommended)

### 2. Install & Run
```bash
cd pyaarlo-log-encrypter
pip install -r requirements.txt
python main.py
```

The service will start at: **`http://127.0.0.1:8080`**.

---

## Deployment to Google App Engine

The service is configured as an App Engine microservice (`service: aarlo`) within the `twrecked-tools` project.

### 1. Prerequisites
* Google Cloud SDK (`gcloud`) installed and authenticated:
  ```bash
  gcloud auth login
  gcloud config set project twrecked-tools
  ```

### 2. Deploy
Deploy to App Engine:
```bash
cd pyaarlo-log-encrypter
gcloud app deploy app.yaml
```

To deploy a timestamped version without immediately routing traffic:
```bash
gcloud app deploy app.yaml --version v$(date +%Y%m%dt%H%M) --no-promote
```

---

## CLI Integration

`pyaarlo` includes built-in commands that communicate with or mimic this service:

* **`pyaarlo-encrypt`**:
  Pipe logs directly to the hosted endpoint:
  ```bash
  cat debug.log | pyaarlo-encrypt
  ```

* **`pyaarlo --debug-report`**:
  All `pyaarlo` commands accept `--debug-report <file>` to automatically anonymize and encrypt diagnostic logs locally using the same public key.
