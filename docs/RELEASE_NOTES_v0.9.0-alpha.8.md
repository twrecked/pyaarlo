# 🚀 PyArlo v0.9.0-alpha.8 — Release Notes

> Version `0.9.0-alpha.8` introduces native **async SIP-over-WebSocket signaling support for WebRTC live camera streaming**, automated cloud capability document retrieval, and new CLI diagnostic commands for SIP and WebRTC.
>
> **Special Thanks:** This release is based on reverse engineering, protocol design, and foundational pull request ([PR #210](https://github.com/twrecked/pyaarlo/pull/210)) by **Edwin Anne ([@edwin-anne](https://github.com/edwin-anne))**, adapted and modernized to native `asyncio`.

---

## 🌟 What's New in v0.9.0-alpha.8

### 1. Native SIP-over-WebSocket Signaling (`pyaarlo.sip`)
Arlo official web and mobile applications stream live video using WebRTC rather than RTSPS relaying. `pyaarlo` now speaks the native SIP signaling protocol:
* Connects to Arlo's signaling proxy (`wss://<domain>:7443`) with subprotocol `sip`.
* Handles the full SIP handshake: `INVITE` $\rightarrow$ `407 Proxy Authentication Required` (MD5 digest) $\rightarrow$ `200 OK` (with answer SDP) $\rightarrow$ `ACK`.
* Manages keepalive messages (`MESSAGE keepAlive`) and clean teardown (`BYE`).
* Operates on a pure signaling model without touching media packets.

### 2. SDP Repair Helpers (`pyaarlo.sdp`)
Pure, I/O-free SDP sanitation helpers ensure browser and WebRTC stack interoperability:
* `filter_offer_candidates`: Strips IPv6 and `.local` mDNS ICE candidates that Arlo's proxy silently rejects.
* `clean_answer`: Injects missing `a=mid` and direction attributes (`a=sendrecv` / `a=sendonly`) and strips `a=end-of-candidates` that modern browsers reject.

### 3. Dynamic Cloud Capabilities (`pyaarlo.capabilities`)
* Fetches per-model, per-interface-version capability documents directly from Arlo Cloud (`/resources/capabilities/<model>/<model>_<version>.json`).
* Caches capability documents in memory and `ArloStorage` with a 24-hour TTL.
* Falls back to known model prefixes if capability documents cannot be fetched.

### 4. Camera API Additions (`ArloCamera`)
* `async def get_sip_info() -> dict`: REST-only call fetching STUN/TURN server configurations.
* `async def start_sip_stream(offer_sdp: str) -> str`: Connects signaling socket and returns repaired answer SDP.
* `async def stop_sip_stream() -> None`: Sends `BYE` and terminates signaling connection.
* `supports_sip_streaming`, `supports_sip_push_to_talk`, and `has_full_duplex_push_to_talk` properties.

### 5. CLI Verification Commands
* `pyaarlo camera <name> sip-info`: Queries and outputs camera SIP credentials and live ICE servers.
* `pyaarlo camera <name> start-sip-stream --offer-file <path> [--answer-file <path>]`: Negotiates live stream from an SDP offer file and maintains keepalive until interrupted.
* `pyaarlo capabilities <name_or_model> [version]`: Inspects capability documents from Arlo Cloud.

---

## 📦 Upgrading to v0.9.0-alpha.8

Install the pre-release directly from GitHub:
```bash
pip install --upgrade git+https://github.com/twrecked/pyaarlo.git@v0.9.0-alpha.8
```
