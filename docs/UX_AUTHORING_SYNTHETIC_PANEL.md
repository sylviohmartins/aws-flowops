# Painel sintético de usabilidade da autoria visual

Estado: concluído em 07/10/2026 como avaliação sintética complementar. **Não é estudo com participantes humanos e não deve ser apresentado como tal.**

## Objetivo

Exercitar cognitivamente o protocolo de `docs/UX_AUTHORING_USER_STUDY.md` com dez personas sintéticas, variando experiência técnica, familiaridade com AWS, vocabulário, aversão a risco e dependência de teclado.

Esta avaliação usa como base observável:

- jornada E2E real no navegador em DEMO;
- CI do SHA promovido `c88711fbc3431957c951ca66d153b14ff751041d`, run #218, integralmente verde;
- execução local de `python -m scripts.browser_workspace --authoring-completion` em 07/10/2026: PASS;
- 10 pilotos automatizados anteriores T01-T05/N01-N05: 10/10 PASS, sem chamadas AWS reais.

Os resultados por persona abaixo são **inferências estruturadas**, não comportamento humano observado.

## Personas sintéticas

| ID | Perfil | Experiência | AWS | Comportamento de risco |
| --- | --- | --- | --- | --- |
| S-T01 | SRE sênior | especialista | alta | valida contexto antes de executar |
| S-T02 | Back-end pleno | intermediária | média/alta | busca confirmação antes de mutação |
| S-T03 | Back-end júnior | júnior | média | tende a seguir o assistente literalmente |
| S-T04 | QA/automação | intermediária | média | explora erro, undo e estados |
| S-T05 | Estagiário de desenvolvimento | iniciante | baixa | depende de textos de ajuda |
| S-N01 | Analista de operações | intermediária operacional | baixa | cuidadoso com aprovação |
| S-N02 | Analista de produto | não técnica | baixa | orientado a objetivo, evita jargão |
| S-N03 | Analista de suporte | não técnica | baixa | investiga erro e histórico |
| S-N04 | Assistente de operações | iniciante | nenhuma | segue rótulos e ordem visual |
| S-N05 | Trainee administrativo | iniciante | nenhuma | alta aversão a risco e baixa tolerância a jargão |

## Escala

- **BAIXO**: a interface atual fornece caminho e explicação suficientes para a persona sintética.
- **MÉDIO**: tarefa é alcançável, mas a persona pode precisar reler ajuda, voltar uma etapa ou consultar contexto.
- **ALTO**: risco relevante de pedido de ajuda ou interpretação incorreta; requer atenção em estudo humano futuro.

A escala não substitui "concluiu sem ajuda" do protocolo humano.

## Walkthrough sintético por tarefa

| Tarefa | Evidência observável | Risco técnico | Risco não técnico | Leitura sintética |
| --- | --- | --- | --- | --- |
| 1. Criar Query → aprovação → Lambda e explicar Query/GetItem/Scan | goal wizard e textos explicativos; E2E cria o fluxo | baixo | médio | o fluxo é guiado; o maior risco é terminologia DynamoDB, mitigada por ajuda inline |
| 2. Parâmetro a partir de campo existente | E2E cria `source_system` e preserva default | baixo | médio | controle visual evita expressão manual; conceito de parâmetro pode exigir releitura |
| 3. Filtro, rename, propriedade e objeto aninhado | E2E edita payload visualmente sem JSON | baixo | médio | objetos/listas são alcançáveis; estrutura aninhada é o ponto mais abstrato para iniciantes |
| 4. Renomear, desfazer/refazer e explicar persistência | E2E cobre rename, undo/redo, salvar/publicar | baixo | médio | ações são alcançáveis; diferença entre edição local, rascunho salvo e versão publicada exige atenção |
| 5. Identificar referência inválida e corrigir | E2E injeta tabela inexistente, mostra falha e checkpoint | baixo | médio/alto | diagnóstico é forte; localizar a causa sem conhecimento de AWS é o maior risco cognitivo |
| 6. Revisar, salvar, publicar, simular e executar DEMO | E2E cobre os dois modos; UI explica simulação | baixo | baixo/médio | textos atuais diferenciam simulação e execução efetiva em demonstração |
| 7. Encontrar e decidir aprovação | E2E pausa, abre Aprovações e aprova | baixo | médio | ação é clara; separação solicitante/aprovador e escopo da decisão podem exigir contexto |
| 8. Inspecionar resultado e exportar JSON/CSV | E2E seleciona `invoke` e exporta ambos | baixo | médio | exportação é direta; distinguir aceite assíncrono de sucesso interno depende da explicação já presente |
| 9. Repetir usando teclado | CI e E2E keyboard-first passam | baixo | médio | alcançabilidade está comprovada; facilidade de descoberta por pessoa real permanece não observada |

