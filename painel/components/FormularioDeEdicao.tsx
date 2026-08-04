"use client";

import { useActionState } from "react";

import { editarPauta } from "@/app/acoes";
import { EDICAO_INICIAL, type PautaPronta } from "@/lib/tipos";
import { Campo, CLASSE_CAMPO } from "@/components/CamposDePauta";

/**
 * Editar o conteúdo de uma pauta pronta, pelo celular.
 *
 * Fica num `<details>` fechado dentro do card — a tela existe para enfileirar
 * render, e cinco campos abertos por card empurrariam a lista para fora do
 * primeiro toque. Diferente do formulário de criar, os campos vêm PRÉ-PREENCHIDOS
 * (`defaultValue`) com o que está no banco, e NÃO remontam no sucesso: depois de
 * salvar, a pessoa quer ver o texto que acabou de editar, não campos vazios. A
 * lista atrás re-renderiza (o `refresh()` da action), então o card reflete o novo
 * valor mesmo com o `<details>` fechado.
 */
export default function FormularioDeEdicao({ pauta }: { pauta: PautaPronta }) {
  const [estado, editar, editando] = useActionState(editarPauta, EDICAO_INICIAL);

  return (
    <details className="mt-2 rounded-lg border border-borda">
      <summary className="flex min-h-12 cursor-pointer list-none items-center px-4 font-medium text-tinta-fraca">
        Editar
      </summary>

      <form action={editar} className="flex flex-col gap-4 p-4 pt-0">
        <input type="hidden" name="pautaId" value={pauta.id} />

        <Campo nome={`tema-${pauta.id}`} rotulo="Tema" obrigatorio dica="Uma linha. É o que a lista mostra.">
          <input
            id={`tema-${pauta.id}`}
            name="tema"
            required
            maxLength={300}
            autoComplete="off"
            defaultValue={pauta.tema}
            className={CLASSE_CAMPO}
          />
        </Campo>

        <Campo
          nome={`roteiro-${pauta.id}`}
          rotulo="Roteiro"
          obrigatorio
          dica="5 linhas, 8–12s no total. Sem ele o vídeo não renderiza."
        >
          <textarea
            id={`roteiro-${pauta.id}`}
            name="roteiro"
            required
            rows={6}
            maxLength={5000}
            defaultValue={pauta.roteiro ?? ""}
            className={`${CLASSE_CAMPO} resize-y`}
          />
        </Campo>

        <Campo nome={`hook-${pauta.id}`} rotulo="Hook" dica="A primeira linha, que segura 1,5s. Vazio = sem cartela.">
          <input
            id={`hook-${pauta.id}`}
            name="hook"
            maxLength={300}
            autoComplete="off"
            defaultValue={pauta.hook ?? ""}
            className={CLASSE_CAMPO}
          />
        </Campo>

        <Campo nome={`titulo-${pauta.id}`} rotulo="Título" dica="YouTube. Vazio = usa o tema. Até 60 aparece inteiro.">
          <input
            id={`titulo-${pauta.id}`}
            name="titulo"
            maxLength={100}
            autoComplete="off"
            defaultValue={pauta.titulo ?? ""}
            className={CLASSE_CAMPO}
          />
        </Campo>

        <Campo nome={`descricao-${pauta.id}`} rotulo="Descrição" dica="Duas linhas. As hashtags da marca entram sozinhas.">
          <textarea
            id={`descricao-${pauta.id}`}
            name="descricao"
            rows={3}
            maxLength={2000}
            defaultValue={pauta.descricao ?? ""}
            className={`${CLASSE_CAMPO} resize-y`}
          />
        </Campo>

        {estado.erro && <p className="text-sm text-brasa">{estado.erro}</p>}

        {!estado.erro && estado.salvo > 0 && (
          <p className="text-sm text-sim">Alterações salvas.</p>
        )}

        <button
          type="submit"
          disabled={editando}
          className="min-h-12 w-full rounded-lg border border-brasa font-medium text-brasa disabled:opacity-50"
        >
          {editando ? "Salvando…" : "Salvar alterações"}
        </button>
      </form>
    </details>
  );
}
