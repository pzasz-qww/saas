# Onboarding de uma empresa beta

O onboarding é interno. Não há cadastro público de empresa nesta versão.

## Antes de começar

1. Confirme que está no ambiente correto.
2. Aplique as migrations:

   ```text
   python manage.py migrate
   ```

3. Em produção, confirme que `SECRET_KEY`, `DATABASE_URL` e `ALLOWED_HOSTS`
   estão configuradas no ambiente.
4. Escolha um username e e-mail que ainda não existam.

## Criação interativa

Execute:

```text
python manage.py create_company_owner --company "Bar Aurora" --username "dono_aurora" --email "email@exemplo.com"
```

O comando solicita a senha sem exibi-la e pede confirmação. Opcionalmente, use:

```text
--document "00.000.000/0001-00" --phone "(11) 99999-9999"
```

Não passe senha como argumento de linha de comando.

## Criação não interativa

Para uma automação controlada, disponibilize a senha no secret
`BAR_SAAS_OWNER_PASSWORD` apenas durante a execução e use `--noinput`:

```text
python manage.py create_company_owner --company "Bar Aurora" --username "dono_aurora" --email "email@exemplo.com" --noinput
```

O comando falha se o secret não estiver presente. Remova a variável do processo
assim que o onboarding terminar. A senha nunca é impressa.

## O que é criado

- uma `Company` ativa;
- um `User` normal, sem acesso ao Django Admin;
- um `Profile` ligado à nova empresa, com função `owner`.

Tudo ocorre em uma única transação. Se qualquer etapa falhar, nenhum registro
parcial fica salvo. Empresa, documento, username ou e-mail já usados são
recusados; o comando nunca associa silenciosamente um novo dono a uma empresa
existente.

## Administrar pelo modo suporte

O modo suporte é restrito a usuários autenticados com `is_staff=True` ou
`is_superuser=True`. Ele não escolhe empresa automaticamente e não altera o
`Profile` do operador nem de qualquer cliente.

1. Entre com a conta interna de suporte.
2. Acesse:

   ```text
   /support/companies/
   ```

3. Localize a empresa ativa e clique em **Administrar esta empresa**.
4. Antes de alterar qualquer dado, confirme no topo:

   ```text
   ⚠ Modo suporte · Visualizando: Bar Aurora
   ```

5. Para mudar de cliente, use **Trocar empresa** e selecione a nova empresa.
6. Ao terminar, use **Sair do modo suporte** ou **Limpar empresa selecionada**.

A seleção fica apenas na sessão atual. A troca limpa estados operacionais
conhecidos, rotaciona a sessão e o token CSRF e mantém o operador autenticado.
Empresas inativas são exibidas para diagnóstico, mas não podem ser selecionadas.
Sem seleção, PDV, pedidos, estoque, equipe e impressão retornam uma tela de
bloqueio com link para o seletor.

Usuários comuns nunca veem os controles acima e recebem 403 se tentarem acessar
as rotas de suporte diretamente. A empresa deles continua vindo exclusivamente
de `request.user.profile.company`.

## Configuração inicial e validação

1. Se a empresa precisar cadastrar produtos, um superusuário deve criar ao menos
   uma `Unit` para ela no Django Admin global. Confira a empresa no formulário
   antes de salvar.
2. Entre com o novo dono.
3. Confirme no topo da tela:
   - empresa correta;
   - username correto;
   - função `Dono`.
4. Confirme que PDV, estoque, pedidos e equipe começam vazios para a nova empresa.
5. Entre com um usuário de uma empresa anterior e confirme que os dados antigos
   continuam presentes.

Se a empresa ou o usuário já existir, investigue o cadastro existente. Não
renomeie nem reaproveite registros apenas para fazer o comando passar.

## Checklist de isolamento entre empresas

Use duas empresas de teste, por exemplo Praça Kennedy e Bar Aurora:

- [ ] O dono da Praça Kennedy vê somente produtos, estoque, pedidos e equipe da
  Praça Kennedy.
- [ ] Trocar um ID na URL por um registro do Bar Aurora retorna 404/403 e não
  altera dados.
- [ ] Campos `company` ou `company_id` enviados manualmente por um usuário comum
  são ignorados.
- [ ] Um usuário comum não vê o seletor e recebe 403 nas três rotas de suporte.
- [ ] Suporte sem seleção não consegue abrir nenhuma operação empresarial.
- [ ] Após selecionar Praça Kennedy, o suporte vê somente dados da Praça Kennedy.
- [ ] Após trocar para Bar Aurora, o suporte vê somente dados do Bar Aurora.
- [ ] A troca não altera o `Profile.company` do suporte, dos donos ou dos
  funcionários existentes.
- [ ] Funcionário criado por um dono fica na empresa desse dono.
- [ ] Funcionário criado pelo suporte fica na empresa selecionada.
- [ ] Depois de sair do modo suporte, as operações voltam a ficar bloqueadas.

Finalize executando:

```text
python manage.py check
python manage.py test
```
