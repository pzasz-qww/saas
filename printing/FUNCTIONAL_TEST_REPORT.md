# Teste funcional local — 17/10/2026

Resultado: aprovado, incluindo confirmação física do usuário de que original e reimpressão saíram legíveis e com corte automático.

Ambiente: branch prebeta4, implementação no commit 43641b7, SQLite local, Empresa A, usuário PA autenticado pelo próprio usuário. POS-80 via Windows RAW/USB, 48 colunas, CP860/tabela 3, avanço de 5 linhas e corte parcial.

## Execução pela interface

1. Preparação com backup do banco (`print_bridge/state/db-before-functional.sqlite3`), reativação temporária do produto #11 e entrada #12 com duas unidades exclusivas de teste. Impressora temporária #2 configurada com corte e geração automática de tickets.
2. No PDV, adicionada uma unidade do produto TESTE IMPRESSORA USB (NAO VENDER), comanda TESTE FUNCIONAL USB. Criado pedido #5 de R$ 0,01 como pré-venda.
3. Antes de aprovar: estoque 2, nenhum ticket do pedido #5.
4. Aprovação por Pix na interface: venda simulada #5, estoque 1 e ticket automático #2. Não ocorreu transferência financeira real.
5. Bridge consultou a API local e enviou ticket #2 à fila Windows como trabalho #4, com corte. Interface confirmou Impresso, uma tentativa.
6. Botão Reimprimir do ticket #2 criou ticket #3, referenciando o original. Bridge enviou como trabalho Windows #5, com corte. Interface confirmou Impresso, uma tentativa.
7. Usuário confirmou que os dois tickets saíram legíveis e com corte.

## Verificações

| Momento | Estoque do produto de teste |
| --- | --- |
| Antes da venda | 2 |
| Pré-venda criada | 2 |
| Venda aprovada | 1 |
| Após impressão original | 1 |
| Após reimpressão | 1 |

Os snapshots dos tickets #2 e #3 foram comparados e são idênticos. O pedido permaneceu vinculado à venda #5. Não houve nova baixa na reimpressão. Todos os demais produtos e entradas de estoque foram comparados com o backup e permaneceram intactos.

## Estado final

Impressão automática restaurada para desligada e impressora padrão restaurada ao valor anterior. Produto #11 desativado novamente, com uma unidade residual de teste. Credenciais temporárias revogadas. Pedido, venda e tickets preservados para auditoria. SaaS local mantido aberto para inspeção; nenhum bridge contínuo ficou ativo.

Nenhuma alteração de código foi necessária nesta etapa. Este relatório foi criado após o commit 43641b7 e incluído no commit documental autorizado pelo usuário. Sem push, merge ou deploy. O banco do Render utilizado no bar não foi alterado por esta etapa.

Pendências de outras etapas: configuração permanente do bridge e validação de concorrência em PostgreSQL. O teste funcional local de venda, impressão com corte e reimpressão sem nova baixa foi concluído.
