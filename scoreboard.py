import csv, statistics as s
rows=[r for r in csv.DictReader(open('calls.csv')) if r['multiple']]
m=[float(r['multiple']) for r in rows]
if m: print(f"calls={len(m)} 2x+={sum(x>=2 for x in m)} <=0.5x={sum(x<=0.5 for x in m)} median={s.median(m):.2f}x best={max(m):.1f}x worst={min(m):.2f}x")
else: print("no calls yet")
