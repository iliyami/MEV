#!/usr/bin/env python3
"""Testnet committee in consensus-index order, with endpoints and our round-trip time to each.

The consensus index of a validator is its rank when the committee is sorted by protocol public key
(crates/sui-types/src/sui_system_state/epoch_start_sui_system_state.rs). For each active testnet
validator we record the index, name, stake, gRPC endpoint (net_address, port 8080), and the median
TCP connect time from this machine (5 tries), used to latency-match the race opponents.

Usage: testnet_committee.py --out data/testnet_committee.json
"""
import argparse, base64, json, socket, statistics, time, urllib.request

G = "https://graphql.testnet.sui.io/graphql"
Q = """query($a:String){ epoch{ epochId referenceGasPrice validatorSet{ activeValidators(first:50, after:$a){
  pageInfo{hasNextPage endCursor} nodes{ contents{ json } } } } } }"""


def q(v):
    r = urllib.request.Request(G, json.dumps({"query": Q, "variables": v}).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=60))


def rtt(host, port, tries=5):
    out = []
    for _ in range(tries):
        t = time.time()
        try:
            s = socket.create_connection((host, port), timeout=3)
            s.close()
            out.append((time.time() - t) * 1000)
        except OSError:
            pass
    return statistics.median(out) if out else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    vals, after, epoch, rgp = [], None, None, None
    while True:
        e = q({"a": after})["data"]["epoch"]
        epoch, rgp = e["epochId"], int(e["referenceGasPrice"])
        av = e["validatorSet"]["activeValidators"]
        for n in av["nodes"]:
            m = n["contents"]["json"]["metadata"]
            parts = m["net_address"].split("/")  # /dns/<host>/tcp/<port>/http
            vals.append(dict(name=m["name"], key=base64.b64decode(m["protocol_pubkey_bytes"]).hex(),
                             host=parts[2], port=int(parts[4]), power=int(n["contents"]["json"]["voting_power"])))
        if not av["pageInfo"]["hasNextPage"]:
            break
        after = av["pageInfo"]["endCursor"]
    vals.sort(key=lambda v: bytes.fromhex(v["key"]))
    for i, v in enumerate(vals):
        v["index"] = i
        v["rtt_ms"] = rtt(v["host"], v["port"])
        print(i, v["name"][:28], v["host"], v["power"], v["rtt_ms"] and round(v["rtt_ms"], 1))
    json.dump(dict(epoch=epoch, rgp=rgp, validators=vals), open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
