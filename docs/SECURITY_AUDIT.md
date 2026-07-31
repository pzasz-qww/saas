# Auditoria de segurança multiempresa

Data da revisão: 30/07/2026  
Branch: `security`

## Regra oficial da empresa atual

Existe uma única resolução central em
`accounts.permissions.get_current_company(request)`, com duas regras distintas:

- **Usuário comum:** a empresa vem exclusivamente de
  `request.user.profile.company`.
- **Staff ou superusuário:** a empresa vem exclusivamente da chave
  `request.session["support_company_id"]`, gravada depois de uma seleção
  explícita no modo suporte.

O helper nunca consulta a primeira, a última ou uma empresa aleatória. Um
staff/superusuário sem seleção recebe `None`, mesmo que também possua `Profile`.
Da mesma forma, uma chave de suporte presente na sessão de um usuário comum é
descartada e nunca substitui `profile.company`.

Usuários sem `Profile`/empresa recebem uma resposta segura e não podem operar
PDV, produtos, estoque, pedidos, equipe ou impressão. Uma empresa com
`active=False` continua sendo identificada pelo `Profile`, mas todas as operações
ficam bloqueadas e a interface mostra o estado inativo.

No modo suporte, IDs de sessão inválidos ou de empresas removidas são apagados
sem fallback. Empresas inativas aparecem no seletor para diagnóstico, mas não
podem ser selecionadas para operação. O decorator `company_required` bloqueia a
view antes de qualquer consulta ou alteração sensível quando a empresa está
ausente ou inativa.

As rotas de suporte são:

- `GET /support/companies/`;
- `POST /support/companies/<id>/select/`;
- `POST /support/companies/clear/`.

Elas exigem autenticação e `is_staff` ou `is_superuser`. Usuários comuns recebem
403, inclusive se digitarem a URL. Selecionar e limpar exigem POST com CSRF.

Ao trocar ou limpar a seleção, estados operacionais conhecidos de carrinho,
filtros, pedidos, estoque e relatórios são removidos da sessão sem apagar as
chaves de autenticação. A chave da sessão e o token CSRF também são rotacionados,
reduzindo o risco de envio acidental de um formulário aberto para a empresa
anterior. O carrinho atual do PDV vive apenas na memória da página e é descartado
pela navegação.

O topo de todas as telas do produto identifica:

- empresa, usuário e função para usuário comum;
- ausência ou inatividade de empresa para usuário comum bloqueado;
- `Modo suporte · Nenhuma empresa selecionada` para suporte sem seleção;
- `Modo suporte · Visualizando: <empresa>` com ações de trocar/limpar quando há
  seleção.

O Django Admin é o painel global de controle, restrito a superusuários e
identificado visualmente como acesso a todas as empresas.

## Mapa de dados

### Empresa direta

- `Profile` e `StaffRole`;
- `Unit` e `Product`;
- `StockEntry` e `StockMovement`;
- `Order` e `OrderItem`;
- `Sale` e `SaleItem`.

### Empresa por relação adicional

- `Profile.role_template -> StaffRole.company`;
- `Product.unit -> Unit.company`;
- `StockEntry.product -> Product.company`;
- `StockMovement.product/stock_entry -> Product/StockEntry.company`;
- `OrderItem.order/product -> Order/Product.company`;
- `Order.sale -> Sale.company`;
- `SaleItem.sale/product -> Sale/Product.company`.

Os models acima validam que as relações redundantes pertencem à mesma empresa.
Isso impede que código interno ou o Admin grave, por exemplo, um item da Empresa
A com um produto da Empresa B.

### Sem vínculo de empresa

`Printer`, `PrintSettings` e `PrintJob` ainda são modelos vazios de um módulo em
desenvolvimento. A tela de impressão foi protegida por autenticação e empresa
atual, mas esses models não devem armazenar configuração real até receberem um
vínculo explícito com `Company`.

Não existem, nesta branch, models ou endpoints próprios de relatório financeiro.
O único relatório disponível é o PDF de estoque.

## Isolamento aplicado

- O menu global mostra empresa, usuário e função em todas as telas autenticadas
  que usam o layout da aplicação.
- Produtos, unidades, estoque e relatório de estoque partem da empresa atual.
- IDs de produto/unidade enviados em criação, entrada ou conferência são
  revalidados com a empresa atual.
- O PDV só aceita produtos da empresa atual e a criação do pedido é atômica.
- O PDV rejeita quantidade inválida, não finita, zero ou negativa; aprovação de
  venda aceita apenas as formas de pagamento definidas pelo sistema.
- Painel e detalhe de pedidos, aprovação, entrega, cancelamento, retorno ao
  estoque e descarte buscam o pedido pelo ID **e** pela empresa atual.
