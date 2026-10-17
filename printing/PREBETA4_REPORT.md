# Prebeta 4 · Relatório de implementação

> Atualização em 17/10/2026: o teste USB e a simulação autorizada na Empresa A estão registrados em [USB_TEST_REPORT.md](USB_TEST_REPORT.md). Nessa etapa posterior, a migração foi aplicada ao banco local e foram criados pedido/venda de R$ 0,01 e estoque exclusivo de teste. As afirmações abaixo sobre ausência de migração e alteração de estoque descrevem o encerramento original da implementação.

## A. Base

Branch de trabalho: `prebeta4`. Base: `release/prebeta3-cloud`, commit `c319d06` (`deploy: prepara prebeta3 para cloud`), confirmada pelo usuário após a inspeção inicial. A branch local `prebeta3` apontava para `88566be`, 29 commits atrás da base consolidada escolhida. Ela não foi movida.

Estado inicial: árvore limpa, branch de origem alinhada com sua referência remota local. Não houve fetch, commit, push, merge ou deploy. A criação de `prebeta4` foi confirmada com `git branch --show-current`, `git status` e `git log -1 --oneline`.

## B. Auditoria inicial

`printing/` continha três protótipos sem vínculo com empresa: `Printer(id, name)`, `PrintSettings(id, created_at)` e `PrintJob(id, created_at)`. Havia apenas a migração `0001_initial`, registros básicos no admin, uma view protegida por login/empresa, uma rota de configurações, `AppConfig` sem sinais e três testes de acesso/empresa. Não havia services, renderer, fila, bridge, autenticação de dispositivo ou snapshots.

O template antigo estava em `templates/printing/settings.html`, fora do escopo permitido. Ele foi preservado. A nova view usa `printing/templates/printing/prebeta4/`, evitando também a precedência do diretório global de templates. O app já estava em `INSTALLED_APPS`, e `config/urls.py` já incluía suas rotas. Nenhuma alteração de configuração global foi necessária.

Uma consulta somente de leitura ao banco local confirmou **zero registros** em cada um dos três protótipos. A migração verifica isso novamente antes de substituir as tabelas vazias. Se outro ambiente tiver registros, ela interrompe sem apagá-los e exige uma decisão explícita sobre a empresa correta. A migração não oferece reversão automática que elimine os novos registros operacionais. Ela foi aplicada em bancos temporários/de teste, não no banco operacional local.

| Informação da impressão | Campo atual de origem | Existe? |
|---|---|---|
| Nome da empresa | `Company.name` | Sim |
| Número do pedido | `Order.id` | Sim; é a chave do pedido, não uma numeração independente por empresa |
| Mesa/comanda | `Order.table_or_tab` | Sim; opcional |
| Observação do pedido | `Order.notes` | Sim; opcional; criação atual do PDV não a recebe |
| Observação do item | `OrderItem.notes` | Sim; opcional; criação atual do PDV não a recebe |
| Data/hora original | `Order.created_at` | Sim; preservada, convertida para o fuso configurado no snapshot |
| Funcionário que criou | `Order.created_by` → `User` | Sim; pode ser nulo |
| Nome do funcionário | `User.get_full_name()` / `username` | Sim, como cadastro atual; não havia histórico |
| Cargo/classe | `Profile.role_template` → `StaffRole.name`, ou `Profile.role` | Existe o atual; histórico ausente na base |
| Usuário da aprovação | `Order.approved_by`, `Sale.created_by` | Sim; não substitui o autor do pedido no ticket |
| Quantidade | `OrderItem.quantity`, `SaleItem.quantity` | Sim, decimal |
| Nome do produto | `OrderItem.product.name` | Sim, como cadastro atual; não havia nome histórico |
| Preço aplicado | `OrderItem.unit_price`, `SaleItem.unit_price` | Sim, persistido |
| Total da linha | `OrderItem.total_price`, `SaleItem.total_price` | Sim, persistido |
| Total final | `Sale.total_amount`, conferido com `Order.total_amount` | Sim |
| Pagamento | `Sale.payment_method` | Sim; Dinheiro, Pix, Débito, Crédito, Outro |

