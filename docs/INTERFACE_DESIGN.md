# Alinhamento e consistência da interface

## Recurso escolhido

**ADAPT: Impeccable como referência de design, CSS Grid + Streamlit como implementação e
Playwright como teste de geometria.** Nenhuma dependência de execução foi acrescentada.

O [projeto oficial](https://github.com/pbakaus/impeccable), vinculado pelo site do autor, usa
[Apache-2.0](https://github.com/pbakaus/impeccable/blob/main/LICENSE). Seus comandos
[layout](https://impeccable.style/docs/layout/) e [polish](https://impeccable.style/docs/polish/)
orientam agrupamento, espaçamento, responsividade e acabamento. Não são um motor de layout que
garante automaticamente a posição de cada controle de uma aplicação Streamlit.

Os [detectores/hooks](https://impeccable.style/docs/hooks/) inspecionam formatos web e podem
rodar após alterações. Python/Streamlit não aparece entre os formatos padrão documentados;
por isso a verificação do DOM renderizado é necessária aqui. Não executamos o instalador,
downloads dinâmicos, hooks, extensão ou helper de navegador; não houve concessão de permissões,
leitura de segredos nem envio do código para esse serviço. A decisão avalia a adaptação das
orientações públicas, não certifica a segurança do pacote executável completo.

## Contrato implementado

- As dez páginas usam o mesmo contêiner e a mesma escala de espaçamento.
- Colunas de campos e ações usam uma grade com trilhas mínimas de 12 rem, que se reorganiza
  conforme a largura do contêiner. Métricas usam trilhas mínimas de 8 rem.
- Os sete filtros do histórico pertencem à mesma grade: as linhas compartilham larguras e
  margens. O número de colunas depende do espaço, inclusive em embedding.
- Busca/serviço no editor e no catálogo ficam lado a lado quando há espaço.
- Menu, botões, títulos, rótulos e janela de edição compartilham dimensões e espaçamentos.
- Controles nativos preservam tema, foco, estado desabilitado e semântica. CSS não muda valores,
  submissões, permissões, persistência, aprovações, chamadas AWS ou snapshots.
- Os estilos ficam restritos a contêineres FlowOps. A moldura e as margens gerais do host
  continuam sob controle do host. O canvas mantém seu próprio sistema de coordenadas.

## Validação e manutenção

`tests/test_layout.py` percorre as dez páginas por AppTest e verifica que renderizar não altera
rascunhos, versões publicadas, eventos ou execuções. O teste estrutural garante um único grupo
de sete filtros; a avaliação de pixels exige navegador real.

O teste de navegador usa desktop, tablet e celular para verificar margens, trilhas, gaps,
alvos de botões, transbordamento e contêineres internos. Capturas complementam as medições:
um teste automático não substitui julgamento visual nem prova todas as combinações de dados.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_layout.py -q
.venv/Scripts/python.exe -m scripts.browser_workspace --layout-only
# Jornada completa, seguida da inspeção responsiva:
.venv/Scripts/python.exe -m scripts.browser_workspace
```

Evidências: `browser-artifacts/workspace/layout/measurements.json` e capturas por página/largura.
O banco do teste é temporário, em modo demonstração; não usa o banco aberto na prévia do usuário.

Ao atualizar Streamlit, valide especialmente os seletores `data-testid`, o diálogo e os
controles de tabela/JSON. Não reduza as tolerâncias ocultando conteúdo. Não aplique os estilos
fora dos contêineres definidos em [DESIGN.md](../DESIGN.md).

Rollback: reverter somente os ajustes de layout e o CSS empacotado e reiniciar a aplicação.
Não exige migração nem alteração do banco; preserve as mudanças anteriores de funcionalidade.

## Evidência local — 13/09/2026

- 33 verificações de geometria aprovadas: dez páginas e diálogo de etapa em 1440, 1024 e 390 px.
- As duas jornadas Chromium passaram, incluindo aprovação manual, Lambda no backend de
  demonstração, exportação JSON/CSV e diagnóstico de falha; nenhum acesso à AWS real.
- Suíte Python: 246 testes aprovados, cinco opt-ins não executados; cobertura de 96,29%.
- Ruff, mypy, Bandit, validação do repositório e build passaram. O CSS está incluído no wheel.
- Auditoria de dependências bloqueada por certificado TLS do PyPI; CI da árvore exata não
  executada, sem publicação remota autorizada. Isso não constitui aprovação para produção.
- Não foram repetidas as integrações opt-in Docker/PostgreSQL nem a instalação completa.
  Seletores do Streamlit continuam sendo um risco de manutenção em atualizações do framework.
