# Homologação do instalador — 18/10/2026

Resultado: fluxo local aprovado com confirmação física do usuário.

## Fluxo executado

1. Backup SQLite em `print_bridge/state/before-installer-20261018.sqlite3`; fila sem trabalhos pendentes. Aplicada somente a migração aditiva `printing.0003_connectorlink`.
2. Tarefa antiga `Bar SaaS - Bridge POS-80 Local` parada e desabilitada para evitar concorrência. Servidor local reiniciado com a nova tela.
3. Instalador aberto; botão de instalação criou executável por usuário, atalho no menu Iniciar, associação `.pdvconnect` e inicialização no login Windows.
4. Vínculo baixado pela tela do SaaS local, Empresa A, sessão `.p` em modo suporte. Arquivo aberto no seletor do conector; empresa e endereço confirmados. Nenhum token copiado manualmente.
5. Configuração permanente armazenada em `settings.bin`, criptografada para o usuário Windows. Vínculo marcado como utilizado. Nova impressora lógica #3.
6. POS-80 selecionada, corte parcial marcado. Botão de teste imprimiu sem criar venda; usuário confirmou texto legível e corte.
7. Ativação pela interface do conector definiu impressora #3 como padrão da Empresa A e habilitou impressão após confirmação da venda.
8. Pelo PDV: pedido #6, comanda TESTE INSTALADOR, venda #6 de R$ 0,01, Pix simulado. Consumida a unidade residual do produto exclusivo #11: estoque 1 → 0. Produto desativado novamente após o teste.
9. Novo conector buscou e confirmou automaticamente ticket #4, uma tentativa, sem erro. Usuário confirmou saída automática com corte após o pagamento.
10. Conector encerrado pela interface e executável instalado reaberto com `--background`, o mesmo comando registrado no login Windows. Configuração preservada, processo ativo e consultas à API retornando 200. Não houve reinicialização completa do Windows nesta etapa.

## Estado final

- Novo conector instalado e ativo em segundo plano, apontando para `http://127.0.0.1:8000`, Empresa A, POS-80, 48 colunas, CP860/tabela 3, corte parcial.
- Bridge antigo desabilitado; arquivos e credencial antiga preservados, sem trabalhos pendentes.
- Fila vazia. Demais produtos e entradas comparados com o backup e preservados.
- Registros do pedido, venda e impressão de teste mantidos para auditoria.
- Servidor local precisa estar funcionando para gerar os tickets; o instalador não inicia o servidor do SaaS.
- Sem commit, push ou publicação no Render. Nenhum dado do Render foi alterado.

## Limites e próximas validações

Confirmar início após um login real do Windows e testar em computador limpo. A reabertura do executável instalado foi validada. O binário continua sem assinatura digital. Publicação do backend e disponibilização do instalador no Render permanecem pendentes.