## C. Arquitetura

```text
Order / OrderItem criados
   ↓ captura em memória de nome/cargo e nome do produto
   ↓ COMMIT → contextos históricos dentro de printing

Order / Sale aprovados pela operação existente
   ↓ sinal de Sale registrado no AppConfig de printing
   ↓ COMMIT DA TRANSAÇÃO COMERCIAL
   ↓ leitura de pedido/venda persistidos e conferência de valores
   ↓ snapshot imutável
PrintJob
   ↓ API autenticada com credencial de bridge
Print Bridge local
   ↓ renderer compartilhado (também usado pelo preview)
ESC/POS
   ↓ TCP configurável
Impressora
```

O serviço real de aprovação cria `Sale` e `SaleItem` e atualiza `Order` com `QuerySet.update()`, que não emite `post_save` de pedido. Por isso o disparo observa `Sale`, agenda `transaction.on_commit()` e procura o pedido vinculado **depois** do commit. Nesse momento o vínculo e os totais estão completos. Sinais repetidos convergem para a mesma chave `order:<id>:sold`.

Toda gravação da impressão ocorre depois do commit comercial. As leituras auxiliares de identidade/nome usam um savepoint próprio para impedir que uma falha de leitura contamine a transação externa. Os callbacks isolam e registram exceções. Não há conexão TCP, dependência USB, driver local ou IP privado no Django.

Limite explícito: `on_commit()` não é uma fila durável entre processos. Uma interrupção do processo entre commit e callback pode deixar a venda sem trabalho. A recuperação técnica está documentada no README do bridge, com a mesma chave idempotente. Essa entrega não faz varredura automática de vendas antigas.

## D. Arquivos estáveis

**Arquivos estáveis alterados: NENHUM.** `orders/`, `sales/`, `products/`, `accounts/`, `companies/`, `config/`, templates globais e dependências foram preservados.

Fora de `printing/`, foram criados somente os arquivos autorizados do novo bridge:

- `print_bridge/__init__.py`, `__main__.py`, `client.py`, `renderer.py`;
- `print_bridge/config.example.json`, `.gitignore`, `README.md`, `test_client.py`.

Dentro de `printing/`: models, migração, snapshots, services, queue, API, signals, AppConfig, forms, views, urls, admin, templates isolados, testes e exemplos/relatório.

O menu global não ganhou um link, pois está fora do escopo autorizado. Acesso direto: `/printing/settings/` e `/printing/jobs/`. Um favorito resolve o acesso sem alteração estável.

## E. Models

Todos possuem vínculo explícito e obrigatório com `Company`.

| Modelo | Campos principais |
|---|---|
| `Printer` | company, name, identifier UUID, active, paper_width, characters_per_line, auto_cut, created_at |
| `PrintSettings` | company única, default_printer, automatic, timezone_name, created_at |
| `PrintJob` | company, printer, order_reference, status, payload, created_at, claimed_at, printed_at, attempts, last_error, reprint_of, event_key, claimed_by, claim_token |
| `BridgeCredential` | company, printer, identifier UUID, secret_hash, active, created_at |
| `OrderPrintContext` | company, order_reference, employee_name, employee_role, created_at |
| `ItemPrintContext` | company, order_reference, item_reference, product_reference, product_name, created_at |

Status: `pending`, `processing`, `printed`, `error`. Existem constraints para evento por empresa, contextos históricos, faixa de colunas/largura e status. A fila possui índice por empresa/impressora/status/id. Relações de impressão não escrevem em pedido, venda ou estoque. As referências a pedido/item/produto são identificadores históricos; não dependem de uma consulta futura ao cadastro para reimprimir.

Configurações iniciais: 80 mm, 48 colunas, corte desativado, impressão automática desativada, fuso `America/Sao_Paulo`. Empresa e impressora são conferidas nos serviços/formulários. O admin fica somente para diagnóstico de superusuário, sem edição de snapshots ou segredos.

