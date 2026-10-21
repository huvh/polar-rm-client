# Official client / engine video evidence, 2026-10-20

Static inspection of vendor downloads only. No vendor program, installer,
radio command or network reconfiguration was run. No physical video result is claimed.

## Requested downloads

Source: [official software wiki](https://bbs.robomaster.com/wiki/20204847/804784?source=7).

- [Student client 12.0.0.213](https://bbs-web-static.robomaster.com/55bea4d5b5f94a8d8adc2a5f40c225d81783394887530/RoboMasterClient%2012.0.0.213_Student.zip),
  420,317,398 bytes. SHA-256
  `661498326b6a0047d5cf73a4f9ceede3297cba4b0e745aa49c69a46eba873374`.
  All 170 ZIP entries passed CRC checks.
- [Student engine 12.0.0.137](https://bbs-web-static.robomaster.com/ca2ace25e37c4568b399569db0de8db61785413857676/RoboMasterEngine%2012.0.0.137_Student.zip),
  429,242,136 bytes. SHA-256
  `61586fb4083399cbc5607f17e895af42b43b5199ee09522087f628e3354ea933`.
  All 939 ZIP entries passed CRC checks.

Hashes are independently calculated, not vendor signatures. These are Windows
packages; the verification host is Linux, so package execution was not tested.
The current client ReadMe requires root Start.bat, .NET 7, Visual C++ runtime,
and bundled DJI_Driver_Installer_32bit&64bit_4.8.11.exe. The older product-page
Phantom 4 Drivers_1.2 link is not the only current prerequisite. No installation
or license acceptance was performed.

## Legacy path: raw H.264 / UDP 8080

The 2019 official VT02 archive provenance is recorded in
[the integration guide](../legacy_video_ingress.md). Current software corroborates
that observed contract, rather than replacing it with an inferred USB protocol:

- Client 12.0.0.213 UseRenderingPlugin.Start token 0x06000d91 maps to RVA 0x3255d0;
  its actual call at RVA 0x325988 constructs UdpClient on port 8080. The CPU renderer
  independently binds 8080 at RVA 0x344f42.
- RcvUdpThread receives a byte array and passes its full contents and length to
  native PushVideoData without an 8-byte header strip.
- DJIVideoParser.dll is byte-identical in 11.0.1.128 and 12.0.0.213; SHA-256
  `00213c5b40e23642be4479d7a4936350ce680b9df15557b30cbbb7793c997792`.
  PushVideoData RVA 0x1c00 → queued full byte vector → av_parser_parse2 at 0x4e36.
  Initialization selects H.264 codec 0x1c. UDP packets are stream blocks, not frames.

These are exact compiled legacy-renderer paths, not a guarantee that every
receiver/firmware uses them. The package contains multiple video modes. Do not
infer the active hardware route from class names or change shipped settings silently.

## Modern export: separate HEVC / UDP 3334

Current Video2025SerialPortThread.ApplyUdpTarget passes a nonempty MQTT-client
IP to RC150.SetUdpTarget only when export is not stopped. Native RC150 selects
UDP 3334, HEVC encoders (NVENC/QSV/AMF/libx265), and chunks encoded packets with
an 8-byte big-endian uint16 frame / uint16 fragment / uint32 total-length header.
Maximum payload is 1392 bytes; maximum datagram 1400 bytes. Encoder initialization
can fail independently of local rendering.

No verified call chain exports old 8080 input through this new 3334 path.
The [official custom-client guide](https://bbs-web-static.robomaster.com/89561459842d4ee5b979ac55af1ca7781776680883135/RoboMaster%E8%B5%9B%E4%BA%8B%E5%BC%95%E6%93%8E%E8%87%AA%E5%AE%9A%E4%B9%89%E5%AE%A2%E6%88%B7%E7%AB%AF%E9%85%8D%E7%BD%AE%E8%AF%B4%E6%98%8E%E6%89%8B%E5%86%8C%EF%BC%88202604%EF%BC%89.pdf)
requires player 192.168.12.1, custom client static 192.168.12.2, same robot ID, and
normal official-client video before forwarding. Binding 3334 does not initialize
the receiver. This network is distinct from the legacy receiver-side host NIC.

## Control/process ownership

The official legacy renderer itself owns 8080. A second ordinary listener cannot
be assumed to receive that traffic. Static helper inspection found no supported
video-only initialization CLI: the helper starts multiple device loops, receives
role/channel commands from elsewhere, and the daemon supervises several helpers
and includes process termination behavior. POLAR must not silently launch it as
an alleged isolated acquisition service.

The optional POLAR Npcap bridge preserves the running official client's receiver
control and 8080 ownership, forwarding only explicitly selected UDP payloads to
loopback 18080. It is our engineering adapter, not DJI's supported export API.
Real BPF compilation, Windows/Npcap/RNDIS behavior and continuous receiver-to-HUD
video remain separate unverified gates. No captured vendor binary, raw user
video, private configuration or decompiled vendor source is included here.
