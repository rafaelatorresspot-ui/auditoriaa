# Agendamento automático da varredura

O `scanner_documentacao.py` precisa rodar em uma máquina/servidor que tenha
acesso ao drive `K:\` (rede/VPN mapeada) e que consiga escrever na pasta
`dados/` que o Streamlit lê. Pode ser o mesmo servidor onde o Streamlit
estiver publicado, ou outra máquina que grave o resultado em um local
compartilhado (ajustando `PASTA_SAIDA` no script e o caminho lido pelo
dashboard).

## 1. Ajustar o script antes de agendar

No topo de `scanner_documentacao.py`, confira:
- `PASTA_RAIZ` e `GERENCIAL_PATH` — caminhos corretos no servidor
- `COL_NOME` / `COL_STATUS` — nomes exatos das colunas na aba do GERENCIAL.xlsx
  (rode uma vez manualmente; se os nomes não baterem, o script informa quais
  colunas existem de fato)

## 2. Criar tarefa no Windows Task Scheduler

1. Abra o **Agendador de Tarefas** (`taskschd.msc`)
2. **Criar Tarefa Básica** → nome: `Varredura Documentação BKO`
3. **Gatilho**: Diariamente (ex: todo dia às 06:00, antes do horário comercial)
4. **Ação**: Iniciar um programa
   - Programa/script: caminho do `python.exe` do ambiente (ex:
     `C:\Users\r.torres\AppData\Local\Programs\Python\Python3xx\python.exe`)
   - Argumentos: `scanner_documentacao.py`
   - Iniciar em: `C:\Users\r.torres\OneDrive - SPOT\RAFAELA\Python\documentacao_bko`
     (pasta onde os scripts estiverem)
5. Em **Configurações**, marque "Executar mesmo que o usuário não esteja
   conectado" (requer usuário de serviço com acesso ao `K:\`) e "Executar
   com privilégios mais altos" se necessário para acessar a rede.

## 3. Verificar execução

- Log simples: adicione `> log_execucao.txt 2>&1` no fim do comando dos
  argumentos da tarefa, ou capture o retorno da tarefa no próprio Agendador.
- O dashboard mostra automaticamente "Última atualização" lendo
  `dados/ultima_atualizacao.txt`, gerado a cada execução — isso já serve
  como confirmação visual de que a varredura está rodando.

## 4. Publicar o Streamlit via link

Rodar localmente:
```
streamlit run dashboard_documentacao.py --server.port 8501
```

Para deixar acessível via link para o time:
- **Servidor interno**: rode o comando acima em um servidor Windows/Linux
  sempre ligado na rede da empresa, e compartilhe `http://<ip-do-servidor>:8501`
  (ideal configurar como serviço do Windows para reiniciar sozinho).
- **Streamlit Community Cloud**: exige que os dados fiquem em um repositório
  Git acessível pelo Cloud — nesse caso a varredura do `K:\` continua rodando
  localmente/agendada, e você sincroniza apenas o arquivo `dados/dados_documentacao.parquet`
  para o repositório (ex: via Git commit automático ao final do scanner,
  ou upload para um storage que o Cloud consiga ler).

Se preferir, posso ajudar a montar o serviço do Windows ou o script de
commit automático — é só avisar qual das duas opções de hospedagem vocês
vão usar.