## F. Snapshot

O exemplo em [`examples/ticket.json`](examples/ticket.json) foi realmente produzido pelos models e pelo fluxo de aprovação, em banco temporário com dados fictícios. Não corresponde a uma venda real do bar. O script `python -m printing.examples.generate` o reproduz sem tocar no banco operacional.

```json
{
  "schema_version": 1,
  "company_name": "BAR PRAÇA KENNEDY",
  "order_number": 184,
  "sale_reference": 1,
  "ordered_at": "2026-08-27T21:42:00-03:00",
  "table": "7",
  "employee_role": "Garçom",
  "employee_name": "Pedro",
  "items": [
    {"quantity": "2.00", "name": "Heineken", "name_source": "order_item_capture", "observation": "", "unit_price": "10.00", "line_total": "20.00"},
    {"quantity": "1.00", "name": "Calabresa", "name_source": "order_item_capture", "observation": "sem cebola", "unit_price": "45.00", "line_total": "45.00"}
  ],
  "observation": "",
  "total": "65.00",
  "payment_method": "PIX",
  "payment_code": "pix",
  "missing_historical_data": []
}
```

Valores são copiados dos campos persistidos da operação; `Product.sale_price` não é usado para reconstruir a venda. A conferência entre linhas de pedido/venda verifica integridade, sem trocar os totais históricos. Mudanças posteriores em preço, nome, cargo, mesa, observação ou pagamento não alteram um snapshot já salvo. A proteção inclui `save`, `update`, `bulk_update` e upsert de campos históricos. SQL administrativo direto continua sendo acesso privilegiado ao banco, fora da API do produto.

## G. Ticket

[`examples/ticket.html`](examples/ticket.html) e [`examples/ticket.txt`](examples/ticket.txt) consomem exatamente o snapshot acima. A aparência foi conferida no navegador.

```text
               BAR PRAÇA KENNEDY
                  PEDIDO #184

27/08/2026                                 21:42
Mesa 7

Garçom: Pedro

------------------------------------------------
2x HEINEKEN                             R$ 20,00

1x CALABRESA                            R$ 45,00
   >> SEM CEBOLA <<

------------------------------------------------
TOTAL                                   R$ 65,00

Pagamento: PIX
```

A rotina de layout centraliza as colunas, alinhamento, quebra de textos longos e estilos. Todos os valores exibidos por item são totais da linha. O horário vem do pedido original, com o fuso incorporado ao payload; não é o instante da impressão.

## H. Destaques

- Cabeçalho centralizado, em negrito, com largura e altura duplas; número do pedido centralizado e em negrito.
- Produtos e totais de linha em negrito; valores alinhados à direita.
- Observações em maiúsculas, entre `>>` e `<<`, em negrito e altura dupla; texto longo é quebrado dentro da largura disponível.
- TOTAL em negrito e altura dupla, preservando a largura para não cortar o valor.
- Pagamento em negrito. Feed configurável, corte opcional e modo parcial/total configurável no bridge.

Comandos usados: `ESC @`, `ESC M`, `ESC t`, `ESC a`, `ESC E`, `GS !`, `ESC d` e, quando habilitado, `GS V`. Referências: [Epson ESC/POS](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/commands.html), [tamanho GS !](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/gs_exclamation.html), [codepage ESC t](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/esc_lt.html).

## I. Bridge

Instruções completas em [`../print_bridge/README.md`](../print_bridge/README.md). O bridge configura URL HTTPS, identificador da impressora, host/porta TCP, charset, codepage, pasta de estado, timeout, intervalo, feed e modo de corte. O exemplo `cp860`/tabela 3 vem da referência Epson e exige validação no modelo real.

A credencial própria possui segredo aleatório com hash no SaaS, vínculo com empresa/impressora, revogação e apresentação única. Sessão de funcionário não autentica a API. O bridge não tem acesso administrativo nem a APIs de venda/estoque.

