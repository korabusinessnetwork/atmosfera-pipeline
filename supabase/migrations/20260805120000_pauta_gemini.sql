-- ============================================================
-- PAUTA VIA GEMINI (cold-start) — Rodada 20
-- ============================================================
-- Um quarto valor de `origem`, 'gemini', para o produtor opt-in que escreve
-- pauta com um modelo frontier durante o bootstrap (enquanto a tabela `metricas`
-- não tem histórico para treinar o modelo local). Duas mudanças de schema, e as
-- duas herdam o desenho da Rodada 4 sem tocar no gate humano:
--
--   1. O check de `origem` passa a aceitar 'gemini'. Como não se altera um
--      `check` in-place, é `drop constraint` + `add constraint` — validado, não
--      `not valid` (o novo valor só ALARGA o conjunto aceito; nenhuma linha
--      existente vira inválida). O relatório de sexta lê `origem` para separar o
--      que a máquina escreveu do que uma pessoa digitou, então a coluna carrega
--      significado e merece continuar sob constraint.
--
--   2. O trigger `t_pautas_auto_enfileirar` (Rodada 4) passa a disparar também
--      para 'gemini'. O `when` vive na DEFINIÇÃO do trigger, não na função —
--      então é `drop trigger` + `create trigger`, e a função
--      `auto_enfileirar_pauta()` NÃO muda (segue INSERT-only, sem security
--      definer). Pauta 'gemini' pronta vira `videos.na_fila` sozinha e para no
--      gate, exatamente como 'ollama'/'cowork'.
--
-- O Gemini é ferramenta manual de bootstrap (opt-in, fora do loop). A invariante
-- continua de pé: quem gera pauta só escreve em `pautas`; quem cria o vídeo é o
-- trigger. A tabela é o contrato.
-- ============================================================

-- ============================================================
-- ORIGEM: 'gemini' entra no check
-- ============================================================
-- Conferido: alargar o conjunto aceito nunca invalida linha existente, então a
-- constraint entra validada (sem `not valid`).
alter table public.pautas
  drop constraint pautas_origem_check;

alter table public.pautas
  add constraint pautas_origem_check
  check (origem in ('cowork', 'manual', 'ollama', 'gemini'));

comment on constraint pautas_origem_check on public.pautas is
  'origem carrega significado (o relatório de sexta a lê). Quarto valor '
  '''gemini'' entra na Rodada 20, junto do produtor de pauta opt-in de '
  'cold-start (modelo frontier durante o bootstrap).';

-- ============================================================
-- AUTO-ENFILEIRAR: 'gemini' também é produtor de máquina
-- ============================================================
-- A função não muda (o `when` mora no trigger). Recriar o trigger é a única forma
-- de alargar o `when` para incluir 'gemini'.
drop trigger t_pautas_auto_enfileirar on public.pautas;

create trigger t_pautas_auto_enfileirar
  after insert on public.pautas
  for each row
  when (new.status = 'pronta' and new.origem in ('cowork', 'ollama', 'gemini'))
  execute function public.auto_enfileirar_pauta();
