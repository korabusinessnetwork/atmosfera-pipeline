-- ============================================================
-- SEMENTE DE DESENVOLVIMENTO — atmosfera-pipeline
-- ============================================================
-- Põe trabalho na fila para o worker ter o que fazer antes de o Cowork
-- existir. Rodar com:
--
--   supabase db query --linked -f supabase/seeds/dev_seed.sql
--
-- É re-executável: limpa as próprias linhas ([dev] no tema) antes de semear,
-- então rodar dez vezes deixa o mesmo estado que rodar uma.
--
-- NÃO é migration: não vai para produção e não entra em supabase/migrations/.
--
-- SQL puro, sem meta-comando de psql (`\set` não existe do outro lado da
-- Management API, que é por onde o `supabase db query` fala com o banco).
-- ============================================================

do $$
declare
  -- Org de desenvolvimento. Tem que casar com o ORG_ID do worker/.env.
  -- Em produção o org_id vem de app_metadata.org_id no JWT (public.current_org_id).
  v_org uuid := '0f927960-fa0d-4694-84da-366e8aaaed46';
begin
  -- ---------- limpeza das linhas anteriores ----------
  -- videos e publicacoes caem junto (FK on delete cascade).
  delete from public.pautas where tema like '[dev]%';

  -- ---------- pautas prontas ----------
  insert into public.pautas
    (org_id, tema, roteiro, hook, titulo, descricao, status, origem, prioridade)
  values
    (v_org,
     '[dev] Disciplina não é motivação',
     E'A motivação te acorda.\nA disciplina te levanta.\nUma é clima.\nA outra é escolha.\nTodo dia.',
     'A motivação te abandona no terceiro dia.',
     'Disciplina não é motivação',
     E'Sobre o que sobra quando a vontade acaba.\n#atmosferaviral #mindset #disciplina',
     'pronta', 'manual', 10),

    (v_org,
     '[dev] O silêncio como método',
     E'Todo mundo fala.\nQuase ninguém escuta.\nO silêncio não é ausência.\nÉ filtro.\nUse.',
     'Você não precisa responder tudo.',
     'O silêncio como método',
     E'Sobre falar menos e pesar mais.\n#atmosferaviral #aesthetic #mindset',
     'pronta', 'manual', 5),

    -- Tema em CJK de propósito: exercita o fallback do slug no nome do arquivo.
    (v_org,
     '[dev] 亡者',
     E'Toda versão nova pede uma morte.\nA antiga não sai sozinha.\nVocê escolhe o que enterra.\nOu carrega.\nPara sempre.',
     'Alguma versão sua precisa morrer hoje.',
     '亡者 — o que morre em você',
     E'Sobre soltar o que já era.\n#atmosferaviral #亡者 #mindset',
     'pronta', 'manual', 1);

  -- ---------- enfileira um render por pauta ----------
  -- É o que o painel vai fazer na Sprint 6, no botão "enfileirar render".
  -- Ordem de consumo é por created_at (claim_proximo_video), não por
  -- prioridade — `prioridade` aqui é só fidelidade de dado.
  insert into public.videos (org_id, pauta_id, status)
  select org_id, id, 'na_fila'
    from public.pautas
   where tema like '[dev]%';

  update public.pautas set status = 'em_producao' where tema like '[dev]%';
end $$;

-- ---------- confirmação ----------
select v.status, count(*) as quantidade
  from public.videos v
  join public.pautas p on p.id = v.pauta_id
 where p.tema like '[dev]%'
 group by v.status
 order by v.status;
