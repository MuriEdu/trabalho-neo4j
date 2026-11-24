"""Coleta reproduzível da API e carga idempotente de um recorte no Neo4j."""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE = 'https://dadosabertos.camara.leg.br/api/v2'
RAW = Path('data/raw')


def get(url):
    for attempt in range(5):
        try:
            with urlopen(Request(url, headers={'Accept': 'application/json', 'User-Agent': 'camara-neo4j-academico/1.0'}), timeout=60) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def pages(path, limit=0, **params):
    params.update({'itens': 100, 'pagina': 1})
    url = BASE + path + '?' + urlencode(params)
    result = []
    while url:
        try:
            page = get(url)
        except HTTPError as exc:
            # Alguns endpoints de detalhe retornam a lista inteira e não aceitam paginação.
            if exc.code != 400 or result or set(params) != {'itens', 'pagina'}:
                raise
            page = get(BASE + path)
        result.extend(page['dados'])
        if limit and len(result) >= limit:
            return result[:limit]
        url = next((link['href'] for link in page.get('links', []) if link.get('rel') == 'next'), None)
    return result


def id_from_uri(uri):
    if not uri:
        return None
    try:
        return int(urlparse(uri).path.rstrip('/').split('/')[-1])
    except ValueError:
        return None


def collect(args):
    # A ordenação explicita como o recorte limitado de proposições é selecionado.
    propositions = pages('/proposicoes', limit=args.limite_proposicoes, ano=args.ano, siglaTipo='PL', ordem='ASC', ordenarPor='id')
    fronts = pages('/frentes', limit=args.limite_frentes, idLegislatura=args.legislatura)
    data = {'proposicoes': propositions, 'frentes': fronts, 'autores': {}, 'votacoes': {}, 'votos': {}, 'membros': {}}
    for index, p in enumerate(propositions, 1):
        key = str(p['id'])
        print(f'Proposição {index}/{len(propositions)}: {key}', flush=True)
        data['autores'][key] = pages(f'/proposicoes/{key}/autores')
        votes = pages(f'/proposicoes/{key}/votacoes')
        data['votacoes'][key] = votes
        for vote in votes:
            vid = str(vote['id'])
            if vid not in data['votos']:
                data['votos'][vid] = pages(f'/votacoes/{vid}/votos')
    for index, front in enumerate(fronts, 1):
        key = str(front['id'])
        print(f'Frente {index}/{len(fronts)}: {key}', flush=True)
        data['membros'][key] = pages(f'/frentes/{key}/membros')
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / args.arquivo
    snapshot = {'metadados': {'fonte': BASE, 'coletado_em_utc': datetime.now(timezone.utc).isoformat(), 'ano_proposicoes': args.ano, 'legislatura_frentes': args.legislatura, 'limite_proposicoes': args.limite_proposicoes, 'limite_frentes': args.limite_frentes, 'selecao': 'PL em ordem crescente de id; 0 = todos'}, 'dados': data}
    tmp = out.with_suffix(out.suffix + '.tmp')
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(out)
    print(f'Snapshot salvo em {out}')


def rows(snapshot):
    d = snapshot['dados']
    deputies, parties, memberships, authors, ballots, votes, links = {}, {}, {}, [], {}, [], []
    def deputy(obj):
        if not isinstance(obj, dict) or obj.get('id') is None:
            return None
        ident = obj['id']
        # Não substituir informação disponível por um registro incompleto.
        record = deputies.setdefault(ident, {'id': ident})
        for k in ('nome', 'siglaUf', 'urlFoto'):
            if obj.get(k):
                record[k] = obj[k]
        party = obj.get('siglaPartido')
        if party:
            parties[party] = {'sigla': party}
            memberships[(ident, party)] = {'deputado': ident, 'partido': party}
        return ident
    for fid, members in d['membros'].items():
        for member in members:
            ident = deputy(member)
            if ident is not None:
                links.append({'deputado': ident, 'frente': int(fid)})
    for pid, author_list in d['autores'].items():
        for author in author_list:
            # Outros autores (comissões, senadores etc.) não são deputados.
            if author.get('codTipo') != 10000 and author.get('tipo') != 'Deputado':
                continue
            ident = id_from_uri(author.get('uri'))
            if ident is not None:
                deputy({'id': ident, 'nome': author.get('nome')})
                authors.append({'deputado': ident, 'proposicao': int(pid)})
    proposition_votes = []
    for pid, ballot_list in d['votacoes'].items():
        for ballot in ballot_list:
            vid = str(ballot['id'])
            ballots[vid] = {k: ballot.get(k) for k in ('id', 'data', 'descricao', 'aprovacao')}
            proposition_votes.append({'proposicao': int(pid), 'votacao': vid})
    for vid, vote_list in d['votos'].items():
        for vote in vote_list:
            ident = deputy(vote.get('deputado_'))
            if ident is not None:
                votes.append({'deputado': ident, 'votacao': str(vid), 'tipo': vote.get('tipoVoto'), 'dataRegistro': vote.get('dataRegistroVoto')})
    return {'deputados': list(deputies.values()), 'partidos': list(parties.values()), 'filiacoes': list(memberships.values()), 'frentes': [{'id': f['id'], 'titulo': f.get('titulo'), 'idLegislatura': f.get('idLegislatura')} for f in d['frentes']], 'proposicoes': [{k: p.get(k) for k in ('id', 'siglaTipo', 'numero', 'ano', 'ementa')} for p in d['proposicoes']], 'votacoes': list(ballots.values()), 'membros': links, 'autorias': authors, 'proposicao_votacoes': proposition_votes, 'votos': votes}


