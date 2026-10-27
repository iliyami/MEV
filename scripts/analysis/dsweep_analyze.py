"""Committee-size sweep on Bullshark (dsweep.sh): pooled rate per arm, run bootstrap, one-sided run-label
permutation per committee size, on M3, M2 and M1. Usage: python3 dsweep_analyze.py"""
import json, random, sys
import os
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("COAL_DATA", os.path.join(HERE, "../../data/bullshark/coal"))   # per-run score files
rows=[json.loads(l) for l in open(os.path.join(DATA, 'dsweep_scores.jsonl'))]
arms={}
for r in rows:
    p=r['run'].split('/'); arm=p[p.index('dsweep')+1]   # the directory after dsweep/ (the file's own arm field is wrong)
    m=r['m']
    if not m or not m.get("cells"): arms.setdefault(arm,[]).append(None); continue
    c=list(m['cells'].values())[0]
    arms.setdefault(arm,[]).append({k:(c[k]['succ'],c[k]['total']) for k in ('M3_targeted_committing_height','M1_all_pairs','M2_same_round')})
random.seed(1)
def pooled(L,k): s=sum(x[k][0] for x in L); t=sum(x[k][1] for x in L); return 100*s/t if t else float('nan'), t
def boot(L,k,B=4000):
    v=[]
    for _ in range(B):
        S=[random.choice(L) for _ in L]; p,t=pooled(S,k)
        if t: v.append(p)
    v.sort(); return v[int(.025*len(v))], v[int(.975*len(v))]
def diffboot(A,Bl,k,B=4000):
    d=[]
    for _ in range(B):
        a=[random.choice(A) for _ in A]; b=[random.choice(Bl) for _ in Bl]
        pa,ta=pooled(a,k); pb,tb=pooled(b,k)
        if ta and tb: d.append(pa-pb)
    d.sort(); return d[int(.025*len(d))], d[int(.975*len(d))]
def perm(A,Bl,k,B=4000):
    obs=pooled(A,k)[0]-pooled(Bl,k)[0]; allr=A+Bl; n=len(A); c=0
    for _ in range(B):
        random.shuffle(allr); x=pooled(allr[:n],k)[0]-pooled(allr[n:],k)[0]
        if x>=obs: c+=1
    return (c+1)/(B+1)
for k in ('M3_targeted_committing_height','M2_same_round','M1_all_pairs'):
    print('==',k)
    for a in sorted(arms):
        L=[x for x in arms[a] if x]
        if not L: print(a,'no scored runs'); continue
        p,t=pooled(L,k); lo,hi=boot(L,k)
        runmean=[100*x[k][0]/x[k][1] for x in L if x[k][1]]
        print(f"{a:6s} runs={len(L):2d} pairs={t:6d} pooled={p:5.1f} [{lo:5.1f},{hi:5.1f}] runmean={sum(runmean)/len(runmean):5.1f}")
    for s in ('13','7','25'):
        A=[x for x in arms['f'+s] if x]; Bl=[x for x in arms['b'+s] if x]
        d=pooled(A,k)[0]-pooled(Bl,k)[0]; lo,hi=diffboot(A,Bl,k)
        print(f"  f{s}-b{s}: {d:+5.1f} [{lo:+5.1f},{hi:+5.1f}] perm p={perm(A,Bl,k):.4f}")
