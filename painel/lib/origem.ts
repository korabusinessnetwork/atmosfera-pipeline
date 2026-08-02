import { headers } from "next/headers";

/**
 * O endereço público deste app, do ponto de vista de quem pediu a página.
 *
 * Serve para montar o `emailRedirectTo` do magic link. Chumbar a URL numa
 * variável de ambiente daria login quebrado em preview da Vercel (cada deploy
 * tem host próprio) e link apontando para produção quando se testa em
 * localhost. Ler do header resolve os dois casos com uma linha.
 *
 * `x-forwarded-*` antes de `host`: atrás do proxy da Vercel, `host` é o host
 * interno. NEXT_PUBLIC_SITE_URL fica como último recurso — não como primeiro.
 */
export async function origemDaRequisicao(): Promise<string> {
  const cabecalhos = await headers();

  const origem = cabecalhos.get("origin");
  if (origem) return origem;

  const host = cabecalhos.get("x-forwarded-host") ?? cabecalhos.get("host");
  if (host) {
    const protocolo =
      cabecalhos.get("x-forwarded-proto") ??
      (host.startsWith("localhost") ? "http" : "https");
    return `${protocolo}://${host}`;
  }

  return process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
}

/**
 * Só caminho interno.
 *
 * O `next` chega pela query string do link do e-mail — a parte do fluxo que
 * qualquer um consegue montar e mandar para outra pessoa. `//evil.com` e
 * `https://evil.com` são endereços de outro host que o navegador seguiria de
 * bom grado, e o open redirect sai de um domínio que a pessoa reconhece,
 * logo depois de um login que funcionou.
 */
export function caminhoInterno(bruto: string | null): string {
  if (!bruto) return "/";
  if (!bruto.startsWith("/")) return "/";
  if (bruto.startsWith("//") || bruto.startsWith("/\\")) return "/";
  return bruto;
}
