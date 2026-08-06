# Passos manuais acumulados

Tudo que só uma pessoa pode fazer — credencial, tela de consentimento, caixa de
e-mail, painel de terceiro. O loop **não** interrompe para pedir nenhum destes;
ele anota aqui e segue. A lista é entregue de uma vez no fim, como o dono pediu.

Ordem de leitura: o que destrava mais coisa primeiro.

---

## 1. Footage de verdade em `MoneyPrinterTurbo/storage/local_videos/`

**Por quê:** os três clipes que estão lá (`atm-teste-01/02/03.mp4`) são pretos —
o pixel mais claro do frame inteiro fica em 36–41 de 255. Não é "material
escuro": um clipe cinematográfico escuro ainda tem highlight passando de 200.
Enquanto isso não mudar, todo vídeo renderizado é tela preta com legenda, e a
graduação da Sprint 3 não pode ser julgada.

**O que fazer:** soltar arquivos `.mp4` verticais na pasta. Nenhuma linha de
código muda. Nome de arquivo, não caminho — o MPT resolve tudo contra essa pasta
e descarta em silêncio o que escapar.

---

## 2. OAuth do YouTube (item 9b do § 8)

**Por quê:** o worker publica no YouTube, mas nenhum vídeo subiu ainda. O
consentimento do Google exige uma pessoa na tela; credencial não passa por mim.

**O que fazer**, em `console.cloud.google.com`:

1. Ativar a **YouTube Data API v3**.
2. Tela de consentimento: tipo **Externo**, e o seu e-mail em **Usuários de teste**.
3. Criar ID de cliente OAuth do tipo **App para computador**.
4. Baixar o JSON e salvar como `worker/client_secret.json`.

Depois:

```bash
cd worker && uv run autorizar_youtube.py
```

Abre o navegador, você aprova, o script grava `worker/token.json` (gitignored).

**Armadilha de 7 dias:** enquanto o app estiver como *Testing*, o refresh token
expira toda semana e o worker para de publicar com `AutorizacaoAusente` — sem
barulho, só some vídeo. Publicar o app (mesmo sem verificação, para uso próprio)
remove o prazo. Isso morde na Sprint 7, quando o worker subir sozinho no boot.

---

## 3. Deploy do painel na Vercel + primeiro login (item 10b do § 8)

**Por quê:** o painel está pronto e compila, mas ninguém logou. O magic link cai
numa caixa de e-mail que é sua.

1. Vercel: importar o repositório com **Root Directory = `painel`**.
2. Variáveis: `NEXT_PUBLIC_SUPABASE_URL` e `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
   **Só a anon.** A `service_role` não entra na Vercel em hipótese nenhuma.
3. Supabase → Authentication → URL Configuration: **Site URL** com o domínio da
   Vercel, e **Redirect URLs** incluindo `https://<domínio>/auth/confirm`.
   Sem isso o link chega e não vira sessão.
4. Abrir no celular, pedir o magic link, confirmar que a fila aparece.

Opcional: trocar o template de e-mail para `{{ .TokenHash }}`. Não é necessário —
`/auth/confirm` aceita `code` e `token_hash`.

---

## 4. App do TikTok (Sprint 5)

**Por quê:** o worker sabe conversar com a API, mas o app precisa existir e ser
autorizado por você. E há um limite que o código não consegue contornar.

1. Criar o app no portal de desenvolvedor do TikTok.
2. Pedir o escopo **`video.upload`** (rascunho/inbox). **Não** `video.publish`:
   cliente não auditado é forçado a `SELF_ONLY` em direct post, o que renderiza
   um vídeo que ninguém vê.
3. Registrar a **redirect URI**, que precisa ser **HTTPS e estática** —
   localhost e HTTP são recusados pelo TikTok.
