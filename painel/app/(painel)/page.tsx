import { clienteServidor } from "@/lib/supabase/server";
import { assinarPreviews } from "@/lib/storage";
import { lerBatimento } from "@/lib/saude";
import CartaoDaFila from "@/components/CartaoDaFila";
import FaixaDoWorker from "@/components/FaixaDoWorker";
import Vazio from "@/components/Vazio";
import type { Batimento, VideoDaFila } from "@/lib/tipos";

/**
 * A fila: o gate humano.
 *
 * Nenhum filtro por org_id nas queries, e isso é o desenho inteiro do projeto —
 * `videos_leitura` e `batimentos_leitura` já restringem à org do JWT. Filtrar
 * aqui também não somaria segurança (a política vale de qualquer jeito) e
 * criaria a ilusão de que a proteção mora no painel. Ela mora no banco.
 */
export default async function Fila() {
  const supabase = await clienteServidor();

  // Em paralelo: uma tela que espera o batimento para só então pedir a fila
  // fica dois round-trips mais lenta no 4G, e o batimento é o menos urgente dos
  // dois.
  const [fila, batimento] = await Promise.all([
    supabase
      .from("videos")
      .select(
        "id, created_at, duracao_seg, preview_url, thumb_url, tentativas, pauta:pautas(tema, hook, titulo, descricao)",
      )
      .eq("status", "aguardando_aprovacao")
      .order("created_at", { ascending: true }),
    supabase.rpc("saude_workers"),
  ]);

  // `null` e `[]` dizem coisas diferentes: erro de leitura vira "não sei", fila
  // vazia de batimento vira "ninguém bateu ainda". Colapsar os dois faria o
  // painel acusar worker morto toda vez que o Supabase espirrasse.
  const estado = lerBatimento(
    batimento.error ? null : ((batimento.data ?? []) as Batimento[]),
  );

  if (fila.error) {
    return (
      <>
        <FaixaDoWorker estado={estado} />
        <Vazio
          titulo="Não deu para carregar a fila."
          detalhe="Puxe a tela para recarregar. Se persistir, saia e entre de novo."
        />
      </>
    );
  }

  const videos = (fila.data ?? []) as unknown as VideoDaFila[];

  if (videos.length === 0) {
    return (
      <>
        <FaixaDoWorker estado={estado} />
        <Vazio
          titulo="Nada esperando aprovação."
          detalhe="Quando o worker terminar um render, ele aparece aqui — com o vídeo pronto para assistir."
        />
      </>
    );
  }

  // Uma chamada só para a lista inteira, antes de renderizar. Assinar dentro do
  // map daria uma ida ao Storage por card, em série.
  const urls = await assinarPreviews(supabase, [
    ...videos.map((v) => v.preview_url),
    ...videos.map((v) => v.thumb_url),
  ]);

  return (
    <>
      <FaixaDoWorker estado={estado} />
      <div className="flex flex-col gap-4">
        {videos.map((video) => (
          <CartaoDaFila
            key={video.id}
            video={video}
            previewUrl={
              video.preview_url ? (urls.get(video.preview_url) ?? null) : null
            }
            thumbUrl={
              video.thumb_url ? (urls.get(video.thumb_url) ?? null) : null
            }
          />
        ))}
      </div>
    </>
  );
}