Polling por POST combina busca e claim atômico. PostgreSQL utiliza lock de linha; a mudança condicional de estado impede dupla reivindicação. O retorno contém snapshot, opções e token do claim. Sucesso/erro exige a mesma credencial e o token correto. A confirmação é idempotente.

O registro local persiste antes do envio TCP. Falha ao confirmar não repete o envio físico. Reinício durante envio gera erro de resultado incerto; não há retry automático de impressão. Os trabalhos ficam visíveis na fila. “Impresso” significa envio TCP concluído; a saída física não pode ser comprovada universalmente por esse protocolo.

## J. Reimpressão

Um POST autorizado cria outro `PrintJob`, copia profundamente o payload e registra `reprint_of`. Só trabalhos finalizados (`printed` ou `error`) podem ser reimpressos. Um trabalho preso em `processing` precisa de encerramento explícito como erro, após conferência física. Uma reimpressão não reutiliza a chave do evento automático.

Não chama aprovação, cálculo de venda, baixa/reversão de estoque ou atualização de pedido. Testes comparam integralmente pedido, itens, venda, entradas e movimentos antes/depois da reimpressão e da falha do bridge. CSRF protege as operações humanas; a API de dispositivo usa exclusivamente Bearer e não aceita sessão.

Permissões: configurações/credenciais/encerramento incerto seguem `can_manage_users`; fila/preview seguem `can_view_orders_panel`; reimpressão segue `can_approve_order`. Mantidos os critérios existentes de dono e suporte com empresa explicitamente selecionada. Toda consulta operacional filtra a empresa atual.

## K. DADOS AUSENTES PARA O TICKET

| Dado/limitação | Onde era esperado | Solução nesta entrega | Arquivo estável que precisaria mudar |
|---|---|---|---|
| Cargo e nome históricos do autor em pedidos antigos | `Order`/`Profile`/`StaffRole` | Novos pedidos capturam em `OrderPrintContext`; pedidos sem captura exibem “não registrado” e sinalizam ausência | Nenhum para os novos pedidos; dados antigos não podem ser reconstruídos com certeza pelo cadastro atual |
| Nome histórico do produto em pedidos antigos | `OrderItem`/`SaleItem` | Novos itens capturam em `ItemPrintContext`; legado usa o nome disponível ao criar o snapshot, marcado `snapshot_creation` e com aviso | Nenhum para novos itens; um histórico nativo exigiria model/migração em `orders/models.py` ou `sales/models.py`, sem recuperar nomes antigos já perdidos |
| Entrada de observação no PDV | `Order.notes` e `OrderItem.notes` existem, mas não entram no fluxo de criação atual | Renderer e snapshot preservam tudo que já estiver salvo; preenchimento no PDV ficou pendente | `orders/views.py`, função `pdv`, e o template do PDV (`templates/orders/pdv.html`) |
| Mesa, pagamento, preço histórico e horário original | Models auditados | Já persistidos; nenhum campo novo nesses apps | Nenhum |

**Parte interrompida pela regra de proteção:** não foi acrescentada entrada de observações ao PDV. Uma integração exigiria validar/transportar o texto no carrinho, gravar `notes` em `pdv` e adicionar o campo no template/JavaScript do PDV. Estimativa inicial: 40–100 linhas, mais testes, dependendo do formato de observação por item/pedido. Alternativa sem alterar módulos estáveis: imprimir observações que já estejam registradas. Não houve alteração silenciosa.

Um atalho no menu também exigiria alteração opcional em `templates/includes/main_menu.html` (bloco de navegação, aproximadamente 3–6 linhas). Não foi necessário implementá-lo: as rotas diretas permitem usar todo o módulo.

## L. Testes

Os checkpoints foram executados na sequência 4A → 4B → 4C → 4D → 4E. Falhas intermediárias de testes foram corrigidas antes do encerramento de cada checkpoint (bloqueio de arquivo Windows e asserts de HTML/idioma).

