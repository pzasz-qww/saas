# Teste USB — 17/10/2026

Ambiente: banco SQLite local, Empresa A. Impressora Baisec GS-80MM, fila Windows POS-80, USB002, driver POS-80 11.3.0.1. Transporte Windows RAW; 48 colunas; CP860/tabela 3; corte desligado.

O primeiro ticket manual teve saída física, acentos e alinhamento confirmados pelo usuário. O usuário também confirmou que o ticket integrado do pedido #4, Empresa A, total R$ 0,01, saiu completo e legível na POS-80. Teste integrado USB concluído com confirmação física.

## Resultado integrado

- Pedido #4 e venda #4: R$ 0,01, pagamento registrado como pix apenas para simulação local; nenhuma transferência financeira foi realizada pelo roteiro.
- Produto #11: TESTE IMPRESSORA USB (NAO VENDER), desativado após a simulação.
- Entrada de estoque #11: uma unidade criada para o teste, saldo consumido de 1 para 0.
- Ticket #1 criado automaticamente após aprovação da venda; uma tentativa; estado `printed` após confirmação do bridge pela API.
- Consulta/claim e confirmação HTTP: ambas retornaram 200.
- Windows recebeu trabalho #2, documento Prebeta 4 - ticket ESC/POS. Na consulta seguinte ainda constava na fila com estado Normal; posteriormente o usuário confirmou a saída física completa e legível. Não houve reenvio.
- Impressão automática restaurada para desligada; credencial temporária revogada; servidor local temporário encerrado.
- Registros da simulação permanecem no banco local para auditoria, inclusive a venda de R$ 0,01.

## Segurança dos dados e preparação

Backup SQLite antes da migração: `print_bridge/state/db-before-usb-20261017-024809.sqlite3`.
Backup adicional antes da criação dos registros: `print_bridge/state/db-before-usb-20261017-024819.sqlite3`.
Migração `printing.0002_printing_domain` aplicada ao banco local.
A primeira execução do roteiro falhou por usar inteiro em um campo que exige Decimal; a transação de criação foi revertida. Corrigido o roteiro, a execução seguinte concluiu sem duplicar pedido ou venda.
Resultado estruturado: `print_bridge/state/local-usb-result.json` (arquivo local ignorado pelo Git).

## Testes automatizados

Suíte focada printing + print_bridge após adicionar Windows RAW: 58 testes, 57 aprovados e 1 ignorado por depender de PostgreSQL. Log: `printing/usb-tests.log`.
Verificação de whitespace: sem erros. A suíte geral anterior à extensão USB teve 480 testes, 470 aprovados e 10 ignorados; não foi repetida nesta etapa.

## Pendências

Teste de corte enviado em 17/10/2026: um ticket identificado como TESTE CORTE USB, via bridge Windows RAW, 48 colunas, CP860/tabela 3, avanço de 5 linhas e corte parcial ativado apenas nesse envio. Aceito pelo Windows como trabalho #3. O usuário confirmou a impressão e o corte automático, deixando apenas um pequeno ponto preso, conforme o modo parcial. Não houve criação de venda, alteração de estoque ou ativação permanente do corte.

1. Executar teste funcional pela interface na Empresa A.
2. Para uso contínuo, informar a URL do SaaS e configurar credencial própria; a credencial temporária deste teste foi revogada.
3. Validar concorrência com PostgreSQL no ambiente apropriado.

Os testes físicos foram realizados sem commit, push, merge ou deploy. Após confirmar o corte, o usuário autorizou o commit da implementação. Push, merge e deploy continuam fora do escopo. Alterações de código restritas a printing/ e print_bridge/.
