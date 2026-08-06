-- Recuperação one-off: devolve à fila os vídeos que caíram em 'erro' por causa
-- de infra (MPT desligado — WinError 10061 na porta 8080), não por conteúdo.
-- Zera o contador de tentativas e limpa o lock/erro para o claim pegar de novo.
--
-- Rodar com o MPT JÁ DE PÉ:
--   supabase db query --linked -f supabase/reprocessar_erros.sql
--
-- Seguro: só toca linhas em 'erro'; não mexe em aprovação, publicação ou pauta.
update public.videos
   set status     = 'na_fila',
       tentativas = 0,
       locked_by  = null,
       locked_at  = null,
       erro_msg   = null
 where status = 'erro';
