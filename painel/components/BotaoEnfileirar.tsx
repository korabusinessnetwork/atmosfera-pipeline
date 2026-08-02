"use client";

import { useActionState } from "react";

import { enfileirarPauta } from "@/app/acoes";
import { ACAO_OK } from "@/lib/tipos";

export default function BotaoEnfileirar({ pautaId }: { pautaId: string }) {
  const [estado, enfileirar, enfileirando] = useActionState(
    enfileirarPauta,
    ACAO_OK,
  );

  return (
    <form action={enfileirar} className="mt-4">
      <input type="hidden" name="pautaId" value={pautaId} />
      <button
        type="submit"
        disabled={enfileirando}
        className="min-h-12 w-full rounded-lg border border-brasa font-medium text-brasa disabled:opacity-50"
      >
        {enfileirando ? "Enfileirando…" : "Enfileirar render"}
      </button>
      {estado.erro && <p className="mt-2 text-sm text-brasa">{estado.erro}</p>}
    </form>
  );
}