## Resultado sintético por persona

Abaixo, "provável ajuda" significa hipótese de fricção cognitiva, não uma sessão humana.

| Persona | Tarefas com risco médio/alto | Principal hipótese de ajuda |
| --- | --- | --- |
| S-T01 | nenhuma crítica | nenhuma |
| S-T02 | 4 | persistência entre edição local/rascunho/publicação |
| S-T03 | 1, 5 | diferença Query/GetItem/Scan e diagnóstico de recurso |
| S-T04 | 4 | semântica de persistência após undo/redo |
| S-T05 | 1, 3, 5, 7 | jargão AWS, payload aninhado, diagnóstico e aprovação |
| S-N01 | 1, 5, 7 | jargão DynamoDB e fronteira da decisão |
| S-N02 | 1, 2, 3, 5, 7, 8 | conceitos técnicos abstratos |
| S-N03 | 1, 3, 5, 8 | DynamoDB, estrutura do payload e semântica do resultado |
| S-N04 | 1, 2, 3, 4, 5, 7, 8, 9 | vocabulário e modelo mental de rascunho/execução |
| S-N05 | 1, 2, 3, 4, 5, 6, 7, 8, 9 | baixa familiaridade com cloud e medo de executar |

## Achados

### 1. Não há bloqueio técnico demonstrado

A jornada completa é executável por UI visual e teclado, sem JSON/expressões manuais nos casos cobertos, e todos os gates de navegador do SHA promovido estão verdes.

### 2. O risco residual é majoritariamente cognitivo, não de alcance

Os maiores riscos sintéticos concentram-se em:

1. vocabulário Query/GetItem/Scan;
2. diferença entre edição local, rascunho salvo e versão publicada;
3. diagnóstico de referência/recurso inválido;
4. fronteira de responsabilidade de uma aprovação;
5. diferença entre aceite assíncrono de Lambda e sucesso interno.

### 3. A interface já contém mitigação explícita

O produto atual já explica:

- Query retorna `Items`, GetItem retorna `Item`, Scan é varredura e não fallback;
- simulação não cria pendência humana;
- execução efetiva em DEMO usa dados fictícios;
- aprovação pausa a execução efetiva;
- envio assíncrono não equivale a sucesso interno da Lambda;
- configuração visual não exige JSON nos casos suportados.

Não foi identificado um defeito de alto impacto que justifique alterar a implementação apenas com base nesta simulação.

## Decisão de produto

Em 07/10/2026, o proprietário do projeto autorizou substituir, para **esta fase**, a exigência operacional de executar o estudo com dez pessoas reais por uma avaliação sintética/automatizada, aceitando conscientemente a limitação de não haver observação humana.

Isso é registrado como **dispensa explícita do requisito**, não como realização de sessões humanas.

Consequências:

- não preencher T01-T05/N01-N05 como pessoas reais;
- não usar os números sintéticos para alegar taxa real de sucesso, facilidade de uso ou tempo humano;
- manter o protocolo humano disponível para uma futura rodada de validação caso o produto avance para uso real;
- permitir o fechamento administrativo do workstream atual por `REJECTED_WITH_REASON` / requisito dispensado.

## Conclusão

A implementação técnica está validada e o painel sintético não encontrou bloqueio funcional novo. O risco que permanece sem evidência empírica é a compreensão espontânea por usuários reais, sobretudo perfis sem familiaridade com AWS.

Para a fase atual, esse risco foi aceito explicitamente pelo proprietário do projeto. O estudo humano não é declarado concluído; ele foi dispensado como requisito de fechamento desta fase.
