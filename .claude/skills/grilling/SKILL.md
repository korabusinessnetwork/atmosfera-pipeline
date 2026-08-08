---
name: grilling
description: Entrevista o usuário sem dó sobre um plano, decisão ou ideia até não sobrar nada suposto em silêncio. Use quando o usuário quiser testar o próprio raciocínio antes de construir, ou usar frases como "me questiona", "me grelha", "me interroga", "detona meu plano", "pergunta tudo antes de fazer", "quero fechar o desenho antes de codar", "grill me". É o primitivo reusável de entrevista — outras skills chamam esta em vez de reinventar o roteiro.
---

# Grilling — a entrevista até a árvore fechar

Entreviste o usuário sem dó até vocês chegarem a um **entendimento compartilhado**.
Modele o problema como uma **árvore de decisão**: toda decisão ramifica nas decisões
que dependem dela.

Isso existe porque, como diz o *Pragmatic Programmer*, **ninguém sabe exatamente o que
quer**. A distância entre o que o usuário pediu e o que ele queria é onde nasce retrabalho.
A entrevista fecha essa distância **antes** de escrever a primeira linha.

## O algoritmo

Trabalhe a árvore em **rodadas**.

A **fronteira** é o conjunto de decisões cujos pré-requisitos já estão resolvidos — as
perguntas que dá pra fazer **agora**, sem chutar respostas que você ainda não ouviu.

1. Calcule a fronteira.
2. Faça **a fronteira inteira numa rodada só**, numerada, cada pergunta com a sua
   recomendação.
3. **Pare e espere** as respostas do usuário.
4. As respostas reordenam a árvore: o que ficou resolvido empurra a fronteira pra fora e
   destrava perguntas que dependiam dali. Recalcule a fronteira e faça a rodada seguinte.

Uma pergunta cuja resposta depende de outra pergunta **ainda aberta nesta rodada**
pertence a uma rodada **posterior**, não a esta. Se você não consegue formular a pergunta
sem supor a resposta de outra, ela não está na fronteira.

## Formato de cada pergunta

```
❓ **Q1** — **<título da pergunta>**: <corpo da pergunta, pode ter vários parágrafos,
inclusive alternativas enumeradas>

➡️ <sua recomendação>
```

A recomendação não é opcional. Nunca faça uma pergunta sem dizer o que **você** faria e
por quê — o usuário responde muito mais rápido corrigindo uma proposta do que preenchendo
um vazio.

## Fato é seu, decisão é dele

**Achar fato é trabalho seu, nunca do usuário.** Se uma pergunta da fronteira depende de
algo que está no ambiente (o que já existe no schema, como um módulo está feito hoje, o
que a doc já decidiu), vá olhar. Não pergunte ao usuário nada que você mesmo pode
levantar.

Não trave por causa disso: uma investigação em curso é um pré-requisito não resolvido,
então **só as perguntas que dependem dela** esperam — o resto da fronteira vai agora.

As **decisões** são do usuário. Coloque cada uma na frente dele e espere.

## Quando termina

A sessão acaba quando **a fronteira fica vazia**: todo galho da árvore visitado, nada
suposto em silêncio.

**Não comece a executar até o usuário confirmar** que vocês chegaram ao entendimento
compartilhado. O produto desta skill é o entendimento, não o código.

---

## No Atmosfera Pipeline

**Onde levantar fato** (nesta ordem, antes de perguntar qualquer coisa):
`ATMOSFERA_PIPELINE.md` (fonte da verdade da arquitetura — § 0 são os ADRs, § 7 os limites
operacionais, § 8 a ordem de execução com o histórico de cada rodada) e `CLAUDE.md` →
`specs/` (a spec da rodada que criou o comportamento, e `specs/_manual.md` para o que é
passo humano) → `supabase/migrations/` e `supabase/tests/rls_test.sql` (o banco real e o
que ele garante) → `worker/`, `painel/`, `docs/08_DECISOES/`. Lembre que **a tabela é o
contrato**: se a resposta muda estado, ela está no schema antes de estar no código.

**Subagente com parcimônia.** Delegue só investigação ampla genuinamente paralela em
vários arquivos. Levantamento que se resolve em algumas chamadas de ferramenta você faz no
loop principal — é mais barato e mais rápido que despachar um agente.

**Galhos que nunca podem ficar supostos em silêncio** — se o plano toca neles e o usuário
não falou, eles estão na fronteira:

- **Gate humano** (ADR-06) — são **dois**: o do texto (revisar pauta no `controle.py`) e o
  do vídeo (aprovar no celular). Nada vira publicação sozinho. Se a ideia encurta um
  caminho, pergunte qual gate ela atravessa e por quê.
- **Qual painel** — operação da máquina nasce no painel local (`worker/controle.py`,
  `service_role`, ao lado do PC); aprovação nasce no painel web (Vercel, `anon`). Confundir
  os dois já custou uma rodada inteira.
- **Estado e schema** — se o comportamento novo não cabe no `check (status in (...))`, é
  migration antes de código; e migration que toca tabela só está pronta com caso novo no
  `rls_test.sql` e `advisors` limpo.
- **Multi-tenant e segurança** — `org_id` em toda tabela; RPC de `service_role` com
  `p_org` casa cada linha tocada com `p_org`; a `service_role` nunca sai do `.env` local, e
  nada de token, chave ou URL assinada em log ou coluna.
- **Direção da conexão** (ADR-05) — o worker só faz saída. Se a ideia precisa que algo
  alcance o PC, isso é um galho, não um detalhe.
- **Custo** — o caminho automático é **só gratuito/local** (Ollama, edge-tts, XTTS). Se a
  ideia exige API paga ou com token, isso é decisão do dono: traga custo aproximado,
  alternativa local, impacto e recomendação.
- **Limites de plataforma** (§ 7) — cota de 6/dia do YouTube no fuso do Pacífico, 5
  rascunhos/24h no TikTok, rótulo de IA obrigatório. Não são preferência, são número
  publicado.
- **Como se mede** — qualidade de prompt/geração só vale medida (n, braços pareados,
  antes/depois). Se o plano promete "ficar melhor", pergunte contra o quê e com que número.
