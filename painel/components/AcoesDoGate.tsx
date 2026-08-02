"use client";

import { useActionState, useState } from "react";

import { aprovarVideo, reprovarVideo } from "@/app/acoes";
import { ACAO_OK } from "@/lib/tipos";

export default function AcoesDoGate({ videoId }: { videoId: string }) {
  const [aprovacao, aprovar, aprovando] = useActionState(aprovarVideo, ACAO_OK);
  const [reprovacao, reprovar, reprovando] = useActionState(
    reprovarVideo,
    ACAO_OK,
  );
  const [motivoAberto, setMotivoAberto] = useState(false);

  const ocupado = aprovando || reprovando;
  const erro = aprovacao.erro ?? reprovacao.erro;

  return (
    <div className="border-t border-borda p-3">
      {!motivoAberto ? (
        <div className="flex gap-2">
          <form action={aprovar} className="flex-1">
            <input type="hidden" name="videoId" value={videoId} />
            <button
              type="submit"
              disabled={ocupado}
              // min-h-12: alvo de toque de polegar. Botão de 32px erra, e errar
              // aqui significa publicar o que ia ser reprovado.
              className="min-h-12 w-full rounded-lg bg-sim font-medium text-tinta disabled:opacity-50"
            >
              {aprovando ? "Aprovando…" : "Aprovar"}
            </button>
          </form>
          <button
            type="button"
            disabled={ocupado}
            onClick={() => setMotivoAberto(true)}
            className="min-h-12 flex-1 rounded-lg border border-nao font-medium text-nao disabled:opacity-50"
          >
            Reprovar
          </button>
        </div>
      ) : (
        <form action={reprovar} className="flex flex-col gap-2">
          <input type="hidden" name="videoId" value={videoId} />
          <textarea
            name="motivo"
            rows={2}
            maxLength={500}
            autoFocus
            placeholder="Motivo (opcional) — ex.: legenda cortada"
            className="w-full resize-none rounded-lg border border-borda bg-superficie-alta px-3 py-2 text-tinta outline-none placeholder:text-tinta-fraca/60 focus:border-brasa"
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={ocupado}
              onClick={() => setMotivoAberto(false)}
              className="min-h-12 flex-1 rounded-lg border border-borda text-tinta-fraca disabled:opacity-50"
            >
              Voltar
            </button>
            <button
              type="submit"
              disabled={ocupado}
              className="min-h-12 flex-1 rounded-lg bg-nao font-medium text-tinta disabled:opacity-50"
            >
              {reprovando ? "Reprovando…" : "Confirmar"}
            </button>
          </div>
        </form>
      )}

      {erro && <p className="mt-2 text-sm text-brasa">{erro}</p>}
    </div>
  );
}
