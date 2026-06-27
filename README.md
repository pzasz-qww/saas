# 🍻 SaaS de Gestão para Bares

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

- SQLite (desenvolvimento)

Planejamento futuro:

- PostgreSQL (produção)

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