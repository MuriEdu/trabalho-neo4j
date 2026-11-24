// Contagem por tipo de nó
MATCH (n) RETURN labels(n) AS tipo, count(*) AS quantidade ORDER BY tipo;
// Contagem por tipo de relacionamento
MATCH ()-[r]->() RETURN type(r) AS tipo, count(*) AS quantidade ORDER BY tipo;
// Amostra visual: todos os tipos de relacionamento encontrados, até 100 por tipo.
MATCH (a)-[r]->(b)
WITH type(r) AS tipo, collect(r)[..100] AS relacoes
UNWIND relacoes AS r
RETURN startNode(r), r, endNode(r);
// Grafo completo: potencialmente grande; use apenas em bases pequenas.
// MATCH (n) OPTIONAL MATCH (n)-[r]->(m) RETURN n, r, m;
