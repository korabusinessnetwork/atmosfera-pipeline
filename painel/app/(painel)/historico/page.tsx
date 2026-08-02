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
