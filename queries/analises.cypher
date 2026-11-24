// Execute cada bloco separadamente no Neo4j Browser.
// 1. Em quais frentes os integrantes de partidos diferentes mais concordam?
// Apenas votos Sim/Não, pares com pelo menos 10 votações compartilhadas.
MATCH (a:Deputado)-[:INTEGRA]->(f:Frente)<-[:INTEGRA]-(b:Deputado),
      (a)-[:FILIACAO_OBSERVADA]->(pa:Partido), (b)-[:FILIACAO_OBSERVADA]->(pb:Partido),
      (a)-[va:VOTOU_EM]->(v:Votacao)<-[vb:VOTOU_EM]-(b)
WHERE a.id < b.id AND pa.sigla <> pb.sigla AND va.tipo IN ['Sim','Não'] AND vb.tipo IN ['Sim','Não']
WITH f, count(*) AS comparacoes, sum(CASE WHEN va.tipo = vb.tipo THEN 1 ELSE 0 END) AS acordos
WHERE comparacoes >= 10
RETURN f.titulo AS frente, comparacoes, acordos, round(100.0 * acordos / comparacoes, 1) AS concordancia_percentual
ORDER BY concordancia_percentual DESC, comparacoes DESC LIMIT 20;

// 2. Quais pares de deputados mais colaboram como autores de PLs?
MATCH (a:Deputado)-[:AUTOR_DE]->(p:Proposicao)<-[:AUTOR_DE]-(b:Deputado)
WHERE a.id < b.id
RETURN a.nome AS deputado_1, b.nome AS deputado_2, count(DISTINCT p) AS projetos_em_comum,
       collect(DISTINCT p.siglaTipo + ' ' + toString(p.numero) + '/' + toString(p.ano))[..5] AS exemplos
ORDER BY projetos_em_comum DESC, deputado_1 LIMIT 20;

// 3. Como varia a concordância em votações entre pares de partidos?
MATCH (a:Deputado)-[:FILIACAO_OBSERVADA]->(pa:Partido),
      (b:Deputado)-[:FILIACAO_OBSERVADA]->(pb:Partido),
      (a)-[va:VOTOU_EM]->(v:Votacao)<-[vb:VOTOU_EM]-(b)
WHERE a <> b AND pa.sigla < pb.sigla AND va.tipo IN ['Sim','Não'] AND vb.tipo IN ['Sim','Não']
WITH pa, pb, count(*) AS comparacoes, sum(CASE WHEN va.tipo = vb.tipo THEN 1 ELSE 0 END) AS acordos
WHERE comparacoes >= 30
RETURN pa.sigla AS partido_1, pb.sigla AS partido_2, comparacoes,
       round(100.0 * acordos / comparacoes, 1) AS concordancia_percentual
ORDER BY concordancia_percentual DESC, comparacoes DESC LIMIT 20;

// 4. Quais deputados mais divergem dos demais membros de suas frentes?
MATCH (d:Deputado)-[:INTEGRA]->(f:Frente)<-[:INTEGRA]-(outro:Deputado),
      (d)-[vd:VOTOU_EM]->(v:Votacao)<-[vo:VOTOU_EM]-(outro)
WHERE d <> outro AND vd.tipo IN ['Sim','Não'] AND vo.tipo IN ['Sim','Não']
WITH d, f, count(*) AS comparacoes, sum(CASE WHEN vd.tipo <> vo.tipo THEN 1 ELSE 0 END) AS divergencias
WHERE comparacoes >= 30
RETURN d.nome AS deputado, f.titulo AS frente, comparacoes, divergencias,
       round(100.0 * divergencias / comparacoes, 1) AS divergencia_percentual
ORDER BY divergencia_percentual DESC, comparacoes DESC LIMIT 20;

// 5. Quanto os pares de coautores concordam nas votações compartilhadas?
MATCH (a:Deputado)-[:AUTOR_DE]->(p:Proposicao)<-[:AUTOR_DE]-(b:Deputado)
WHERE a.id < b.id
WITH a, b, count(DISTINCT p) AS projetos_em_comum
MATCH (a)-[va:VOTOU_EM]->(v:Votacao)<-[vb:VOTOU_EM]-(b)
WHERE va.tipo IN ['Sim','Não'] AND vb.tipo IN ['Sim','Não']
WITH a, b, projetos_em_comum, count(DISTINCT v) AS votacoes_compartilhadas,
     sum(CASE WHEN va.tipo = vb.tipo THEN 1 ELSE 0 END) AS acordos
WHERE votacoes_compartilhadas >= 3
RETURN a.nome AS deputado_1, b.nome AS deputado_2, projetos_em_comum,
       votacoes_compartilhadas, acordos,
       round(100.0 * acordos / votacoes_compartilhadas, 1) AS concordancia_percentual
ORDER BY votacoes_compartilhadas DESC, concordancia_percentual DESC LIMIT 20;
