import type { SupabaseClient } from "@supabase/supabase-js";

const BUCKET = "atmosfera";

/**
 * Dez minutos. Tempo de assistir a um vídeo de 10s e decidir, não de guardar.
 *
 * A URL assinada É a credencial do arquivo: quem tem o link lê o vídeo, logado
 * ou não. Por isso ela nasce a cada render e nunca é gravada em lugar nenhum —
 * `videos.preview_url` guarda o CAMINHO no Storage, não a URL. A Sprint 3
 * decidiu isso; o painel é quem cumpre. Persistir uma URL assinada seria
 * guardar bearer token em texto plano numa coluna, e o CLAUDE.md proíbe até
 * *logar* uma dessas.
 */
const VALIDADE_SEG = 600;

/**
 * Assina vários caminhos de uma vez e devolve caminho -> URL.
 *
 * Uma chamada só para a lista inteira: assinar dentro do map da lista daria
 * uma ida ao Storage por card, em série, num celular no 4G.
 *
 * Falha de assinatura não derruba a página — devolve o mapa sem a entrada, e o
 * card mostra "preview indisponível". O vídeo continua no disco do worker e
 * continua aprovável; ficar sem imagem é chato, ficar sem gate é pior.
 */
export async function assinarPreviews(
  supabase: SupabaseClient,
  caminhos: (string | null | undefined)[],
): Promise<Map<string, string>> {
  const mapa = new Map<string, string>();

  const limpos = [
    ...new Set(caminhos.filter((c): c is string => typeof c === "string" && c.length > 0)),
  ];
  if (limpos.length === 0) return mapa;

  const { data, error } = await supabase.storage
    .from(BUCKET)
    .createSignedUrls(limpos, VALIDADE_SEG);

  if (error || !data) return mapa;

  for (const item of data) {
    if (item.path && item.signedUrl && !item.error) {
      mapa.set(item.path, item.signedUrl);
    }
  }

  return mapa;
}
