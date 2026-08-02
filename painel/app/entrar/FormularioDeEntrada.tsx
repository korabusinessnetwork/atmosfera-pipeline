"use client";

import { useActionState } from "react";

import { LINK_INICIAL } from "@/lib/tipos";
import { enviarLink } from "./acoes";

export default function FormularioDeEntrada({
  linkInvalido,
}: {
  linkInvalido: boolean;
}) {
  const [estado, enviar, enviando] = useActionState(enviarLink, LINK_INICIAL);

  if (estado.enviado) {
    return (
      <div className="rounded-lg border border-borda bg-superficie p-5 text-sm leading-relaxed">
        <p className="text-tinta">Link enviado.</p>
        <p className="mt-2 text-tinta-fraca">
          Abra o e-mail neste mesmo aparelho. O link vale por pouco tempo e só
          funciona uma vez.
        </p>
      </div>
    );
  }

  return (
    <form action={enviar} className="flex flex-col gap-3">
      <label htmlFor="email" className="text-sm text-tinta-fraca">
        E-mail
      </label>
      <input
        id="email"
        name="email"
        type="email"
        inputMode="email"
        autoComplete="email"
        autoCapitalize="none"
        autoCorrect="off"
        required
        placeholder="voce@exemplo.com"
        className="w-full rounded-lg border border-borda bg-superficie px-4 py-3 text-tinta outline-none placeholder:text-tinta-fraca/60 focus:border-brasa"
      />

      {(estado.erro || linkInvalido) && (
        <p className="text-sm text-brasa">
          {estado.erro ??
            "Esse link não vale mais — expirou ou já foi usado. Peça outro."}
        </p>
      )}

      <button
        type="submit"
        disabled={enviando}
        className="mt-1 rounded-lg bg-brasa px-4 py-3 font-medium text-fundo disabled:opacity-50"
      >
        {enviando ? "Enviando…" : "Receber link de acesso"}
      </button>

      <p className="mt-1 text-xs leading-relaxed text-tinta-fraca">
        Sem senha. Chega um link no e-mail e ele te loga.
      </p>
    </form>
  );
}
