import type { EstadoDoWorker } from "@/lib/tipos";

const COR: Record<EstadoDoWorker["tom"], string> = {
  ok: "bg-sim",
  atencao: "bg-brasa",
  mudo: "bg-tinta-fraca",
};

/**
 * A linha de sinal de vida, no topo da fila.
 *
 * Existe por causa de uma ambiguidade que só aparece na tela vazia: "nada
 * esperando aprovação" pode significar que o worker trabalhou e a fila acabou,
 * ou que ele morreu às 3h e nunca mais vai chegar nada. As duas telas eram
 * idênticas — e a segunda é a que custa um dia de publicação.
 *
 * O ponto colorido é enfeite: a frase carrega o significado inteiro. Cor
 * sozinha não é informação para quem não distingue vermelho de verde, e este
 * painel é usado no celular, no escuro, de relance.
 */
export default function FaixaDoWorker({ estado }: { estado: EstadoDoWorker }) {
  return (
    <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-borda bg-superficie px-3 py-2.5">
      <span
        aria-hidden
        className={`mt-[0.3rem] size-2 shrink-0 rounded-full ${COR[estado.tom]}`}
      />
      <p className="min-w-0 text-xs leading-relaxed text-tinta-fraca">
        <span className="text-tinta">{estado.titulo}</span>
        {estado.detalhe ? ` · ${estado.detalhe}` : null}
      </p>
    </div>
  );
}
