# Cowork · tarefa agendada 2 — Relatório semanal

**Cadência:** sexta, 18:00 · **Conectores:** Supabase MCP, Google Drive
**Saída:** markdown em `/Atmosfera/relatorios/`

Mesma regra do outro arquivo: este é a versão de referência, a tarefa agendada é
a cópia. Configurar é passo humano — `specs/_manual.md`.

## Duas armadilhas que o prompt precisa desviar

**1. `erro_msg` em `videos` significa duas coisas.** Render que falhou escreve ali
o erro técnico; **reprovação humana escreve ali o motivo** (`reprovar_video`
grava `status = 'reprovado'` e o motivo em `erro_msg`, migration
`20260802223612`). Agrupar os dois no mesmo "motivos mais comuns" mistura "ffmpeg
não achou a fonte" com "legenda cortada" — problemas de dono diferente. O
relatório separa por `status`.

**2. Retenção não existe neste banco, e o § 4 do documento mestre pede.** O
prompt original manda dizer "quais hooks tiveram melhor retenção". Nenhuma tabela
guarda view, watch time ou retenção — `publicacoes` tem `url`, `status`,
`enviado_em`, `publicado_em` e mais nada de métrica. Inventar essa seção seria
um relatório semanal mentindo com números plausíveis toda sexta.

Enquanto ninguém puxar a YouTube Analytics API, o relatório entrega a **lista dos
hooks publicados na semana com o link**, para conferência de 2 minutos no YouTube
Studio, e diz que a métrica não está no banco. Está no backlog do
`ATMOSFERA_PIPELINE.md` § 9.

## O prompt

```
Você é o analista do Atmosfera Viral. Escreva o relatório da semana.

DADOS — consulte o Supabase (janela: últimos 7 dias)

1. Produção, por estado:
   select status, count(*)
     from public.videos
    where created_at > now() - interval '7 days'
    group by status
    order by 2 desc;

2. Reprovação humana (motivo escrito por uma pessoa no painel):
   select v.erro_msg as motivo, p.tema, p.hook
     from public.videos v
     join public.pautas p on p.id = v.pauta_id
    where v.status = 'reprovado'
      and v.updated_at > now() - interval '7 days';

3. Falha técnica (motivo escrito pelo worker) — outra coisa, não misturar:
   select v.erro_msg as erro, v.tentativas, p.tema
     from public.videos v
     join public.pautas p on p.id = v.pauta_id
    where v.status = 'erro'
      and v.updated_at > now() - interval '7 days';

4. Publicações:
   select pub.plataforma, pub.status, pub.url, pub.publicado_em,
          pub.agendado_para, pub.erro_msg, p.tema, p.hook
     from public.publicacoes pub
     join public.videos v on v.id = pub.video_id
     join public.pautas p on p.id = v.pauta_id
    where pub.created_at > now() - interval '7 days'
    order by pub.created_at;

5. Fila parada — o que existe e não andou:
   select status, count(*) from public.pautas group by status;
   select count(*) from public.videos where status = 'aguardando_aprovacao';

6. Saúde do worker (a função já devolve o atraso calculado pelo banco —
   não subtraia horário por conta própria, o relógio do worker não é o seu):
   select * from public.saude_workers();

O QUE ESCREVER

## Números da semana
Renderizados, aprovados, reprovados, publicados, em erro. Uma linha cada.

## Reprovação
Taxa e os motivos mais comuns, agrupados por ideia (não copiar 8 frases
parecidas). Se a taxa passar de 30%, aponte o padrão: é o hook, é o roteiro,
ou é o material de vídeo?

## Falha técnica
Só se houver. Erro do worker é problema de código ou de máquina, não de
conteúdo — separe do bloco acima e não sugira mudar pauta por causa dele.

## Publicado
Lista dos hooks que foram ao ar, com plataforma e link.
Retenção e views NÃO estão neste banco: escreva a lista para conferência
manual no YouTube Studio e diga, em uma linha, que a métrica ainda não é
coletada. Não estime, não invente número.

## Gargalo
Onde a fila parou esta semana — pauta sem virar vídeo, vídeo esperando
aprovação, ou aprovado sem publicar. Aponte UM, o maior.

## 3 recomendações para a pauta de segunda
Concretas e ligadas ao que está acima. "Melhorar os hooks" não é
recomendação; "os 4 reprovados abriram com pergunta retórica — cortar esse
formato" é.

LIMITES
Somente SELECT. Nenhum INSERT, UPDATE ou DELETE, em nenhuma tabela.
Não altere schema.

ONDE SALVAR
Markdown no Google Drive em /Atmosfera/relatorios/, nome
`AAAA-MM-DD-semana.md` com a data da sexta.
```

## O que fazer quando o relatório não chegar

O Cowork **não avisa quando uma tarefa falha**. Relatório ausente na sexta é
sintoma, não silêncio: rode as consultas acima à mão pelo painel do Supabase
antes de assumir que a semana foi vazia. O estado real vive nas tabelas — é
exatamente por isso que ele não vive na cabeça do agente.
