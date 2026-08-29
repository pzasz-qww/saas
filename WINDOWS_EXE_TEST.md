# Homologação — PracaPDV.exe no Windows 11

Este roteiro valida o executável autocontido em uma máquina Windows 11 x64 sem
Python instalado. Faça a homologação em uma pasta nova, sem copiar `data/` ou
`config/` do ambiente de desenvolvimento.

## 1. Conferir a distribuição

A pasta entregue deve conter:

```text
PRACA_PDV_PORTABLE/
├── PracaPDV.exe
└── LEIA-ME-EXECUTAVEL.txt
```

Coloque a pasta na Área de Trabalho, em Documentos ou em um pendrive gravável.
Não use `C:\Program Files`, pois o sistema precisa criar dados ao lado do EXE.

## 2. Smoke test automatizado

Abra o PowerShell na pasta e execute:

```powershell
.\PracaPDV.exe --smoke-test
```

Resultado esperado:

- criação dos diretórios portáteis;
- migrations aplicadas em `data/db.sqlite3`;
- tela de login e CSS respondendo por HTTP;
- host do IP LAN aceito;
- mensagem `Smoke test HTTP concluído com sucesso`;
- encerramento automático com código zero.

Apague as pastas geradas pelo smoke test antes de validar a primeira execução,
ou teste a primeira execução em outra cópia limpa da distribuição.

## 3. Primeira execução e proprietário

1. Dê dois cliques em `PracaPDV.exe`.
2. Informe estabelecimento, usuário e e-mail.
3. Digite e confirme uma senha forte; ela não aparece na tela.
4. Aguarde `Configuração inicial concluída com sucesso`.
5. Aguarde `Status: ONLINE` e a abertura do navegador.
6. Entre com o proprietário criado.

Resultado esperado: o assistente aparece somente enquanto o banco não possui
usuários.

## 4. Persistência após reinício

1. Cadastre um produto de teste.
2. Encerre o servidor com `Ctrl+C`.
3. Inicie novamente pelo mesmo EXE.
4. Faça login e consulte o produto.

Resultado esperado: nenhum assistente de primeiro uso e dados preservados em
`data/db.sqlite3`.

## 5. Fluxo operacional

Valide login, produtos, entrada de estoque, lotes, FIFO, pré-venda, aprovação,
baixa de estoque, reversão e conferência. O comportamento deve permanecer igual
à Prebeta 3 e isolado por empresa.

## 6. Acesso pela LAN

1. Permita o executável somente em redes privadas no Firewall do Windows.
2. Conecte celular e computador à mesma rede.
3. Abra no celular a URL exibida em `Na rede local`.
4. Faça login e execute uma leitura e uma gravação.

Não permita em redes públicas e não encaminhe a porta 8000 no roteador.

## 7. Operação sem internet

Mantenha a rede Wi-Fi/LAN ativa, desconecte a internet do roteador e repita o
acesso pelo computador e pelo celular. Login, estoque, pedidos e vendas devem
continuar funcionando.

## 8. Teste de portabilidade

1. Encerre com `Ctrl+C`.
2. Copie a pasta inteira para outra unidade ou computador Windows 11 x64.
3. Execute o EXE na nova localização.

Resultado esperado: o sistema usa os dados copiados e não depende da letra da
unidade, do usuário do Windows, de Python ou de internet.

## Limitações e diagnóstico

- O primeiro início de um executável one-file é mais demorado porque os
  recursos internos são extraídos para uma pasta temporária.
- O binário não tem assinatura digital nesta fase; valide sempre sua origem.
- Se houver erro, consulte `logs/portable.log` e `logs/django.log`.
- SQLite pode apresentar contenção em muitas gravações simultâneas.
- A compilação x64 não é um binário ARM64 nativo.
