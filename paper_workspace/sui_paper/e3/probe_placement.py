#!/usr/bin/env python3
"""Does the validator you submit to determine your consensus author index? Measured live, read-only.

The "priority lane" is the product of two facts:
  (a) the validator a transaction is first submitted to includes it in that validator's own proposed
      block, so the author index of the transaction is that validator's committee index;
  (b) within a consensus round, a lower author index is ordered first (settled read-only on mainnet
      in the census, e1/).
This probe settles (a) on a live network without sending any transaction, spending anything, or
contending with anyone. We open a connection to each reachable testnet validator and send the
protocol's built-in position probe (SubmitTransaction with an empty transaction list, submit_type =
Ping, messages_grpc.rs). The validator replies with the consensus position it would assign: epoch,
round, and author index of its own next block. We record that author index and check it equals the
validator's committee index (the rank of its protocol public key). No funds, no state change, no
faucet, no transactions.

Usage: probe_placement.py --committee data/testnet_committee.json --out data/placement.json [--reps 5]
"""
import argparse, json, time

import vgrpc


def probe_one(v, reps, pause):
    """Return the author indices the validator reports over `reps` position probes."""
    authors, epoch, err = [], None, None
    try:
        c = vgrpc.Validator(v["host"], v["port"], timeout=15)
        for _ in range(reps):
            status, msg, res = c.ping()
            if status != "0" or not res or res[0][0] != "submitted":
                err = f"grpc-status={status} msg={msg!r} res={res!r}"
                break
            pos = res[0][1]
            authors.append(pos["author"])
            epoch = pos["epoch"]
            time.sleep(pause)
    except Exception as e:  # unreachable host, closed socket, TLS failure
        err = repr(e)[:160]
    return authors, epoch, err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--committee", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--pause", type=float, default=0.2, help="seconds between probes to one validator")
    a = ap.parse_args()

    com = json.load(open(a.committee))
    vals = com["validators"]
    rows, match, total, unreachable = [], 0, 0, 0
    for v in vals:
        authors, epoch, err = probe_one(v, a.reps, a.pause)
        row = dict(index=v["index"], name=v["name"], host=v["host"], epoch=epoch,
                   authors=authors, err=err)
        # A validator passes when every probe reports its own committee index as the author.
        row["reported_consistent"] = bool(authors) and all(x == authors[0] for x in authors)
        row["author"] = authors[0] if authors else None
        row["matches_index"] = bool(authors) and all(x == v["index"] for x in authors)
        rows.append(row)
        if err and not authors:
            unreachable += 1
        if authors:
            total += 1
            match += row["matches_index"]
        tag = "ok " if row["matches_index"] else ("--  " if not authors else "MISMATCH ")
        print(f"{tag} idx {v['index']:3d}  {v['name'][:26]:26s}  reported author {row['author']}")

    out = dict(
        epoch=com["epoch"], committee_size=len(vals),
        probed=total, unreachable=unreachable,
        author_equals_index=match,
        author_equals_index_share=match / total if total else 0.0,
        mismatches=[r for r in rows if r["author"] is not None and not r["matches_index"]],
        reps=a.reps, rows=rows)
    json.dump(out, open(a.out, "w"), indent=1)
    print(f"\nepoch {out['epoch']}  committee {out['committee_size']}  probed {total}  "
          f"unreachable {unreachable}  author==index {match}/{total} "
          f"({out['author_equals_index_share']*100:.1f}%)")


if __name__ == "__main__":
    main()
