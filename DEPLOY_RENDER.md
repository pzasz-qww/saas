# Deploy da Prebeta 3 no Render

Esta branch prepara o Praça PDV para um serviço web Python com PostgreSQL. Ela
não publica o sistema automaticamente e não contém credenciais reais.

## Caminho recomendado: Blueprint

1. No Render, crie um Blueprint apontando para o `render.yaml` da raiz.
2. Revise os nomes, a região e os planos antes de confirmar a criação.
3. O Blueprint cria um PostgreSQL, injeta `DATABASE_URL`, gera `SECRET_KEY` e
   inicia o serviço com `gunicorn config.wsgi:application`.
4. Acompanhe o primeiro build e confirme que `collectstatic` e `migrate`
   terminam sem erro.

O `build.sh` mantém as migrations no build para ser compatível com a
configuração simples do Render. Em uma operação com várias instâncias, mova
`python manage.py migrate` para `preDeployCommand` e remova essa linha do
script de build, evitando execuções concorrentes.

## Configuração manual ou plataforma equivalente

Comandos:

```text
Build: ./build.sh
Start: gunicorn config.wsgi:application
```

Variáveis:

| Variável | Obrigatória | Uso |
| --- | --- | --- |
| `DEPLOYMENT_MODE=cloud` | Sim | Ativa as proteções de produção. |
| `DATABASE_URL` | Sim | Conexão PostgreSQL completa, fornecida pela plataforma. |
| `SECRET_KEY` | Sim | Valor secreto, exclusivo e com pelo menos 50 caracteres. |
| `DEBUG=false` | Recomendado | Em cloud o código força `False`, mesmo se outro valor for informado. |
| `PYTHON_VERSION=3.13.14` | Recomendado | Reproduz a versão usada na homologação desta release. |
| `ALLOWED_HOSTS` | Fora do Render | Lista de hosts separados por vírgula. Nunca use `*`. |
| `CSRF_TRUSTED_ORIGINS` | Quando houver domínio/proxy adicional | Origens HTTPS completas, separadas por vírgula. |

O Render fornece `RENDER_EXTERNAL_HOSTNAME`; o sistema inclui esse hostname em
`ALLOWED_HOSTS` e sua origem HTTPS em `CSRF_TRUSTED_ORIGINS`. Domínios
personalizados ainda devem ser adicionados explicitamente às duas variáveis.
O Blueprint fixa Python 3.13.14 para não depender da versão padrão mutável da
plataforma.

## Primeiro acesso

Nenhum usuário ou superusuário é criado no build.

Para criar a primeira empresa e o proprietário operacional, abra o Shell do
serviço e execute:

```text
python manage.py create_company_owner --company "Nome do bar" --username proprietario --email dono@exemplo.com
```

A senha será pedida sem aparecer na tela. Como alternativa não interativa,
defina temporariamente `BAR_SAAS_OWNER_PASSWORD` no ambiente do comando e use
`--noinput`; remova a variável em seguida.

Para acesso somente ao Django Admin, também é possível executar:

```text
python manage.py createsuperuser
```

Um superusuário do Django sem empresa/perfil não substitui o proprietário
operacional do Praça PDV.

## Arquivos estáticos e mídia

WhiteNoise serve os arquivos estáticos gerados por `collectstatic`. O projeto
possui `MEDIA_ROOT` e `MEDIA_URL`, mas atualmente os modelos e fluxos principais
não recebem uploads persistentes. Se uploads forem adicionados, o filesystem
efêmero da cloud não deve ser usado como armazenamento definitivo; configure
um serviço externo compatível com S3.

## Verificação antes do deploy

Use um PostgreSQL descartável, nunca o banco operacional do bar, e valide:

```text
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py collectstatic --no-input
python manage.py migrate
python manage.py test
```

Com `DEPLOYMENT_MODE=cloud`, defina também `DATABASE_URL`, uma `SECRET_KEY`
forte, `ALLOWED_HOSTS` e, para acesso HTTP local sem redirecionamento, use um
proxy que envie `X-Forwarded-Proto: https` ou faça apenas a checagem de
configuração. O serviço real no Render recebe esse cabeçalho no proxy HTTPS.
