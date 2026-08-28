# Teste manual — Praça PDV Portable

Este roteiro valida a prova de conceito local no Windows sem alterar o banco do
SaaS Cloud. Use uma rede privada e mantenha o computador ligado durante os
testes.

## Preparação inicial

1. Instale as dependências no ambiente local:

   ```powershell
   .\venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Execute `iniciar_pdv.bat`.
3. Na primeira execução, o launcher criará `data/`, `media/`, `logs/`,
   `backups/` e a chave local em `config/portable_secret_key.txt`.
4. Se o Windows Defender Firewall solicitar acesso, selecione somente
   **Redes privadas**. Não permita em redes públicas.

## Teste 1 — inicialização

Execute:

```text
iniciar_pdv.bat
```

Resultado esperado:

- migrations aplicadas sem erro;
- mensagem `Status: ONLINE`;
- URL local e, quando detectável, URL da rede local;
- navegador aberto somente depois de o servidor responder.

Para testar inicialização e HTTP sem deixar o servidor aberto:

```powershell
.\iniciar_pdv.bat --smoke-test
```

Resultado esperado: `Smoke test HTTP concluído com sucesso.`

## Teste 2 — acesso no computador

Acesse:

```text
http://127.0.0.1:8000
```

Resultado esperado: redirecionamento para a tela de login.

## Teste 3 — primeiro proprietário em um banco vazio

Uma cópia portátil recém-criada não possui usuários. Depois da primeira
execução do launcher, encerre-o com `Ctrl+C` e, no PowerShell aberto na pasta do
projeto, execute:

```powershell
$env:DEPLOYMENT_MODE = "portable"
$env:PORTABLE_ROOT = (Get-Location).Path
$env:SECRET_KEY = (Get-Content .\config\portable_secret_key.txt -Raw).Trim()
.\venv\Scripts\python.exe manage.py create_company_owner --company "Meu Bar" --username "proprietario" --email "proprietario@example.com"
```

Digite e confirme uma senha forte quando solicitado. Em seguida, remova as
variáveis apenas dessa sessão do PowerShell ou feche a janela.

## Teste 4 — fluxo funcional mínimo

Inicie novamente por `iniciar_pdv.bat` e valide:

1. login;
2. abertura do PDV;
3. criação ou consulta de produto;
4. entrada de estoque e criação dos lotes;
5. abertura de pré-venda;
6. aprovação da venda;
7. baixa de estoque e custos/FIFO esperados;
8. conferência e relatórios locais existentes.

Resultado esperado: o comportamento deve ser o mesmo da Prebeta 3, usando
exclusivamente `data/db.sqlite3`.

## Teste 5 — acesso por celular ou tablet

1. Conecte o aparelho à mesma rede Wi-Fi/LAN do computador.
2. Use exatamente a URL `Na rede local` exibida pelo launcher, por exemplo:

   ```text
   http://192.168.0.105:8000
   ```

3. Faça login e consulte o PDV.

Se não abrir, confirme que a rede do Windows está marcada como privada, que o
aparelho não está em uma rede de convidados com isolamento e que o firewall
permitiu o Python somente na rede privada.

## Teste 6 — operação sem internet

1. Mantenha o Wi-Fi ou cabo de rede local conectado.
2. Desconecte a internet do roteador.
3. Repita o acesso no computador e no celular.
4. Faça uma operação de leitura e uma de gravação.

Resultado esperado: login, produtos, estoque, pedidos e vendas continuam
operando. O IP local pode mudar se o roteador reiniciar; nesse caso, reinicie o
launcher e use o novo endereço exibido.

## Encerramento seguro

Pressione `Ctrl+C` na janela do launcher e aguarde a mensagem de encerramento.
Não remova o pendrive ou a pasta sincronizada enquanto o processo estiver em
execução. O diretório `backups/` está reservado para a próxima fase; nesta prova
de conceito, faça cópias de `data/db.sqlite3` apenas com o servidor parado.

## Limitações conhecidas

- SQLite permite múltiplas leituras, mas tem capacidade limitada para escritas
  simultâneas; evite grande concorrência nesta prova de conceito.
- Não há sincronização com o SaaS Cloud, autoatualização, instalador, serviço do
  Windows ou backup automático.
- O acesso é HTTP dentro da LAN privada. Não exponha a porta 8000 à internet.
- VPNs e múltiplos adaptadores podem fazer o launcher escolher um IP diferente
  do Wi-Fi principal; use `ipconfig` para conferir o IPv4 se necessário.