4. Preencher no `worker/.env`: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`,
   `TIKTOK_REDIRECT_URI`.
5. Rodar `uv run autorizar_tiktok.py` e colar de volta a URL para onde o TikTok
   te redirecionou.

**O que a API não faz por você:** o rótulo de conteúdo gerado por IA. O endpoint
de rascunho aceita só `source_info` — legenda, privacidade e o toggle de IA são
escolhidos no app, na hora de postar. **Ligue o toggle de "conteúdo gerado por
IA" em cada rascunho.** Sem rótulo, a política das duas plataformas prevê
remoção do conteúdo.

---

## 5. Registrar o worker no Task Scheduler (item 12b do § 8)

**Por quê:** a tarefa roda **como você**, na sua sessão do Windows. Criá-la é um
comando de um minuto, mas o dono da tarefa é quem a registra — e o resto da
Sprint 7 (batimento, health check, faixa no painel) já está provado contra o
banco real sem ela.

Num PowerShell qualquer — **não precisa de administrador**, a tarefa é sua e não
do sistema — na raiz do projeto:

```powershell
pwsh worker/scripts/Registrar-Worker.ps1
```

Ele cria `\Atmosfera\Atmosfera Worker`: gatilho no **seu logon** com 1 min de
atraso (no logon o Windows ainda está montando rede e o OneDrive ainda está
hidratando arquivo), reinício automático em caso de queda (3×, 5 min de
intervalo), sem limite de duração, e sem parar na bateria nem quando você volta
a mexer no PC. Ele confere antes de registrar — `.env` ausente, `uv` fora do
PATH ou `main.py` no lugar errado viram erro na hora, com a frase inteira — e
relê a tarefa gravada no fim, para o "pronto" ser evidência e não promessa.

Subir na hora, sem esperar o próximo logon:

```powershell
Start-ScheduledTask -TaskName 'Atmosfera Worker' -TaskPath '\Atmosfera\'
```

E o veredito do batimento, que é a pergunta que interessa:

```bash
cd worker && uv run saude.py
```

Para desfazer, `pwsh worker/scripts/Remover-Worker.ps1` — idempotente, não
reclama se a tarefa não existir, e não encosta em `logs/`, `.env` nem token.

**Opcional — subir com o PC trancado.** O gatilho é logon e não boot de
propósito: boot exigiria guardar a senha da sua conta do Windows dentro da
tarefa, e senha não passa por mim. Se você quiser que o worker suba mesmo com a
máquina reiniciando sozinha de madrugada, o caminho é ligar o **auto-logon do
Windows** por conta própria (`netplwiz` → desmarcar "Os usuários devem digitar
um nome e uma senha"). Isso é uma escolha de segurança sua, e ela vale a pena
pensar: com auto-logon, quem tem acesso físico à máquina tem a sua sessão — e
dentro dela está o `.env` com a `service_role`.

**Lembrete que vem do § 2:** com o app do Google ainda em *Testing*, o refresh
token expira a cada 7 dias. Um worker que sobe sozinho e para de publicar em
silêncio no oitavo dia é exatamente o modo de falha que a Sprint 7 existe para
tornar visível — o `saude.py` vai dizer `SAUDAVEL`, porque o loop está girando;
quem denuncia é o vídeo que não sobe.

---

## 6. ~~As duas tarefas agendadas no Cowork (item 13b do § 8)~~ — APOSENTADO (R10)

> **O Cowork foi aposentado na Rodada 10 (2026-08-04).** Não há mais tarefa
> remota para configurar: a pauta de segunda roda localmente desde a Rodada 4 e o
> relatório de sexta desde a Rodada 10, os dois com Ollama no seu PC (§ 7). Esta
> seção fica como **referência histórica** — se um dia você quiser voltar o
> Cowork, o passo a passo está aqui; mas o caminho vivo é o § 7.

**Por quê (histórico):** os itens 1–12 construíram tudo que acontece **depois** que
uma pauta existe. Nada produzia pauta. Com o worker no boot e a fila vazia, o
sistema completo acordava a cada 30s, não achava nada e voltava a dormir — para
sempre. O formulário do painel resolve a ideia avulsa; o Cowork enchia a fila toda
segunda sem o PC ligado. Hoje o produtor local faz isso, com o PC que o worker já
exige ligado.

A conta do Cowork é sua e o prompt precisa do **seu** `org_id`. Nada disso passa
por mim.

### 6.1 Descobrir o `org_id`

No SQL Editor do Supabase:

```sql
select org_id from public.membros where email = 'seu@email.com';
```

Esse uuid substitui o `'00000000-0000-0000-0000-000000000000'` do template de
INSERT. **É o único valor do prompt que precisa ser trocado** — se ele ficar como
está, o INSERT funciona e as 15 pautas caem numa org que não é a sua: elas
existem no banco e não aparecem no painel, porque a RLS faz exatamente o que
deve. O sintoma é "a tarefa rodou e não veio nada", que é o mais difícil de
diagnosticar.

### 6.2 Subir `memory/00_IDENTIDADE.md` para o Drive

O prompt de segunda manda ler esse arquivo antes de escrever a primeira linha —
é onde vivem tom de voz, o teto de 88 caracteres do hook e as sete regras do que
nunca fazer. O Cowork **não enxerga o seu disco**; se o arquivo não estiver no
Drive, ele escreve pauta genérica e nada avisa.

Copie `memory/00_IDENTIDADE.md` para o Google Drive em `/Atmosfera/`. Quando você
mexer nele aqui, suba de novo — o arquivo do Drive é uma cópia, e cópia velha é
pior que arquivo ausente.

### 6.3 Criar as duas tarefas

| Tarefa | Cadência | Prompt | Conectores |
|--------|----------|--------|------------|
| Pauta semanal | segunda, 06:00 | `cowork/pauta-semanal.md` | Supabase MCP · Google Drive |
| Relatório | sexta, 18:00 | `cowork/relatorio.md` | Supabase MCP · Google Drive |

Em cada arquivo, o prompt é o bloco entre as crases — cole ele inteiro, sem o
texto explicativo em volta. O que está fora do bloco é para você, não para o
agente.

**Os arquivos no git são a fonte da verdade.** A tarefa agendada é uma cópia que
vive numa conta pessoal e não entra em diff. Quando os dois divergirem, corrija
aqui e recole lá.

### 6.4 O que saber antes de ligar

- **O Cowork não avisa quando falha.** Nenhuma das duas tarefas notifica erro.
  Relatório ausente na sexta é sintoma, não silêncio — e pauta que não entrou na
  segunda só aparece como fila vazia na quarta. Por isso o estado vive nas
  tabelas: se a tarefa quebrar, nada do que já existe se perde.
- **Cada execução consome uso do plano** como uma sessão normal.
- **Não cole a `service_role` no Cowork.** O conector do Supabase se autentica
  sozinho; a chave que ignora RLS no banco inteiro continua só no `.env` local do
  worker. Se algum campo pedir uma chave, é a errada.
- **A tarefa de segunda só faz INSERT em `pautas`; a de sexta só faz SELECT.**
  Está escrito nos dois prompts, e é o limite que mantém o Cowork como camada de
  decisão — quem muda estado de vídeo é o worker e o gate humano, ninguém mais.
- **Primeira execução: não espere segunda-feira.** Rode a tarefa à mão uma vez e
  confira no painel se as pautas apareceram. Se aparecerem lá, o `org_id` está
  certo — que é a única coisa que pode estar errada e não dá erro.

---

## 7. Ativar os produtores locais com Ollama (pauta R4 + relatório R10)

**Por quê:** o Cowork era o único ponto do sistema que gastava uso do plano. Os
produtores locais fazem o mesmo trabalho — pauta de segunda e relatório de sexta —
com um LLM que roda no seu PC, de graça, offline, sem token. Com os dois locais, o
Cowork foi aposentado e **nada no sistema depende mais de token**: se o plano
zerar, a fila continua girando.

Não é mais "escolha um dos dois" (era, na Rodada 4, enquanto o Cowork existia):
hoje o caminho local é o único. São dois processos separados no PC — a pauta
(`pauta_local.py`) e o relatório (`relatorio_local.py`), cada um com sua tarefa
agendada.

### 7.1 Instalar o Ollama e puxar um modelo

1. Instale o Ollama: https://ollama.com
2. Puxe o modelo:
   ```powershell
   ollama pull qwen2.5
   ```
   **Por que qwen2.5 e não llama3.1** (medido em teste seco): para pt-BR, o
   llama3.1 8B alucina token quebrado no meio do roteiro (`"ezê"`) e copia os
   exemplos de referência em vez de criar ângulo novo. O qwen2.5 escreve
   português limpo e trata os exemplos como estilo. Se o seu canal for em
   **inglês**, o llama3.1 aí é forte — é a língua-mãe dele.

### 7.2 Testar a qualidade do hook ANTES de agendar

O hook é o produto (§7 do documento mestre: o gargalo nunca foi renderizar).
Modelo local escreve hook mais fraco que o Claude — então rode à mão primeiro e
olhe o resultado no painel antes de confiar a produção a ele:

```powershell
cd worker
uv run pauta_local.py
```

Ele lê `memory/00_IDENTIDADE.md`, gera as pautas e — pelo trigger — cada uma já
entra na fila até o gate. Abra o painel e veja se os hooks prestam. Se estiverem
fracos, troque o modelo em `worker/.env` (`OLLAMA_MODEL=`), não o prompt: a voz
da marca mora no `00_IDENTIDADE.md`, que é onde a identidade se ajusta.

### 7.3 Agendar (segunda 06:00 ou quando a fila esvaziar)

Mesma ideia do worker (seção 5), tarefa própria. Um gatilho de horário simples,
no PowerShell (a tarefa roda como você, sem senha):

```powershell
$acao = New-ScheduledTaskAction -Execute 'C:\Users\bonas\.local\bin\uv.exe' `
  -Argument 'run pauta_local.py' `
  -WorkingDirectory 'C:\Users\bonas\OneDrive\Documentos\Projetos\atmosfera-pipeline\worker'
