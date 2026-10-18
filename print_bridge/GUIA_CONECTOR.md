# Conector Praça PDV — Windows

## Para o cliente

1. Conecte a impressora e confirme que ela imprime a página de teste do Windows.
2. Abra `ConectorPracaPDV.exe` e clique em **Instalar e iniciar com o Windows**. Não é necessário instalar Python nem usar terminal.
3. No conector, informe o endereço do seu SaaS e clique em **Abrir meu SaaS**. Para o sistema deste computador, use `http://127.0.0.1:8000`. Para o Render, use o endereço HTTPS do bar.
4. Entre com um usuário autorizado a configurar impressão. Clique em **Conectar minha impressora**. Abra o arquivo `.pdvconnect` baixado; se o navegador não abrir diretamente, use **Abrir arquivo de conexão baixado** no conector.
5. Confira o endereço e a empresa mostrados. Selecione a impressora do Windows (USB) ou informe IP e porta para uma impressora de rede.
6. Marque o corte se a impressora tiver guilhotina. Clique em **Imprimir teste** e confira o papel. O teste não cria venda nem movimenta estoque.
7. Clique em **Ativar impressão ao confirmar venda e pagamento**. Essa impressora passa a ser a padrão da empresa.

Depois disso, confirme as vendas normalmente. Fechar a janela mantém a impressão em segundo plano quando ativada. Abra novamente pelo menu Iniciar para ver o estado. **Encerrar conector** para a impressão neste computador até abri-lo novamente. **Pausar** mantém tickets no SaaS; para retomar, teste e ative novamente.

O conector inicia ao entrar com o mesmo usuário do Windows. O computador e a impressora precisam estar ligados. No SaaS local, o servidor também precisa estar funcionando: o conector não instala nem inicia o servidor do PDV. No Render, o computador precisa de internet.

Não compartilhe o arquivo de conexão: ele expira em 10 minutos e só pode ser usado uma vez. Nenhum token precisa ser copiado. A configuração permanente é criptografada para o usuário Windows.

## Distribuição e implantação — equipe técnica

- Executável: `print_bridge/dist/ConectorPracaPDV.exe`. É um auto-instalador por usuário, sem necessidade de administrador, que copia o aplicativo para `%LOCALAPPDATA%/Programs/PracaPDVConnector`, registra a associação `.pdvconnect`, cria atalho no menu Iniciar e entrada de inicialização do usuário.
- Dados e journal: `%LOCALAPPDATA%/PracaPDV/Connector`. Não apague o journal para repetir uma impressão incerta.
- A migração `printing.0003_connectorlink` adiciona somente a tabela de vínculos de uso único. Não modifica estoque, pedidos ou vendas. Implantar backend e migração antes de distribuir o fluxo de vínculo.
- No SaaS local, a tela oferece o executável quando ele está em `print_bridge/dist/`. O download exige permissão para gerenciar impressão.
- No Render, hospede o executável como artefato de versão em HTTPS e configure `PRINT_CONNECTOR_DOWNLOAD_URL` com seu endereço. O executável Windows não é compilado pelo build Linux do Render. Sem o artefato configurado, a tela orienta solicitar o instalador ao suporte; não exibe link quebrado.
- Build reproduzível pelo script `print_bridge/build_windows.ps1`, usando `requirements-build.txt` existente. O cliente recebe apenas o executável.
- Binário ainda sem assinatura Authenticode. Para distribuição comercial, assinar e publicar uma versão identificada. Não orientar clientes a desativar proteção do Windows.
- O conector mantém uma empresa por perfil Windows. Troca de empresa e migração de uma instalação antiga requerem suporte para conferir pendências e revogar a credencial antiga. Não substitua um bridge em operação sem conferir a fila.
- Instalações antigas por tarefa agendada não são removidas silenciosamente. O bridge antigo deste computador foi preservado durante o desenvolvimento.

## Validação desta entrega

- 65 testes focados: 64 passaram, 1 ignorado por depender de PostgreSQL.
- Cobertura nova: uso único/expiração, empresa inativa, autenticação, CSRF/permissão para baixar vínculo, isolamento na ativação, validação de parâmetros, HTTPS, criptografia DPAPI e ticket de teste com corte.
- Fluxo completo homologado localmente em 18/10/2026: instalação, vínculo pela tela, teste físico com corte, ativação, venda #6 e impressão automática confirmada pelo usuário. Executável instalado reaberto em segundo plano com configuração preservada. Ver `printing/INSTALLER_TEST_REPORT.md`. Ainda faltam computador limpo e login real após reiniciar Windows.
- A implementação anterior já teve impressão USB, corte e reimpressão sem nova baixa confirmados fisicamente. Isso não substitui a homologação do novo instalador.
- Sem publicação no Render nesta etapa; código, migração e documentação permanecem locais para revisão.
