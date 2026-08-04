/**
 * Marcação compartilhada dos campos de pauta — criar (`FormularioDePauta`) e
 * editar (`FormularioDeEdicao`) usam a mesma. Ficava embutida no formulário de
 * criar até a Rodada 15; saiu para cá quando editar precisou dos mesmos campos e
 * duplicar a régua de estilo (o `text-base` anti-zoom, a borda de foco) seria
 * abrir caminho para os dois divergirem em silêncio.
 */

// text-base (16px) não é escolha estética: abaixo disso o Safari do iPhone dá
// zoom sozinho ao focar o campo e a tela sai do lugar no meio da digitação.
export const CLASSE_CAMPO =
  "w-full rounded-lg border border-borda bg-superficie-alta px-3 py-3 text-base text-tinta outline-none focus:border-brasa";

export function Campo({
  nome,
  rotulo,
  dica,
  obrigatorio = false,
  children,
}: {
  nome: string;
  rotulo: string;
  dica: string;
  obrigatorio?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={nome} className="text-sm text-tinta">
        {rotulo}
        {obrigatorio ? (
          <span className="text-brasa"> *</span>
        ) : (
          <span className="text-tinta-fraca"> (opcional)</span>
        )}
      </label>
      {children}
      <p className="text-xs leading-relaxed text-tinta-fraca">{dica}</p>
    </div>
  );
}
