"""Minimal client for a Sui validator's SubmitTransaction gRPC call (no generated code).

Wire format, from crates/sui-types/src/messages_grpc.rs (Sui v1.58):
  RawSubmitTxRequest  { 1: repeated bytes transactions (BCS Transaction); 2: enum submit_type (0 Default, 1 Ping) }
  RawSubmitTxResponse { 1: repeated RawSubmitTxResult }
  RawSubmitTxResult   { oneof: 1 Submitted(bytes = BCS ConsensusPosition), 2 Executed, 3 Rejected }
  ConsensusPosition   = epoch u64 | round u32 | author u32 | block digest [32] | tx index u16   (BCS, little endian)
"""
import socket
import ssl
import struct

import h2.config
import h2.connection
import h2.events

METHOD = "/sui.validator.Validator/SubmitTransaction"


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _read_varint(b, i):
    n = s = 0
    while True:
        c = b[i]
        i += 1
        n |= (c & 0x7F) << s
        s += 7
        if not c & 0x80:
            return n, i


def _fields(b):
    """(tag, wire type, value) for each field of a protobuf message."""
    i = 0
    while i < len(b):
        key, i = _read_varint(b, i)
        tag, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _read_varint(b, i)
        elif wt == 2:
            n, i = _read_varint(b, i)
            v, i = b[i:i + n], i + n
        else:
            raise ValueError(f"unsupported wire type {wt}")
        yield tag, wt, v


def request(tx_bcs_list, submit_type=0):
    out = b"".join(b"\x0a" + _varint(len(t)) + t for t in tx_bcs_list)
    if submit_type:
        out += b"\x10" + _varint(submit_type)
    return out


def position(raw):
    epoch, rnd, author = struct.unpack_from("<QII", raw, 0)
    (idx,) = struct.unpack_from("<H", raw, 48)
    return dict(epoch=epoch, round=rnd, author=author, block=raw[16:48].hex(), tx_index=idx)


def parse_response(b):
    """List of per-transaction results: ('submitted', position) | ('executed', None) | ('rejected', raw)."""
    out = []
    for tag, _, res in _fields(b):
        if tag != 1:
            continue
        for t, _, v in _fields(res):
            out.append(("submitted", position(v)) if t == 1 else ("executed", None) if t == 2 else ("rejected", bytes(v)))
    return out


class Validator:
    """A warm TLS HTTP/2 connection to one validator, speaking gRPC framing directly.

    Validators serve a self-signed Ed25519 certificate for the name "sui" (crates/sui-tls/src/lib.rs,
    SUI_VALIDATOR_SERVER_NAME), which the grpcio library refuses; the Sui client instead pins the
    validator's network key. We use OpenSSL with certificate checks off: nothing secret is sent,
    and a wrong server could only make a probe fail, which shows up in the result."""

    def __init__(self, host, port=8080, timeout=20):
        self.host, self.port, self.timeout = host, port, timeout
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_alpn_protocols(["h2"])
        raw = socket.create_connection((host, port), timeout=timeout)
        raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock = ctx.wrap_socket(raw, server_hostname="sui")
        self.h2 = h2.connection.H2Connection(h2.config.H2Configuration(client_side=True))
        self.h2.initiate_connection()
        self.sock.sendall(self.h2.data_to_send())

    def prepare(self, tx_bcs_list, submit_type=0):
        """Encode the request; returns bytes for fire(), so the send itself does no work."""
        msg = request(tx_bcs_list, submit_type)
        sid = self.h2.get_next_available_stream_id()
        self.h2.send_headers(sid, [(":method", "POST"), (":scheme", "https"), (":path", METHOD),
                                   (":authority", "sui"), ("content-type", "application/grpc"), ("te", "trailers")])
        self.h2.send_data(sid, b"\x00" + struct.pack(">I", len(msg)) + msg, end_stream=True)
        return sid, self.h2.data_to_send()

    def fire(self, prepared):
        self.sock.sendall(prepared[1])
        return prepared[0]

    def wait(self, sid):
        """Read until stream `sid` ends; returns (grpc-status, message, parsed results)."""
        body, status, msg = b"", None, ""
        while True:
            data = self.sock.recv(65536)
            if not data:
                raise ConnectionError("closed")
            for ev in self.h2.receive_data(data):
                if isinstance(ev, h2.events.DataReceived):
                    if ev.stream_id == sid:
                        body += ev.data
                    self.h2.acknowledge_received_data(ev.flow_controlled_length, ev.stream_id)
                elif isinstance(ev, (h2.events.ResponseReceived, h2.events.TrailersReceived)) and ev.stream_id == sid:
                    hd = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                          for k, v in ev.headers}
                    status = hd.get("grpc-status", status)
                    msg = hd.get("grpc-message", msg)
                elif isinstance(ev, h2.events.StreamEnded) and ev.stream_id == sid:
                    self.sock.sendall(self.h2.data_to_send())
                    res = parse_response(body[5:]) if len(body) >= 5 else []
                    return status, msg, res
            self.sock.sendall(self.h2.data_to_send())

    def submit(self, tx_bcs_list, submit_type=0):
        return self.wait(self.fire(self.prepare(tx_bcs_list, submit_type)))

    def ping(self):
        return self.submit([], submit_type=1)