- Listagem, edição de perfil e permissões da equipe usam a empresa atual.
- A criação de funcionário ignora qualquer `company` recebido, usa a empresa
  atual centralizada e cria `User` + `Profile` na mesma transação. Para usuário
  comum isso significa `profile.company`; para suporte, a empresa da sessão.
- Relações sensíveis nos models rejeitam combinações entre empresas.

## Onboarding beta

O cadastro público de empresas continua desativado. Novos clientes são criados
pelo comando interno:

```text
python manage.py create_company_owner --company "Bar Aurora" --username "dono_aurora" --email "email@exemplo.com"
```

O comando cria `Company`, usuário normal e `Profile` com função `owner` em uma
transação. Ele não reaproveita registros existentes, não imprime a senha e não
altera empresas ou usuários já cadastrados. O procedimento completo está em
`docs/BETA_ONBOARDING.md`.

Depois da criação, staff/superusuário acessa `/support/companies/`, seleciona a
empresa explicitamente e confirma o aviso no topo antes de administrar seus
dados. A opção “Sair do modo suporte” remove a seleção da sessão.

## Cobertura automatizada

Os testes usam pelo menos duas empresas, usuários e dados separados e protegem:

- helper request-aware e bloqueio de usuário sem empresa/seleção;
- identificação da empresa no layout;
- 403 para usuário comum nas três rotas de suporte;
- staff e superusuário sem seleção, seleção de A, troca para B e limpeza;
- sessão inválida, empresa removida/inativa e operações que exigem POST;
- limpeza de estado operacional com preservação do login;
- ausência de alteração nos `Profile` ao trocar empresa;
- criação e atualização de equipe;
- criação de funcionário de suporte dentro da empresa selecionada;
- listagem de produtos;
- entrada, conferência e criação de produto com IDs de outro tenant;
- listagem, detalhe e todas as ações de pedido por ID;
- ausência de pedido órfão em carrinho inválido;
- bloqueio de quantidades não positivas, formas de pagamento inválidas e empresa
  inativa;
- integridade de relações de estoque, pedido e venda;
- criação do cliente beta e rollback em duplicatas.

As rotas de detalhe/edição de produto, detalhe/listagem direta de venda e
relatório financeiro ainda não existem. Por isso, o isolamento de venda é
coberto pelas ações de pedido e pelas invariantes de `SaleItem`; qualquer endpoint
novo nessas áreas deve nascer com testes HTTP de duas empresas.

## Configuração de produção

- `SECRET_KEY`, `DATABASE_URL` e `ALLOWED_HOSTS` vêm do ambiente;
- no Render, `DEBUG` fica desativado por padrão;
- host curinga é rejeitado em produção;
- PostgreSQL via `DATABASE_URL`, HTTPS, cookies seguros, HSTS e WhiteNoise são
  habilitados no modo de produção;
- `db.sqlite3`, `.env`, ambientes virtuais, `staticfiles` e bytecode estão no
  `.gitignore`.
- os 94 arquivos de `__pycache__`/bytecode que já estavam versionados foram
  removidos da árvore de trabalho para saírem do próximo commit.

A chave que existia anteriormente no histórico Git deve ser considerada
comprometida e rotacionada no ambiente de produção.

Em desenvolvimento, quando `SECRET_KEY` não está definida, o projeto usa uma
chave local fixa marcada como insegura e exclusiva para desenvolvimento. Isso
mantém sessões e tokens CSRF estáveis entre reinícios locais. Em produção, a
chave continua obrigatoriamente vindo da variável de ambiente e o fallback local
é rejeitado.

## Pendências e riscos conhecidos

- `Company.name` e `Company.document` não têm restrição única no banco. O comando
  bloqueia duplicatas normais, mas uma garantia contra duas execuções realmente
  simultâneas exigirá um identificador único definido pelo negócio.
- Todo usuário com `is_staff=True` recebe poder global de suporte, conforme a
  regra do beta. Depois do beta, recomenda-se substituir esse critério por grupo
  ou permissão dedicada e revisar todos os usuários staff existentes.
- A seleção de suporte pertence à sessão e é compartilhada entre abas. A rotação
  de sessão/CSRF e os filtros por empresa reduzem o risco de abas antigas, mas o
  operador ainda deve conferir o aviso no topo antes de qualquer ação.
- A seleção temporária não possui trilha de auditoria persistente. Se o modo
  suporte permanecer após o beta, registrar operador, empresa, horário e motivo.
- O módulo de impressão precisa receber `company` antes de deixar de ser
  protótipo.
- Ainda faltam endpoints de vendas e relatório financeiro; quando criados,
  deverão filtrar `Sale.objects.filter(company=get_current_company(request))`
  e proteger cada ID com o mesmo escopo.
- O banco SQLite local apresentou histórico de migrations aplicadas que não
  existe nesta branch. Ele não deve ser usado como fonte de schema nem ser
  commitado; ambientes novos devem ser construídos somente com migrations
  versionadas e validadas.
