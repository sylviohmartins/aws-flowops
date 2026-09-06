# ADR 012 — DAG determinístico e iteração explícita

- Status: Accepted
- Date: 2026-09-06

## Decisão

Runbooks são DAGs com um Start e término alcançável em End/Stop. Ciclos, arestas duplicadas,
nós desconectados, branches inválidos e referências a outputs futuros são rejeitados antes
da execução. Limites de 200 nós e 1.000 conexões delimitam validação e apresentação.

Loops de negócio usam `core.for_each`, com cardinalidade limitada, checkpoints por item,
impacto agregado e intervalo opcional. IDs internos de iteração não podem colidir com o
grafo nem com outras iterações. A execução mantém os IDs de checkpoints já usados pelo
formato v1. Leituras irmãs podem paralelizar; mutações permanecem serializadas.

## Consequências

O grafo é serializável e reproduzível, e o canvas transporta apenas layout, seleção e edges.
Subflows futuros devem compor/expandir DAGs com namespace de IDs, parâmetros tipados e versão
fixa de cada definição; a versão atual não executa recursão nem runbooks arbitrários embutidos.