QUERIES = {
'deputados': 'UNWIND $rows AS r MERGE (n:Deputado {id:r.id}) SET n += r',
'partidos': 'UNWIND $rows AS r MERGE (n:Partido {sigla:r.sigla})',
'frentes': 'UNWIND $rows AS r MERGE (n:Frente {id:r.id}) SET n += r',
'proposicoes': 'UNWIND $rows AS r MERGE (n:Proposicao {id:r.id}) SET n += r',
'votacoes': 'UNWIND $rows AS r MERGE (n:Votacao {id:r.id}) SET n += r',
'filiacoes': 'UNWIND $rows AS r MATCH (d:Deputado {id:r.deputado}), (p:Partido {sigla:r.partido}) MERGE (d)-[:FILIACAO_OBSERVADA]->(p)',
'membros': 'UNWIND $rows AS r MATCH (d:Deputado {id:r.deputado}), (f:Frente {id:r.frente}) MERGE (d)-[:INTEGRA]->(f)',
'autorias': 'UNWIND $rows AS r MATCH (d:Deputado {id:r.deputado}), (p:Proposicao {id:r.proposicao}) MERGE (d)-[:AUTOR_DE]->(p)',
'proposicao_votacoes': 'UNWIND $rows AS r MATCH (p:Proposicao {id:r.proposicao}), (v:Votacao {id:r.votacao}) MERGE (p)-[:SUBMETIDA_A]->(v)',
'votos': 'UNWIND $rows AS r MATCH (d:Deputado {id:r.deputado}), (v:Votacao {id:r.votacao}) MERGE (d)-[rel:VOTOU_EM]->(v) SET rel.tipo = r.tipo, rel.dataRegistro = r.dataRegistro',
}


def load(args):
    from neo4j import GraphDatabase
    snapshot = json.loads((RAW / args.arquivo).read_text(encoding='utf-8'))
    normalized = rows(snapshot)
    with GraphDatabase.driver(os.getenv('NEO4J_URI', 'bolt://localhost:7687'), auth=(os.getenv('NEO4J_USER', 'neo4j'), os.getenv('NEO4J_PASSWORD', 'trabalho123'))) as driver:
        driver.verify_connectivity()
        with driver.session() as session:
            for label, prop in [('Deputado', 'id'), ('Partido', 'sigla'), ('Frente', 'id'), ('Proposicao', 'id'), ('Votacao', 'id')]:
                session.run(f'CREATE CONSTRAINT {label.lower()}_unique IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE').consume()
            for key, query in QUERIES.items():
                values = normalized[key]
                for i in range(0, len(values), 1000):
                    session.run(query, rows=values[i:i+1000]).consume()
                print(f'{key}: {len(values)} registros processados')
    print('Carga concluída. A carga é cumulativa; consulte o README antes de trocar o recorte.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('coletar')
    c.add_argument('--ano', type=int, default=2023)
    c.add_argument('--legislatura', type=int, default=57)
    c.add_argument('--limite-proposicoes', type=int, default=100, help='0 para todos os PLs')
    c.add_argument('--limite-frentes', type=int, default=0, help='0 para todas as frentes')
    c.add_argument('--arquivo', default='snapshot.json')
    l = sub.add_parser('importar')
    l.add_argument('--arquivo', default='snapshot.json')
    args = parser.parse_args()
    if args.command == 'coletar':
        if args.limite_proposicoes < 0 or args.limite_frentes < 0:
            parser.error('limite deve ser maior ou igual a zero')
        collect(args)
    else:
        load(args)

if __name__ == '__main__':
    main()
