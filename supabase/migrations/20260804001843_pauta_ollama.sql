-- ============================================================
-- PAUTA LOCAL (OLLAMA) + AUTO-ENFILEIRAR — Rodada 4
-- ============================================================
-- Duas mudanças de schema, e as duas existem para tirar o Cowork do caminho
-- crítico sem tocar no gate humano:
--
--   1. `origem` ganha um terceiro valor, 'ollama', e vira um `check`. Até aqui
--      a coluna era texto livre com um comentário — o relatório de sexta a lê
--      para separar o que a máquina escreveu do que uma pessoa digitou, então
--      ela carrega significado e merece constraint. Introduzir o terceiro valor
--      é o momento certo de fechar a porta contra typo.
--
--   2. Um trigger enfileira sozinho toda pauta pronta de PRODUTOR DE MÁQUINA
--      (cowork/ollama). É o "auto até o gate": a corrente anda de `pronta` até
--      `aguardando_aprovacao` sem ninguém abrir o painel, e PARA ali. Publicar
--      continua exigindo o humano (ADR-06).
--
-- Por que trigger e não um passo em Python: "mudança de comportamento começa no
-- schema" (CLAUDE.md). Qualquer produtor futuro que escreva uma pauta pronta de
-- máquina herda o enfileiramento sem uma linha de código nova. A tabela é o
-- contrato.
-- ============================================================

-- ============================================================
-- ORIGEM VIRA UM CHECK
-- ============================================================
-- Conferido antes de aplicar, contra o banco real: as únicas pautas existentes
-- têm origem = 'manual' (3 linhas). A constraint entra validada, não `not valid`.
alter table public.pautas
  add constraint pautas_origem_check
  check (origem in ('cowork', 'manual', 'ollama'));

comment on constraint pautas_origem_check on public.pautas is
  'origem carrega significado (o relatório de sexta a lê). Terceiro valor '
  '''ollama'' entra na Rodada 4, junto do produtor de pauta local.';

-- ============================================================
-- AUTO-ENFILEIRAR: pauta pronta de máquina vira vídeo na fila
-- ============================================================
-- Espelha o EFEITO de `enfileirar_pauta` (a RPC do painel), mas com duas
-- diferenças que importam:
--
--   * o org_id vem de `new.org_id`, não de `current_org_id()`. O produtor local
--     roda como service_role, sem sessão de usuário, onde `current_org_id()` é
--     nulo. A pauta já nasceu carimbada pelo produtor; o vídeo herda o mesmo.
--
--   * é só INSERT, nunca UPDATE. Em UPDATE→pronta apareceriam dois bugs:
--       (a) a própria atualização para 'em_producao', logo abaixo, re-dispararia
--           o trigger em recursão;
--       (b) `reprovar_video` devolve a pauta a 'pronta' quando não sobra vídeo
--           vivo (migration 20260802223612) — em UPDATE, reprovar re-renderizaria
--           sozinho e o gate humano viraria decoração. Reprovar NÃO retenta: é a
--           mesma regra de "falha de publicação vai para erro, não volta para
--           aprovado". Voltar à fila é decisão humana (o botão do painel).
--
-- `origem in ('cowork','ollama')`: só produtor de máquina. Pauta 'manual' nasce
-- pela mão de alguém que já está no painel — quem digitou aperta o botão de
-- enfileirar quando quiser. Auto-enfileirar a manual tiraria essa escolha.
create or replace function public.auto_enfileirar_pauta()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  insert into public.videos (org_id, pauta_id, status)
  values (new.org_id, new.id, 'na_fila');

  update public.pautas
     set status = 'em_producao'
   where id = new.id;

  return null;   -- AFTER trigger: o retorno é ignorado
end;
$$;

comment on function public.auto_enfileirar_pauta() is
  'Pauta pronta de produtor de máquina (cowork/ollama) -> um videos.na_fila + '
  'pauta em_producao. INSERT-only para não recursar nem re-render em reprovação.';

create trigger t_pautas_auto_enfileirar
  after insert on public.pautas
  for each row
  when (new.status = 'pronta' and new.origem in ('cowork', 'ollama'))
  execute function public.auto_enfileirar_pauta();