$gatilho = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 6:00am
Register-ScheduledTask -TaskName 'Atmosfera Pauta' -TaskPath '\Atmosfera\' `
  -Action $acao -Trigger $gatilho
```

**Antes de agendar, o worker precisa estar de pé** (seção 5) — senão a pauta
entra na fila e ninguém renderiza. E o Ollama tem de estar rodando no horário: se
o PC estiver ligado, `ollama serve` sobe sozinho como serviço; confira.

### 7.3b Agendar o relatório de sexta (item 13c do § 8)

O relatório semanal (`relatorio_local.py`) substitui a tarefa de sexta do Cowork.
Ele lê o banco (só SELECT), escreve `output/relatorios/AAAA-MM-DD-semana.md` e não
depende de rede além do Supabase e do Ollama local. Uma tarefa própria, sexta
18:00:

```powershell
$acao = New-ScheduledTaskAction -Execute 'C:\Users\bonas\.local\bin\uv.exe' `
  -Argument 'run relatorio_local.py' `
  -WorkingDirectory 'C:\Users\bonas\OneDrive\Documentos\Projetos\atmosfera-pipeline\worker'
$gatilho = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 6:00pm
Register-ScheduledTask -TaskName 'Atmosfera Relatorio' -TaskPath '\Atmosfera\' `
  -Action $acao -Trigger $gatilho
