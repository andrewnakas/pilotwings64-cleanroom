import collections, sys, traceback
from cleanroom.rom import load_retail
from cleanroom import iff
from games.pilotwings64 import profile as P
from games.pilotwings64.formats import engine
rom=load_retail(r'C:/Users/andre/Downloads/Pilotwings 64 (U) [!].zip')
res=collections.Counter(); tails=collections.Counter(); shown=collections.Counter()
for e,raw in P.read_files(rom):
    f=iff.parse_form(raw)
    for c in f.chunks:
        if f.type in engine.CODECS and c.tag=='COMM':
            pa,bu=engine.CODECS[f.type]
            try:
                ir=pa(c.data); ok= bu(ir)==c.data
                res[(f.type,ok)]+=1
                if ir.get('tail'): tails[f.type]+=1
                if ir.get('tail') and shown[f.type]<2: shown[f.type]+=1; print(f.type,e.kind_index,'tail',len(ir['tail'])//2, ir['tail'][:40])
            except Exception as ex:
                res[(f.type,'ERR')]+=1
                if shown[f.type]<2: shown[f.type]+=1; print(f.type,e.kind_index,'ERR',ex)
print(sorted(res.items())); print('with tails',tails)
