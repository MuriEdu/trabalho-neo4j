from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timezone
import json, sys, time, hashlib
sys.path.insert(0, '.')
from src.cli import pages as api_pages, BASE
cache=Path("/private/tmp/camara_relatorio_cache")
cache.mkdir(exist_ok=True)
def pages(path, **params):
 key=hashlib.sha256((path+json.dumps(params,sort_keys=True)).encode()).hexdigest()
 dest=cache / (key+".json")
 if dest.exists(): return json.loads(dest.read_text())
 for attempt in range(5):
  try:
   value=api_pages(path, **params)
   dest.write_text(json.dumps(value,ensure_ascii=False))
   return value
  except (OSError, ConnectionError):
   if attempt == 4: raise
   time.sleep(2**attempt)
props=pages('/proposicoes',limit=40,ano=2023,siglaTipo='PL',ordem='ASC',ordenarPor='id')
fronts=pages('/frentes',limit=20,idLegislatura=57)
def getprop(p):
 k=str(p['id']); a=pages('/proposicoes/'+k+'/autores'); v=pages('/proposicoes/'+k+'/votacoes'); print('proposição', k,flush=True);return k,a,v
def getfront(f):
 k=str(f['id']); m=pages('/frentes/'+k+'/membros'); print('frente',k,flush=True);return k,m
with ThreadPoolExecutor(max_workers=5) as e:
 ps=list(e.map(getprop,props)); fs=list(e.map(getfront,fronts))
ballots={str(v['id']) for _,_,vs in ps for v in vs}
def getvotes(k):
 v=pages('/votacoes/'+k+'/votos'); print('votação',k,flush=True);return k,v
with ThreadPoolExecutor(max_workers=5) as e: vs=dict(e.map(getvotes,ballots))
d={'proposicoes':props,'frentes':fronts,'autores':{k:a for k,a,_ in ps},'votacoes':{k:v for k,_,v in ps},'votos':vs,'membros':dict(fs)}
s={'metadados':{'fonte':BASE,'coletado_em_utc':datetime.now(timezone.utc).isoformat(),'ano_proposicoes':2023,'legislatura_frentes':57,'limite_proposicoes':40,'limite_frentes':20,'selecao':'40 PLs por ID crescente e 20 frentes na ordem da API'},'dados':d}
Path('data/raw/relatorio.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf8')
print('Concluída',len(props),len(fronts),len(ballots),flush=True)
