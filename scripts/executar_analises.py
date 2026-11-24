import json, os
from neo4j import GraphDatabase
from pathlib import Path
source=Path('/app/queries/analises.cypher').read_text()
queries=[q.strip() for q in source.split(';') if q.strip()]
with GraphDatabase.driver(os.environ['NEO4J_URI'],auth=(os.environ['NEO4J_USER'],os.environ['NEO4J_PASSWORD'])) as driver:
 with driver.session() as s:
  nodes={r['tipo']:r['quantidade'] for r in s.run('MATCH (n) RETURN labels(n)[0] AS tipo, count(*) AS quantidade')}
  rels={r['tipo']:r['quantidade'] for r in s.run('MATCH ()-[r]->() RETURN type(r) AS tipo, count(*) AS quantidade')}
  period=s.run('MATCH (v:Votacao) WHERE v.data IS NOT NULL RETURN min(v.data) AS inicio, max(v.data) AS fim').single().data()
  results=[]
  for n,q in enumerate(queries,1):
   results.append({'id':n,'linhas':[r.data() for r in s.run(q)]})
  samples={}
  for label in ['Deputado','Partido','Frente','Proposicao','Votacao']:
   samples[label]=[r['n'] for r in s.run(f'MATCH (n:{label}) RETURN properties(n) AS n LIMIT 2')]
  examples={}
  for rel in ['FILIACAO_OBSERVADA','INTEGRA','AUTOR_DE','SUBMETIDA_A','VOTOU_EM']:
   examples[rel]=[r.data() for r in s.run(f'MATCH (a)-[r:{rel}]->(b) RETURN labels(a)[0] AS origem, properties(a) AS a, labels(b)[0] AS destino, properties(b) AS b, properties(r) AS rel LIMIT 2')]
  print(json.dumps({'carga':{'nos':nodes,'relacoes':rels,'periodo_votacoes':period,'exemplos_nos':samples,'exemplos_relacoes':examples},'consultas':results},ensure_ascii=False,default=str))
