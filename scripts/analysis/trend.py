"""Bribery arms: pairwise run-level tests and the trend over 0 to 3 bribes. Usage: python3 trend.py"""
import json, random, sys
import os
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("COAL_DATA", os.path.join(HERE, "../../data/bullshark/coal"))   # per-run score files
exec(open(os.path.join(HERE, "analyze.py")).read().split("for arm, rs in by.items():")[0].replace("sys.argv[1]", repr(os.path.join(DATA, "runs_pooled.jsonl"))))
for a,b in [("solo","bribe1"),("solo","bribe2"),("bribe1","bribe2"),("bribe2","bribe"),("bribe1","bribe"),("base1","bribe1"),("base1","bribe2"),("base1","bribe"),("base1","f4"),("f6rival","f6"),("f6ind","f6rival"),("base4","bribe")]:
    d,p=perm(by[a],by[b]); print(f"{b} - {a}: {d:+6.2f} p={p:.4f}")
# trend test: slope of per-pair success on #bribes, permutation over run labels
arms=[("solo",0),("bribe1",1),("bribe2",2),("bribe",3)]
runs=[(k,r) for a,k in arms for r in by[a]]
def slope(rs):
    X=sum(r["total"] for _,r in rs); mx=sum(k*r["total"] for k,r in rs)/X; my=sum(r["succ"] for _,r in rs)/X
    num=sum(k*r["succ"] for k,r in rs)-mx*my*X; den=sum(k*k*r["total"] for k,r in rs)-mx*mx*X
    return 100*num/den
obs=slope(runs); random.seed(3); ks=[k for k,_ in runs]; rr=[r for _,r in runs]; c=0; B=20000
for _ in range(B):
    random.shuffle(ks)
    if abs(slope(list(zip(ks,rr))))>=abs(obs)-1e-12: c+=1
print(f"trend slope {obs:+.2f} pts/bribe p={(c+1)/(B+1):.4f}")
