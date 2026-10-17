# Print Bridge · Prebeta 4

Cliente local independente do Django, em Python 3.11 ou superior, usando somente a biblioteca padrão. TCP funciona em Windows 11 ou Linux. No Windows, o transporte `windows_raw` envia os mesmos bytes ESC/POS pela fila instalada, inclusive USB. O computador precisa alcançar o SaaS; não é necessário abrir uma porta de entrada no computador do bar.

## Impressora USB no Windows

Use `config.windows.example.json` como base. Configure `transport: "windows_raw"` e `printer_name` com o nome exato da fila (neste computador, `POS-80`, porta `USB002`, driver `POS-80 11.3.0.1`). Host e porta TCP ficam sem uso. Não é necessário trocar o driver nem compartilhar a impressora.

O transporte usa `OpenPrinterW`, `StartDocPrinterW` com tipo `RAW`, `WritePrinter` e `EndDocPrinter`. Escritas parciais são completadas; falhas encerram o documento atual. Nenhum job de outra aplicação é cancelado. Referência: [envio RAW pela API do Windows](https://learn.microsoft.com/en-us/windows/win32/printdocs/sending-data-directly-to-a-printer).

Sucesso significa **aceitação pela fila Windows**, não confirmação física de papel. A fila pode continuar tentando imprimir se o equipamento ficar offline. Antes de reimprimir um resultado incerto, confira também a fila POS-80 para não duplicar um trabalho ainda aguardando saída. Não apague o registro local do bridge para forçar reenvio.

O exemplo `cp860`/tabela 3 continua experimental até conferir os acentos no equipamento real. O primeiro teste é enviado sem corte.

## Preparação

1. Após revisar a implementação, aplicar a migração de `printing` no ambiente escolhido: `python manage.py migrate printing`. A migração para se houver protótipos antigos sem empresa; não atribui uma empresa por adivinhação e não apaga esses registros.
2. Entrar no SaaS com um dono ou usuário autorizado a gerenciar equipe. Abrir `/printing/settings/`, cadastrar a impressora, escolher a impressora padrão e habilitar a impressão automática quando estiver pronta para uso.
3. Copiar o identificador da impressora. Gerar uma credencial de bridge: ela aparece uma única vez. Gerar outra revoga a anterior. Não fazer essa troca enquanto houver confirmação pendente no bridge.
4. Copiar `print_bridge/config.example.json` para `print_bridge/config.local.json`. Preencher a URL do SaaS (HTTPS em nuvem), identificador, IP/host e porta reais da impressora. `9100` é apenas exemplo; a porta é configurável.
5. Definir `encoding` e `codepage` conforme o manual do modelo real. `cp860` e `3` são um exemplo documentado para a tabela portuguesa Epson, não uma detecção do equipamento. [Referência Epson: ESC t](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/esc_lt.html).
6. Definir `PRINT_BRIDGE_TOKEN` no ambiente do processo local. O segredo não fica no JSON de configuração nem no repositório. O SaaS guarda apenas um hash, associado à empresa e à impressora. Restringir o ambiente/pasta de estado ao usuário que executa o bridge.

Execute da pasta que contém `print_bridge/`:

```powershell
python -m print_bridge --config print_bridge/config.local.json
```

O mesmo comando funciona no Linux. Para instalação independente, copie a pasta `print_bridge/` para o computador do bar; o código Django não é necessário. Execute a partir da pasta pai. A pasta de estado deve ser persistente e exclusiva para esse bridge. Um bloqueio de arquivo impede dois processos de usarem a mesma pasta simultaneamente.

`--once` processa um trabalho, ou uma confirmação pendente, e termina. Use Agendador de Tarefas no Windows ou um serviço do sistema no Linux somente quando o teste manual estiver concluído. Esta entrega não instala serviços nem tarefas agendadas.

## Configuração

| Campo | Uso |
|---|---|
| `server_url` | URL base do SaaS; HTTPS, exceto localhost para desenvolvimento |
| `printer_identifier` | UUID da impressora mostrado no SaaS |
| `host`, `port` | Endereço local e porta TCP reais |
| `encoding` | Codec Python de byte único, confirmado no manual |
| `codepage` | Número de tabela enviado por `ESC t`, confirmado no manual |
| `state_directory` | Pasta persistente do registro de envio/confirmação |
| `token_env` | Nome da variável com o segredo; padrão `PRINT_BRIDGE_TOKEN` |
| `poll_seconds` | Intervalo entre consultas; padrão 2 s |
| `timeout_seconds` | Timeout de HTTP/TCP; padrão 10 s |
| `feed_lines` | Avanço final; padrão 4 linhas |
| `cut_mode` | `partial` ou `full`; usado apenas quando o corte está habilitado |

Largura em mm, caracteres por linha e habilitação de corte vêm da configuração da impressora no SaaS. O corte inicia desativado. A largura em mm é informativa: a quantidade de colunas/fontes precisa ser calibrada para a largura imprimível real do equipamento.

## Fila e recuperação

O bridge usa `Authorization: Bearer <identificador>.<segredo>`, exclusivamente nos dois endpoints:

- `POST /printing/api/v1/jobs/claim/`: encontra e reivindica atomicamente o próximo trabalho da própria impressora/empresa. Resposta `{"job": null}` significa fila vazia ou impressora desativada. A reivindicação e a leitura são uma operação única.
- `POST /printing/api/v1/jobs/<id>/result/`: envia `claim_token`, `status` (`printed` ou `error`) e `error` quando necessário. Só a credencial dona do claim pode confirmar. Repetir a mesma confirmação é idempotente.

O claim usa lock de linha no PostgreSQL e uma atualização condicional de `pending` para `processing`. Dois consumidores não recebem o mesmo trabalho. Não existe expiração automática que devolva um trabalho ao estado pendente.

Antes do TCP, o bridge grava `pending.json` com estado `sending`. Depois do envio, grava `printed` ou `error` e confirma no SaaS. Se a confirmação HTTP falhar, repete apenas a confirmação. Se reiniciar com `sending`, informa resultado incerto e não repete o envio TCP. Uma falha no socket pode ter ocorrido depois de enviar parte ou todo o ticket.

Se a resposta ao próprio claim se perder antes de chegar ao bridge, o trabalho permanece `processing` no SaaS. Na lista de trabalhos, um gestor pode encerrar como erro após parar o bridge e conferir o papel. A reimpressão é sempre explícita e cria outro trabalho com o mesmo snapshot. Nunca alterar/apagar a pasta de estado para tentar resolver uma impressão incerta.

`printed` significa que `sendall()` concluiu, não prova física de saída de papel. ESC/POS TCP não fornece confirmação universal de impressão física. Falta de papel, equipamento desligando após receber bytes ou guilhotina defeituosa ainda exigem conferência.

Se o processo Django morrer entre o commit comercial e a execução de `on_commit`, um trabalho pode não ser criado. O callback não é uma fila durável. Falhas são registradas no logger `printing.signals`; não desfazem a venda. A recuperação técnica pode chamar `printing.services.enqueue_order(order_id=..., company_id=...)` novamente, com impressão automática habilitada. A chave de evento impede duplicidade; valores vêm dos campos históricos persistidos. Não há varredura automática de vendas antigas nesta fase.

## Preview e teste físico posterior

Preview local, sem fila e sem conexão com impressora:

```powershell
python -m print_bridge --config print_bridge/config.local.json --preview printing/examples/ticket.json --columns 48
```

Envio manual explícito de teste, inicialmente sem corte:

```powershell
python -m print_bridge --config print_bridge/config.local.json --test-ticket printing/examples/ticket.json --columns 48
```

Para testar guilhotina, repetir esse comando acrescentando `--cut`. O modo vem de `cut_mode`. Esses comandos locais não criam nem confirmam `PrintJob`.

Validar no equipamento: texto, `ç`, `ã`, `é`, `Garçom`, `PRAÇA`, alinhamento à direita, 42/48 colunas conforme manual, negrito, tamanho duplo, feed, corte parcial/total, porta/IP, papel e desligamento durante envio. Conteúdo não representável no charset provoca erro antes de abrir a conexão; não é substituído silenciosamente.

## Testes

Sem Django: `python -m unittest discover -s print_bridge -t .`.

No projeto: `python manage.py test printing print_bridge`.

Para o teste concorrente real, configurar `DATABASE_URL` de um PostgreSQL **de teste** com permissão para criar seu banco de teste e executar `python manage.py test printing.test_queue.ClaimConcurrencyTests`. SQLite pula esse caso por não representar `SELECT FOR UPDATE`.

Referências dos comandos: [negrito ESC E](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/esc_ce.html), [dimensões GS !](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/gs_exclamation.html), [corte GS V](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/gs_cv.html). Cada modelo pode suportar variações; conferir o manual da impressora real.
