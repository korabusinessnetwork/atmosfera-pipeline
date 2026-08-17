-- ============================================================
-- AS HASHTAGS PADRÃO VIRAM DO CANAL QUE EXISTE HOJE — Rodada 32
-- ============================================================
-- O default de `pautas.hashtags` é de 2026-08-01, escrito no init do schema:
--
--   array['#atmosferaviral','#mindset','#aesthetic','#disciplina','#亡者']
--
-- Ele nunca foi revisitado. Três dias depois, na Rodada 5, o canal virou en-US
-- por decisão do dono ("dá mais dinheiro"): `00_IDENTIDADE.md` foi reescrito em
-- inglês, `MPT_VOZ` virou voz en-US, e o upload passou a declarar
-- `defaultLanguage`/`defaultAudioLanguage = en-US`. A lista de hashtags ficou
-- para trás, e ela é metadado PÚBLICO — vai para `snippet.tags` e para a
-- descrição de todo vídeo do canal.
--
-- O que isso publica hoje, em cada vídeo:
--
--   `#disciplina`   português num canal que declara en-US. A tag existe e tem
--                   volume — em PORTUGUÊS. Ela não erra por ser inútil; erra por
--                   funcionar, puxando o vídeo para um público que não fala a
--                   língua da narração e que sai nos primeiros segundos. Sinal
--                   contraditório é pior que sinal ausente.
--   `#亡者`         a assinatura da marca, que é ÓTIMA queimada no canto do
--                   vídeo (é o que dá continuidade entre um vídeo e outro) e é
--                   ruim como tag: ninguém busca por ela, e CJK num canal en-US
--                   é mais um sinal de idioma trocado. A marca continua no
--                   pixel, onde ela sempre funcionou.
--   `#atmosferaviral`  nome do canal, volume zero. Tag de marca só trabalha
--                   depois que a marca é buscada; antes disso é espaço gasto.
--
-- ---------------------------------------------------------------
-- POR QUE MEXER NO DEFAULT E NÃO NAS LINHAS EXISTENTES
-- ---------------------------------------------------------------
-- Esta migration troca **só o default da coluna**. As pautas já escritas ficam
-- como estão, de propósito: `hashtags` é conteúdo, e reescrever conteúdo de linha
-- existente por migration é o tipo de coisa que ninguém revisa em diff e que
-- ninguém consegue desfazer depois. As pautas antigas do alvo de duração velho
-- já vão ser descartadas à mão (item 24b do § 8); as novas nascem certas.
--
-- E o publisher não depende disto para melhorar: `youtube.tags_do_tema()` deriva
-- tag do tema da pauta a cada vídeo, então mesmo uma pauta antiga sobe com tag
-- que descreve o vídeo. Este default é o piso, não o conteúdo.
--
-- ---------------------------------------------------------------
-- SEM RLS, SEM POLÍTICA, SEM GRANT
-- ---------------------------------------------------------------
-- `alter column ... set default` não cria objeto, não muda quem enxerga o quê e
-- não abre caminho de escrita novo — `hashtags` continua fora do GRANT por coluna
-- do painel (`20260803013643_pauta_manual.sql`), então o formulário do celular
-- segue sem poder escrever nesta coluna. `rls_test.sql` fica nos mesmos casos.

alter table public.pautas
  alter column hashtags set default array[
    '#mindset', '#discipline', '#motivation', '#selfimprovement', '#mentality'
  ];

comment on column public.pautas.hashtags is
  'Hashtags da marca, em inglês (o canal é en-US desde a R5). São o PISO do '
  'metadado: o publisher (youtube.tags_do_tema) acrescenta tags derivadas do '
  'tema de cada pauta e a tag de formato #Shorts. A assinatura 亡者 é marca '
  'VISUAL (queimada no canto pelo postprocess), nunca tag — CJK num canal '
  'en-US é sinal de idioma trocado.';
