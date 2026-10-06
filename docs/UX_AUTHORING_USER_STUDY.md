# Avaliação da autoria visual com participantes

Estado: roteiro preparado em 16/09/2026. O responsável confirmou disponibilidade de participantes; ainda não há resultados coletados. Os testes automatizados não contam como participantes.

## Preparação

Selecione cinco pessoas técnicas (T01–T05) e cinco não técnicas (N01–N05). Use esses identificadores no registro, sem nomes ou dados pessoais. Reserve 30–45 minutos por pessoa e registre a versão/commit avaliado. Colete consentimento para observação; gravação de tela é opcional e depende de consentimento específico.

Use uma instância DEMO e banco descartável separados da operação. Confirme na interface: Demonstração, conta 000000000000 e Desenvolvimento. Não configure credenciais reais. Cada participante recebe seu próprio rascunho; o aprovador é outra pessoa quando a política exige separação.

Dados fictícios: tabela `payments`, chave textual `paymentId`, valor `12345`, função `payment-processor`, status `PROCESSING`. No editor novo, a biblioteca e a lista de etapas ficam à esquerda, o grafo no centro e o inspetor à direita. O assistente de criação fica em Procedimentos → Criar por objetivo.

## Tarefas (entregue uma por vez)

1. Crie um procedimento para consultar um pagamento e enviá-lo a uma Lambda após aprovação. Explique a diferença entre consulta por partição, leitura de um item e varredura.
2. Faça o identificador do pagamento ser informado na execução. Crie um parâmetro a partir de um campo existente, mantendo seu valor atual como padrão.
3. Filtre os registros por status e renomeie os campos do evento. Acrescente uma propriedade ao payload e uma estrutura aninhada, usando a interface.
4. Altere o nome de uma etapa no novo canvas. Desfaça e refaça a edição. Explique onde os dados estão salvos em cada momento.
5. Use a origem de dados para preencher um campo. Identifique uma referência inválida preparada pelo facilitador e corrija-a pela revisão contextual.
6. Revise, salve e publique. Inicie uma simulação e depois uma execução efetiva em DEMO. Explique por que só a segunda pede decisão humana.
7. Encontre a aprovação pendente, explique destino e dados envolvidos e conclua a decisão autorizada.
8. Inspecione o resultado da etapa correta e exporte JSON/CSV. Diferencie o resultado da Lambda de um simples aceite assíncrono.
9. Repita criar/conectar/configurar/revisar usando apenas teclado. Registre controles que não conseguiu alcançar ou identificar.

Na tarefa 5, prepare a referência quebrada somente em um rascunho de teste; nunca altere uma publicação ou execução histórica. A comparação de interfaces pode usar o canvas anterior e o novo com tarefas equivalentes, alternando a ordem entre participantes para reduzir o efeito de aprendizado.

## Conduta do facilitador

Peça que a pessoa verbalize o que procura e o que espera que aconteça. Não ensine os controles antes da tentativa. Registre o pedido de ajuda e o momento; depois ajude se necessário para permitir a próxima tarefa. Uma tarefa concluída com ajuda não é conclusão sem ajuda.

Registre por tarefa: perfil, interface, conclusão sem ajuda/com ajuda/não concluída, duração em segundos, número de intervenções, erros recuperados, abandono e necessidade de JSON/expressão. Anote a dificuldade de forma concreta (controle, ação tentada, resultado), evitando avaliações genéricas como “ruim”.

## Ficha de coleta

Copie esta ficha para cada participante:

```text
Participante: T01 ou N01
Commit/versão:
Interface e ordem da comparação:
Tarefa | Conclusão | Segundos | Ajudas | Erros recuperados | JSON/expressão necessária | Observação
1      |           |          |        |                   |                          |
2      |           |          |        |                   |                          |
3      |           |          |        |                   |                          |
4      |           |          |        |                   |                          |
5      |           |          |        |                   |                          |
6      |           |          |        |                   |                          |
7      |           |          |        |                   |                          |
8      |           |          |        |                   |                          |
9      |           |          |        |                   |                          |
Distinguiu Demonstração / Simulação / AWS real antes de executar? sim/não
Houve perda de rascunho? sim/não; reprodução:
Principal dificuldade:
Principal melhoria percebida:
```

## Decisão com evidência

Metas propostas pelo plano: pelo menos 8/10 concluem a configuração sem ajuda; zero JSON/expressões manuais nos casos suportados; zero perda de rascunho; 10/10 distinguem demonstração, simulação e execução real. Apresente os resultados por perfil. Compare tempos apenas quando houver uma linha de base real com tarefa equivalente. A amostra é qualitativa, não uma prova estatística de adoção.

Classifique obstáculos encontrados, corrija os de maior impacto e repita as tarefas afetadas. A onda 4 deve receber prioridades dessas observações. Este documento, sozinho, não aprova as metas nem certifica conclusão do estudo.
