import { clienteServidor } from "@/lib/supabase/server";
import Vazio from "@/components/Vazio";
import { quando } from "@/lib/formato";
import type { PublicacaoDoHistorico } from "@/lib/tipos";

const ROTULO: Record<PublicacaoDoHistorico["status"], string> = {
  pendente: "na fila",
  enviado: "enviado",
  publicado: "publicado",
  erro: "erro",
};

const COR: Record<PublicacaoDoHistorico["status"], string> = {
  pendente: "border-borda text-tinta-fraca",
  enviado: "border-borda text-tinta",
  publicado: "border-sim text-sim",
  erro: "border-nao text-nao",
};

const PLATAFORMA: Record<PublicacaoDoHistorico["plataforma"], string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
};

/**
 * O rascunho está na caixa do TikTok e só uma pessoa fecha a publicação.
 *
 * Isto não é enfeite. O worker usa o endpoint de inbox (escopo `video.upload`),
 * que aceita **só** `source_info` — não existe campo `is_aigc`, nem legenda, nem
 * privacidade. O `is_aigc` mora no direct post, que o projeto não usa porque
 * cliente não auditado é forçado a SELF_ONLY lá (ADR-06). Consequência: o
 * rótulo de conteúdo gerado por IA só pode ser marcado no app, à mão, e ele é
 * obrigatório nas duas plataformas — sem ele a política prevê remoção.
 *
 * Este é o único lugar do sistema onde isso pode ser dito para uma pessoa na
 * hora em que ela precisa agir. O worker escreve `falta_marcar_ia` no log, mas
 * ninguém lê log do worker no celular.
 */
function faltaPostarNoTikTok(pub: PublicacaoDoHistorico): boolean {
  return pub.plataforma === "tiktok" && pub.status === "enviado";
}

export default async function Historico() {
  const supabase = await clienteServidor();

  const { data, error } = await supabase
    .from("publicacoes")
    .select(
      "id, plataforma, status, url, agendado_para, publicado_em, erro_msg, created_at, video:videos(id, thumb_url, pauta:pautas(tema, titulo))",
    )
    .order("created_at", { ascending: false })
    .limit(50);

  if (error) {
    return (
      <Vazio
        titulo="Não deu para carregar o histórico."
        detalhe="Puxe a tela para recarregar. Se persistir, saia e entre de novo."
      />
    );
  }

  const publicacoes = (data ?? []) as unknown as PublicacaoDoHistorico[];

  if (publicacoes.length === 0) {
    return (
      <Vazio
        titulo="Nada publicado ainda."
        detalhe="Cada linha aqui é um vídeo numa plataforma. Aparecem depois que você aprova e o worker envia."
      />
    );
  }

  return (
    <ul className="flex flex-col gap-3">
      {publicacoes.map((pub) => (
        <li
          key={pub.id}
          className="rounded-lg border border-borda bg-superficie p-4"
        >
          <div className="flex items-start justify-between gap-3">
            <p className="min-w-0 text-sm leading-snug">
              {pub.video?.pauta?.tema ?? "—"}
            </p>
            <span
              className={`mt-0.5 shrink-0 rounded-full border px-2 py-0.5 text-xs ${COR[pub.status]}`}
            >
              {ROTULO[pub.status]}
            </span>
          </div>

          <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-tinta-fraca">
            <span className="text-tinta">{PLATAFORMA[pub.plataforma]}</span>
            {pub.publicado_em ? (
              <span>publicado {quando(pub.publicado_em)}</span>
            ) : pub.agendado_para ? (
              <span>agendado {quando(pub.agendado_para)}</span>
            ) : (
              <span>criado {quando(pub.created_at)}</span>
            )}
          </p>

          {/* erro_msg vem de descrever_erro() no worker, que já corta a URI da
              requisição — a de upload resumable leva credencial no query
              string. Aqui é status + motivo, nunca a exceção crua. */}
          {pub.erro_msg && (
            <p className="mt-2 text-xs leading-relaxed text-nao">
              {pub.erro_msg}
            </p>
          )}

          {faltaPostarNoTikTok(pub) && (
            <p className="mt-3 rounded border border-brasa/40 bg-brasa/10 px-3 py-2 text-xs leading-relaxed text-tinta">
              Está na sua caixa de entrada do TikTok, como rascunho. Abra o app
              para escrever a legenda e{" "}
              <strong className="font-semibold text-brasa">
                marque “conteúdo gerado por IA”
              </strong>{" "}
              — a API de rascunho não deixa o worker marcar isso, e sem o rótulo
              o vídeo pode ser removido.
            </p>
          )}

          {pub.url && (
            <a
              href={pub.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-3 inline-block text-sm text-brasa underline underline-offset-4"
            >
              Abrir no {PLATAFORMA[pub.plataforma]}
            </a>
          )}
        </li>
      ))}
    </ul>
  );
}
