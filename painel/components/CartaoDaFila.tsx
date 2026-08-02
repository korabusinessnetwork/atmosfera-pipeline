import AcoesDoGate from "@/components/AcoesDoGate";
import { duracao, quando } from "@/lib/formato";
import type { VideoDaFila } from "@/lib/tipos";

export default function CartaoDaFila({
  video,
  previewUrl,
  thumbUrl,
}: {
  video: VideoDaFila;
  previewUrl: string | null;
  thumbUrl: string | null;
}) {
  const pauta = video.pauta;

  return (
    <article className="overflow-hidden rounded-lg border border-borda bg-superficie">
      {previewUrl ? (
        <video
          src={previewUrl}
          poster={thumbUrl ?? undefined}
          controls
          playsInline
          // metadata, não auto: a fila abre com vários cards e o celular está
          // no 4G. Baixar 5 MB de cada vídeo antes de alguém tocar em play
          // gastaria a franquia para julgar um vídeo.
          preload="metadata"
          className="aspect-[9/16] w-full bg-black"
        />
      ) : (
        <div className="flex aspect-[9/16] w-full items-center justify-center bg-black px-6 text-center text-sm text-tinta-fraca">
          Preview indisponível — o arquivo está no PC e o vídeo continua
          aprovável.
        </div>
      )}

      <div className="p-4">
        <h2 className="text-base leading-snug font-medium">
          {pauta?.tema ?? "Pauta removida"}
        </h2>

        {pauta?.hook && (
          // O hook decide os primeiros 1,5s, que decidem a retenção. É a única
          // linha que merece destaque numa tela de decisão rápida.
          <p className="mt-3 border-l-2 border-brasa pl-3 text-sm leading-relaxed text-tinta">
            {pauta.hook}
          </p>
        )}

        {pauta?.titulo && (
          <p className="mt-3 text-sm leading-relaxed text-tinta-fraca">
            <span className="text-tinta-fraca/70">Título: </span>
            {pauta.titulo}
          </p>
        )}

        <p className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-tinta-fraca">
          <span>{quando(video.created_at)}</span>
          <span>{duracao(video.duracao_seg)}</span>
          {video.tentativas > 1 && (
            <span className="text-brasa">tentativa {video.tentativas}</span>
          )}
        </p>
      </div>

      <AcoesDoGate videoId={video.id} />
    </article>
  );
}
