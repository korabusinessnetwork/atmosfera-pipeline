import { clienteServidor } from "@/lib/supabase/server";
import { assinarPreviews } from "@/lib/storage";
import CartaoDaFila from "@/components/CartaoDaFila";
import Vazio from "@/components/Vazio";
import type { VideoDaFila } from "@/lib/tipos";

/**
 * A fila: o gate humano.
 *
 * Nenhum filtro por org_id na query, e isso é o desenho inteiro do projeto —
 * `videos_leitura` já restringe a org do JWT. Filtrar aqui também não somaria
 * segurança (a política vale de qualquer jeito) e criaria a ilusão de que a
 * proteção mora no painel. Ela mora no banco.
 */
export default async function Fila() {
  const supabase = await clienteServidor();

  const { data, error } = await supabase
    .from("videos")
    .select(
      "id, created_at, duracao_seg, preview_url, thumb_url, tentativas, pauta:pautas(tema, hook, titulo, descricao)",
    )
    .eq("status", "aguardando_aprovacao")
    .order("created_at", { ascending: true });

  if (error) {
    return (
      <Vazio
        titulo="Não deu para carregar a fila."
        detalhe="Puxe a tela para recarregar. Se persistir, saia e entre de novo."
      />
    );
  }

  const videos = (data ?? []) as unknown as VideoDaFila[];

  // Uma chamada só para a lista inteira, antes de renderizar. Assinar dentro do
  // map daria uma ida ao Storage por card, em série.
  const urls = await assinarPreviews(supabase, [
    ...videos.map((v) => v.preview_url),
    ...videos.map((v) => v.thumb_url),
  ]);

  if (videos.length === 0) {
    return (
      <Vazio
        titulo="Nada esperando aprovação."
        detalhe="Quando o worker terminar um render, ele aparece aqui — com o vídeo pronto para assistir."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {videos.map((video) => (
        <CartaoDaFila
          key={video.id}
          video={video}
          previewUrl={
            video.preview_url ? (urls.get(video.preview_url) ?? null) : null
          }
          thumbUrl={video.thumb_url ? (urls.get(video.thumb_url) ?? null) : null}
        />
      ))}
    </div>
  );
}
