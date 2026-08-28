# SaaS de Gestão para Bares

Sistema web desenvolvido em Django para gerenciamento operacional de bares, com foco em controle de estoque, vendas, financeiro e operação diária.

O projeto está sendo desenvolvido e validado em ambiente real utilizando o **Bar Praça Kennedy**, permitindo que todas as funcionalidades sejam testadas antes da comercialização.

---

# Objetivo

Criar uma plataforma SaaS moderna para pequenos e médios bares, oferecendo uma solução completa para:

- Controle de estoque
- Registro de vendas
- Gestão financeira
- Relatórios
- Controle operacional
- Futuramente multiempresa (Multi-Tenant)

---

# Tecnologias

## Backend

- Python
- Django

## Frontend

- HTML
- CSS
- JavaScript

## Banco de Dados

- PostgreSQL (SaaS Cloud)
- SQLite (desenvolvimento e prova de conceito portátil)

---

# Funcionalidades

## Autenticação

- Login
- Logout
- Controle de acesso

---

## Produtos

- Cadastro
- Edição
- Exclusão
- Categorias

---

## Estoque

- Controle de quantidade
- Entrada de produtos
- Ajustes manuais
- Conferência de estoque

---

## Vendas

- Registro de vendas
- Baixa automática do estoque
- Histórico de vendas

---

## Financeiro

- Registro de faturamento
- Controle financeiro básico
- Indicadores operacionais

---

# Fluxo do Sistema

Cadastro de Produto

↓

Entrada no Estoque

↓

Venda

↓

Baixa Automática

↓

Atualização Financeira

↓

Histórico

---

# Estrutura do Projeto

```
projeto/
│
├── accounts/
├── estoque/
├── vendas/
├── financeiro/
├── templates/
├── static/
├── media/
├── manage.py
└── requirements.txt
```

---

# Roadmap

## Versão Atual

- [x] Sistema de login
- [x] Controle de estoque
- [x] Movimentação de estoque
- [x] Sistema de vendas
- [x] Baixa automática do estoque
- [x] Controle financeiro
- [x] Histórico de vendas

---

## Próxima Sprint

- [ ] Responsividade Mobile
- [ ] Dashboard Mobile
- [ ] Conferência Mobile
- [ ] Vendas Mobile
- [ ] Melhorias de UX

---

## Próximas Funcionalidades

- [ ] Dashboard gerencial
- [ ] Alertas de estoque
- [ ] Controle de perdas
- [ ] Consumo interno
- [ ] Cortesias
- [ ] Backup automático
- [ ] Controle de permissões

---

## Longo Prazo

- [ ] Multiempresa (SaaS)
- [ ] Assinaturas
- [ ] PDV completo
- [ ] Gestão financeira avançada
- [ ] Compras
- [ ] Fornecedores
- [ ] Delivery
- [ ] API pública
- [ ] Aplicativo Mobile

---

# Ambiente de Desenvolvimento

Clone o projeto:

```bash
git clone https://github.com/SEU-USUARIO/SEU-REPOSITORIO.git
```

Entre na pasta:

```bash
cd projeto
```

Crie um ambiente virtual:

```bash
python -m venv venv
```

Ative:

Windows

```bash
venv\Scripts\activate
```

Linux

```bash
source venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Execute as migrações:

```bash
python manage.py migrate
```

Inicie o servidor:

```bash
python manage.py runserver
```

---

# Modos de execução

O mesmo código atende aos ambientes de desenvolvimento, SaaS Cloud e portátil.
As regras de empresa, usuários, estoque, lotes, FIFO, pedidos e vendas são
compartilhadas entre todos os modos.

## SaaS Cloud

O Render continua compatível com as variáveis existentes. Também é possível
declarar o modo explicitamente:

```text
DEPLOYMENT_MODE=cloud
```

Em cloud, `DEBUG` permanece desligado e as variáveis `SECRET_KEY`,
`DATABASE_URL` (PostgreSQL) e `ALLOWED_HOSTS` são obrigatórias. O fluxo de build
continua sendo o definido em `build.sh`.

## Praça PDV Portable (Windows)

Instale as dependências uma vez no ambiente que será distribuído:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Depois, dê dois cliques em:

```text
iniciar_pdv.bat
```

O launcher usa Waitress em `0.0.0.0:8000`, aplica migrations, prepara os
arquivos estáticos, abre o navegador somente após o servidor responder e exibe
o IP para acesso por outros aparelhos da mesma rede. A porta e a abertura do
navegador podem ser alteradas copiando `config/portable.env.example` para
`config/portable.env`.

Os dados portáteis ficam relativos à pasta do launcher:

```text
data/db.sqlite3
static/
media/
logs/
backups/
config/portable_secret_key.txt
```

Nenhuma letra de unidade ou pasta de usuário é gravada na configuração. O
launcher também reconhece o futuro layout de distribuição em que o código fica
em `app/`, sem exigir uma segunda versão do projeto.

Para um teste automatizado de inicialização e resposta HTTP:

```powershell
.\iniciar_pdv.bat --smoke-test
```

O núcleo não faz chamadas externas e continua funcionando quando a internet é
desconectada, desde que a rede local permaneça ativa. SQLite é apenas a prova de
conceito inicial: vários terminais podem acessar o servidor, mas escritas muito
concorrentes podem encontrar contenção no banco.

O roteiro manual completo está em `PORTABLE_TEST.md`.

---

# Filosofia do Projeto

Este sistema está sendo desenvolvido utilizando um ambiente operacional real.

Cada funcionalidade é implementada para resolver problemas encontrados na rotina diária de um bar, tornando a plataforma prática, intuitiva e preparada para crescimento.

---

# Status

🚧 Em desenvolvimento ativo.

Primeiro ambiente de validação:

**Bar Praça Kennedy**

---

# Autor

Pedro

Desenvolvido com foco em criar uma plataforma moderna de gestão para bares.