```

Rode à mão uma vez antes (`uv run relatorio_local.py`) e abra o arquivo em
`output/relatorios/`. Se o Ollama estiver fora, o relatório sai mesmo assim, só
sem a seção de recomendações — os números nunca dependem do modelo.

### 7.4 O que saber

- **Backpressure automático.** Se a fila já tem 20 vídeos vivos (não aprovados),
  o gerador não escreve nada e diz por quê. Pauta em cima de fila cheia só
  afunda o que existe. Ajuste em `PAUTA_LOCAL_TETO` se precisar.
- **Falhar aqui não quebra nada.** O gerador é processo separado. Ollama fora do
  ar = a tarefa falha, loga, e a fila fica intacta — o estado vive nas tabelas.
- **PC ligado é requisito.** Diferente do Cowork (que roda na nuvem com o PC
  desligado), o Ollama é local. Como o worker já exige o PC ligado, na prática
  não muda nada — mas é a diferença de desenho entre os dois.

---

## 8. Higiene do OneDrive

`worker/` está dentro do OneDrive, então `token.json`, `tiktok_token.json` e
`.env` — que carrega a `service_role` — sincronizam para a nuvem da Microsoft.
Se isso não te agrada, aponte `YOUTUBE_TOKEN`/`TIKTOK_TOKEN` para fora da pasta
sincronizada. Vale excluir `painel/node_modules` da sincronização também: são
dezenas de milhares de arquivos que o OneDrive tenta versionar sem motivo.

---

## 9. Canal em inglês — o que é seu (Rodada 5)

O lado técnico já está feito: identidade em inglês, prompt em inglês, `MPT_VOZ`
en-US e o upload declarando `defaultLanguage=en-US`. **Não precisa de servidor
gringo nem VPN** — o alcance é decidido pelo idioma do conteúdo, não pelo IP de
quem sobe. Upar do Brasil está ok.

O que sobra é seu, e é opcional/cosmético:

- **Renomear o canal no YouTube Studio** para um nome em inglês, e trocar a
  descrição/banner. Não é código; o vídeo sobe no mesmo canal de qualquer jeito.
- **Preencher o W-8BEN** (YouTube Studio → Pagamentos → informações fiscais dos
  EUA). É o tratado Brasil–EUA que reduz a retenção americana sobre a receita de
  público dos EUA. Papelada, não código — mas é o que faz "dá mais dinheiro"
  chegar inteiro.
- **TikTok:** o worker sobe rascunho e você finaliza no celular. Se um dia quiser
  empurrar o "For You" americano com força, a prática é chip/eSIM dos EUA — não é
  requisito para começar, conteúdo em inglês já entrega.

Para **voltar ao pt-BR**: `MPT_VOZ` de volta para uma voz pt-BR, `00_IDENTIDADE.md`
e `montar_prompt` revertidos (o git guarda), e `youtube.py` de `en-US` para
`pt-BR`. É reversível — nada foi apagado do banco.

---

## 10. Ligar o footage variado via Pexels (Rodada 6)

**Por quê:** hoje o worker recicla só os clipes de `storage/local_videos/` — com
poucos clipes, todo vídeo repete o mesmo material e fica genérico. O modo
`pexels` faz o MPT baixar stock variado por vídeo, com os termos de busca gerados
pelo **Ollama local** (custo zero). A parte de código já está pronta e o
`config.toml` do MPT já foi apontado para o Ollama; o que falta é **uma chave
gratuita do Pexels** — que é sua, porque envolve criar conta.

**O que fazer, uma vez:**

1. **Pegue a chave gratuita** em https://www.pexels.com/api/ (crie a conta, a
   chave aparece no painel). É grátis, sem cartão.
2. **Cole no config do MPT** (`MoneyPrinterTurbo/config.toml`, gitignored):
   ```toml
   pexels_api_keys = ["a-sua-chave-aqui"]
   ```
3. **Deixe o Ollama de pé** com o modelo puxado (o mesmo da pauta local):
   ```
   ollama pull qwen2.5
   ```
   O `config.toml` já está com `llm_provider = "ollama"` e
   `ollama_model_name = "qwen2.5"` — não precisa mexer.
4. **Ligue o modo** no `worker/.env`:
   ```
   MPT_VIDEO_SOURCE=pexels
   ```
5. Reinicie o worker. O próximo render busca footage no Pexels.

**O que saber:**

- **Sem a chave do Pexels, o render cai em `erro`** — mas **não trava a fila**:
  o `tentativas < 3` do banco governa, o vídeo volta para `na_fila` e para depois
  de 3 tentativas. Você vê o motivo em `videos.erro_msg` no painel.
- **Sem o Ollama de pé**, o MPT não gera os termos de busca e o render também
  falha — mesmo tratamento. O Ollama já é exigência da pauta local, então se o
  produtor de pauta roda, isto roda.
- **Voltar ao local** é trocar `MPT_VIDEO_SOURCE=local` (ou apagar a linha — o
  padrão é `local`). Nada mais muda.
- Pexels é **stock genérico de banco**, não a sua estética. É variedade, não
  autoria — a graduação/grão/vinheta da Sprint 3 continua por cima, dando a cara
  do canal. Se quiser material autoral, a alternativa é curar footage próprio em
  `local_videos/` (seção 1).

---

## 11. Métrica de verdade — coleta do YouTube (Rodada 11)

**Por quê:** até aqui o banco sabe que **publicou** e não sabe se alguém
**assistiu** — por isso o relatório de sexta lista os hooks para conferência à mão
no Studio, em vez de ranquear por retenção. A Rodada 11 traz a tabela `metricas` e
o coletor (`coletar_metricas.py`), que puxa views/retenção da YouTube Analytics
API. Dois passos são seus: um consentimento e a aplicação da migration.

### 11.1 Re-consentir o OAuth com o escopo de Analytics

O coletor lê a Analytics API, e o token de hoje só tem escopo de **upload**. Rode
de novo o autorizador — agora ele pede upload **e** `yt-analytics.readonly` (só
leitura) de uma vez:

```bash
cd worker && uv run autorizar_youtube.py
```

Aprove na tela do Google. O `token.json` passa a cobrir os dois escopos. **O
upload não quebra durante isso** — o escopo dele não mudou. Antes de re-consentir,
o coletor volta `403` e degrada por vídeo (loga e segue); nada mais para.

### 11.2 Aplicar e verificar a migration `metricas`

A migration `20260804150153_metricas_youtube.sql` cria a tabela. Como o meu
ambiente não alcança o Supabase (DNS externo bloqueado no sandbox), **aplicar e
verificar é seu** — na sua máquina, com o CLI logado:

```bash
supabase db push
supabase db advisors --linked
supabase db query --linked -f supabase/tests/rls_test.sql
```

O alvo é o de sempre: advisors **`No issues found`** e o `rls_test.sql` com
**todos os casos ✅** (os três novos — 29, 30, 31 — cobrem a métrica: a org lê a
sua, o `authenticated` não escreve, o anônimo não lê). Se o push reclamar de
versões, é o pareamento de migration local×remoto — confira que nenhum outro
arquivo novo ficou por aplicar.

### 11.3 Coletar (à mão, e depois agendado)

Com os dois passos acima feitos, rode à mão para conferir:

```bash
cd worker && uv run coletar_metricas.py
```

Ele lista as publicações do YouTube com `external_id`, puxa o retrato de cada uma
e faz upsert em `metricas`. Vídeo publicado hoje ainda sem dado entra zerado (não
é erro). Depois, agende como os outros produtores locais (seção 7) — uma tarefa
semanal, por exemplo junto do relatório de sexta, já que é ele quem vai consumir a
métrica quando a próxima rodada fechar o loop.

**O que esta rodada NÃO faz, de propósito:** consumir a métrica. Ranquear a pauta
por retenção, mostrar no painel e alimentar fine-tuning são as próximas rodadas —
esta **coleta e guarda**. O relatório e o gerador seguem como estão.

## 12. Pauta via Gemini para o cold-start (Rodada 20)

O produtor `pauta_gemini.py` escreve pauta com um modelo frontier (Gemini) enquanto
a tabela `metricas` não tem histórico para treinar o modelo local. É **opt-in** e
**fora do loop** — o produtor gratuito/offline continua sendo `pauta_local.py`
(Ollama). É uma **exceção deliberada e escopada** à regra "auto só gratuito/local",
que você autorizou: o Gemini grátis não é pago, mas é API na nuvem com token, então
fica como ferramenta manual de bootstrap, não no caminho automático.

**Duas ressalvas do tier grátis, que você aceitou conscientemente:**
1. **Rate limits.** Estourou, o produtor diz "limite do tier grátis" e para; roda de
   novo mais tarde. Subir o teto exige habilitar billing no Google Cloud (passo seu,
   fora do código).
2. **Treino.** No tier grátis, o Google usa os prompts para treinar os modelos deles.
   No pago, não. Para conteúdo de pauta, você decidiu que tudo bem.

### 12.1 Pegar a chave (grátis, sem cartão)

1. Entre em <https://aistudio.google.com> com sua conta Google.
2. Clique em **Get API key** → **Create API key**.
3. Copie a chave e cole no `worker/.env`:

```
GEMINI_API_KEY=AIza...sua-chave
```

A chave é **secret**: vai só no `.env` (gitignored), nunca no `.env.example`, nunca
em log, nunca na Vercel. O `worker/` está dentro do OneDrive — a mesma higiene do
`token.json` e da `service_role` vale aqui (seção 8).

O modelo tem padrão **`gemini-flash-latest`** (alias, aponta sempre para o flash
atual). Não use versão cravada: medido em 2026-08-06 com a chave nova,
`gemini-2.0-flash` responde 429 "limit: 0" e `gemini-2.5-flash` responde "no longer
available to new users" — o sintoma é um produtor que só falha, e não parece
"modelo aposentado". Se quiser outro, ajuste `GEMINI_MODEL`.

### 12.2 Aplicar a migration

`origem='gemini'` precisa caber no check e disparar o trigger de auto-enfileirar. Com
o projeto linkado (como nas rodadas recentes):

```bash
supabase db push
supabase db advisors --linked          # alvo: No issues found
supabase db query --linked -f supabase/tests/rls_test.sql   # alvo: 42 ✅
```

### 12.3 Rodar

```bash
cd worker && uv run pauta_gemini.py
```

Ele conta a fila viva (backpressure — não gera em cima de fila cheia), lê a
identidade da marca e os vencedores por retenção (se houver), pede N pautas ao
Gemini, valida e insere com `origem='gemini'`. O trigger enfileira cada uma até o
**gate humano** — aprovar e publicar seguem exigindo você. Se a fila esvaziar e você
quiser cadência, agende como os outros produtores locais (seção 7).

## 13. Produção automática, categorias e o MPT sob o worker (Rodada 21)

Esta rodada muda **o que você opera**: o botão "Gerar agora", os horários da produção
automática e as categorias moram no **painel local** (`worker/controle.py`), não no
painel da Vercel. O painel web continua sendo só o **gate humano** (aprovar/reprovar
no celular) — quem opera a máquina é a tela que roda ao lado dela.

### 13.1 Aplicar as duas migrations

Duas tabelas novas (`configuracao_producao` e `categorias`) e uma coluna
(`pautas.categoria`). Sem elas o painel local mostra a fila normalmente, mas a seção
de produção fica vazia e a automática não dispara.

```bash
supabase db push
supabase db advisors --linked
supabase db query --linked -f supabase/tests/rls_test.sql
```

Alvos: `No issues found` nos advisors e **48 ✅** no rls_test (eram 42 — seis casos
novos: leitura por org das duas tabelas, escrita negada ao painel web, anônimo cego,
uma só categoria padrão por org e horário inválido recusado).

### 13.2 Criar suas categorias

```bash
cd worker && uv run controle.py
```

No cartão **produção**, clique em `ajustar`:

- **Automática ligada** e os **horários** (padrão `8, 14, 18`). Aceita `8h`, `08`,
  separado por vírgula ou ponto e vírgula.
- **Categorias**: crie as suas (`religião`, `motivação`, `lifestyle`…) e marque uma
  como **padrão**. A padrão é a que a produção automática usa — você escolhe antes,
  não às 8h da manhã.

Sem categoria padrão, a automática gera **genérico** (o comportamento de antes desta
rodada). Categoria dirige o **assunto**; a voz da marca continua vindo inteira de
`memory/00_IDENTIDADE.md`.

### 13.3 O que muda no dia a dia

- **"⚡ Gerar agora"** gera na hora, na categoria escolhida no seletor ao lado. Tenta
  o Gemini e, sem cota, **cai para o Ollama** — o manual sempre produz, e a janela diz
  qual dos dois escreveu (hook do Ollama é mais fraco; você decide isso na aprovação).
- **A automática** (8/14/18h) usa **só o Gemini**. Sem cota, ela **pausa** e o motivo
  aparece no painel (`⚠ pausada: …`). Foi decisão sua: três vídeos por dia com hook
  fraco é pior que nenhum. O próximo horário tenta de novo sozinho.
- **PC desligado na hora do slot?** Ao voltar, o slot mais recente ainda é cumprido —
  uma vez só. Não acumula os três.
- **O MPT sobe junto com o worker**, oculto, e o log vai para
  `worker/logs/mpt-<data>.log`. Foi o que resolveu os seis vídeos em `erro` do dia
  2026-08-06 (`[WinError 10061]` = MPT desligado). Para voltar a subir o MPT à mão,
  `MPT_AUTO_START=false` no `.env`.

**O gate humano continua de pé.** Nada disto publica sozinho: pauta → vídeo →
`aguardando_aprovacao` → **você**, no celular.