| Verificação | Resultado |
|---|---|
| Novos testes | **50**, além dos 3 testes anteriores de printing |
| Camada printing + bridge | **53 testes**, 52 aprovados, 0 failures, 0 errors, 1 skip |
| Suíte completa final | **480 testes**, 470 aprovados, 0 failures, 0 errors, 10 skips; 389,733 s |
| `python manage.py check` | Sem problemas |
| `python manage.py makemigrations --check --dry-run` | No changes detected |
| `git diff --check` | Sem erros de whitespace |
| Arquivos novos ainda fora do índice | Inspeção adicional sem espaços sobrando no fim de linhas |

Os 10 skips são testes que exigem lock de linha: 9 já existentes em orders/products e 1 novo de claim. Os últimos ajustes pontuais de exibição do fuso e proteção de upsert foram conferidos também por testes focados; o renderer final foi novamente validado nos seus 6 casos. Os comandos Python usaram `venv/Scripts/python.exe` (Python 3.13.14 / Django 6.0.5), pois `python` não estava disponível no PATH da sessão. Os testes usaram banco SQLite isolado. Logs locais: `printing/test-run.log` e `printing/printing-tests.log` (ignorados pelo Git).

Cobertura nova: snapshot histórico, cargo personalizado e nome capturados antes de alterações, hora original, observações, pagamento, preço de catálogo alterado, imutabilidade, integridade de totais, idempotência, reimpressão sem efeitos comerciais, isolamento por empresa/credencial, revogação, claim, ACK repetido, rollback, erro do callback sem reversão financeira, proteção de permissões/CSRF, renderer/encoding/destaques, falha TCP, ACK perdido, reinício incerto, bloqueio do processo e transporte TCP local com porta efêmera e conferência dos bytes.

O teste real de dois consumidores está em `printing.test_queue.ClaimConcurrencyTests`. Ele é pulado em SQLite e deve rodar com `DATABASE_URL` de um PostgreSQL de teste. Não foi usada uma conexão PostgreSQL sem identificação/credenciais de teste confirmadas.

## M. Hardware

Pendente o teste físico da impressora real: IP e porta, fonte/largura útil, 42/48 colunas, `ç/ã/é`, charset/codepage, negrito, altura/largura dupla, feed, guilhotina e modos de corte, falta de papel e interrupção de rede/energia. O bridge e o comando explícito `--test-ticket` estão preparados. Nenhum envio à impressora real foi realizado.

## N. Git

Branch final: `prebeta4`, ainda no commit-base `c319d064dbff0cc8c12f76d09c16d26ed0aa7d3f`, com alterações locais não commitadas.

`git status`:

```text
On branch prebeta4
Changes not staged for commit:
  modified: printing/admin.py
  modified: printing/apps.py
  modified: printing/models.py
  modified: printing/urls.py
  modified: printing/views.py

Untracked files:
  print_bridge/
  printing/PREBETA4_REPORT.md
  printing/api.py
  printing/examples/
  printing/forms.py
  printing/migrations/0002_printing_domain.py
  printing/queue.py
  printing/services.py
  printing/signals.py
  printing/snapshots.py
  printing/templates/
  printing/test_domain.py
  printing/test_helpers.py
  printing/test_integration.py
  printing/test_queue.py
  printing/test_renderer.py
  printing/test_views.py

no changes added to commit
```

`git diff --stat` confirmado no último check:

```text
 printing/admin.py  |  54 +++++++++++-------
 printing/apps.py   |   5 +-
 printing/models.py | 162 ++++++++++++++++++++++++++++++++++++++++++++++++++++-
 printing/urls.py   |   9 ++-
 printing/views.py  | 134 +++++++++++++++++++++++++++++++++++++++++---
 5 files changed, 331 insertions(+), 33 deletions(-)
```

Arquivos novos permanecem não adicionados ao índice; por isso esse comando não contabiliza os novos arquivos listados acima. A consulta de diff fora de `printing/` e `print_bridge/` retornou vazia.

Não houve commit, push, merge ou deploy. Não houve alteração de módulo estável nem migração do banco operacional. Impressão fiscal, NFC-e/SAT, etiquetas, roteamento por setor, duas vias, receitas e alterações de estoque ficaram fora do escopo.
