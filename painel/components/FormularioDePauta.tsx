"use client";

import { useActionState } from "react";

import { criarPauta } from "@/app/acoes";
import { PAUTA_INICIAL } from "@/lib/tipos";
import { Campo, CLASSE_CAMPO } from "@/components/CamposDePauta";

/**
 * Nova pauta, à mão, pelo celular.
 *
 * Fica dentro de um `<details>` fechado: a tela de pautas existe para
 * enfileirar render, e um formulário de cinco campos aberto por padrão empurraria
 * a lista para fora do primeiro toque. `<details>` também resolve o
 * abrir/fechar sem estado nenhum — é o navegador que guarda.
 *
 * `key={estado.criadas}` no formulário: no sucesso o número muda, o React
 * remonta e os campos voltam ao vazio. É o único jeito de limpar campo não
 * controlado sem depender do reset automático do React, que só acontece em
 * algumas formas de action e mudaria sem avisar.
 */
export default function FormularioDePauta() {
  const [estado, criar, criando] = useActionState(criarPauta, PAUTA_INICIAL);

  return (
    <details className="rounded-lg border border-borda bg-superficie">
      <summary className="flex min-h-12 cursor-pointer list-none items-center px-4 font-medium text-brasa">
        + Nova pauta
      </summary>

      <form key={estado.criadas} action={criar} className="flex flex-col gap-4 p-4 pt-0">
        <Campo
          nome="tema"
          rotulo="Tema"
          obrigatorio
          dica="Uma linha. É o que a lista mostra."
        >
          <input
            id="tema"
            name="tema"
            required
            maxLength={300}
            autoComplete="off"
            className={CLASSE_CAMPO}
          />
        </Campo>

        <Campo
          nome="roteiro"
          rotulo="Roteiro"
          obrigatorio
          // Não é regra de estilo: sem roteiro o render falha DEPOIS do claim e
          // queima uma das três tentativas do vídeo. O banco recusa; o aviso
          // aqui é para ninguém descobrir isso pelo erro.
          dica="5 linhas, 8–12s no total. Sem ele o vídeo não renderiza."
        >
          <textarea
            id="roteiro"
            name="roteiro"
            required
            rows={6}
            maxLength={5000}
            className={`${CLASSE_CAMPO} resize-y`}
          />
        </Campo>

        <Campo
          nome="hook"
          rotulo="Hook"
          dica="A primeira linha, que segura 1,5s. Vazio = sem cartela."
        >
          <input
            id="hook"
            name="hook"
            maxLength={300}
            autoComplete="off"
            className={CLASSE_CAMPO}
          />
        </Campo>

        <Campo
          nome="titulo"
          rotulo="Título"
          dica="YouTube. Vazio = usa o tema. Até 60 aparece inteiro."
        >
          <input
            id="titulo"
            name="titulo"
            maxLength={100}
            autoComplete="off"
            className={CLASSE_CAMPO}
          />
        </Campo>

        <Campo nome="descricao" rotulo="Descrição" dica="Duas linhas. As hashtags da marca entram sozinhas.">
          <textarea
            id="descricao"
            name="descricao"
            rows={3}
            maxLength={2000}
            className={`${CLASSE_CAMPO} resize-y`}
          />
        </Campo>

        {estado.erro && <p className="text-sm text-brasa">{estado.erro}</p>}

        {!estado.erro && estado.criadas > 0 && (
          <p className="text-sm text-sim">
            Pauta criada. Ela está na lista, pronta para enfileirar.
          </p>
        )}

        <button
          type="submit"
          disabled={criando}
          className="min-h-12 w-full rounded-lg bg-brasa font-medium text-fundo disabled:opacity-50"
        >
          {criando ? "Criando…" : "Criar pauta"}
        </button>
      </form>
    </details>
  );
}
