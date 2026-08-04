"use client";

import { useActionState, useState } from "react";

import { descartarPauta } from "@/app/acoes";
import { ACAO_OK } from "@/lib/tipos";

/**
 * Descartar é TERMINAL: a pauta sai da lista e o painel não a traz de volta
 * (`descartada` fica fora do USING das políticas — ressuscitar é SQL com
 * service_role). Por isso a confirmação em dois toques, sem diálogo: o primeiro
 * arma, o segundo confirma, e "Não" desarma. Um toque errado no ônibus não mata
 * uma pauta.
 */
export default function BotaoDescartar({ pautaId }: { pautaId: string }) {
  const [estado, descartar, descartando] = useActionState(
    descartarPauta,
    ACAO_OK,
  );
  const [armado, setArmado] = useState(false);

  if (!armado) {
    return (
      <div className="mt-2">
        <button
          type="button"
          onClick={() => setArmado(true)}
          className="min-h-12 w-full rounded-lg border border-borda font-medium text-tinta-fraca"
        >
          Descartar
        </button>
        {estado.erro && <p className="mt-2 text-sm text-brasa">{estado.erro}</p>}
      </div>
    );
  }

  return (
    <form action={descartar} className="mt-2 flex gap-2">
      <input type="hidden" name="pautaId" value={pautaId} />
      <button
        type="button"
        onClick={() => setArmado(false)}
        disabled={descartando}
        className="min-h-12 flex-1 rounded-lg border border-borda font-medium text-tinta-fraca disabled:opacity-50"
      >
        Não
      </button>
      <button
        type="submit"
        disabled={descartando}
        className="min-h-12 flex-1 rounded-lg border border-brasa font-medium text-brasa disabled:opacity-50"
      >
        {descartando ? "Descartando…" : "Confirmar descarte"}
      </button>
    </form>
  );
}
