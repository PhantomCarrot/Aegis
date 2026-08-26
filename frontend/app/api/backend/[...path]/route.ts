/**
 * Generic BFF proxy to the self-hosted Aegis backend.
 *
 * The browser never talks to the backend directly: no real URL or token is
 * ever exposed client-side. This Route Handler runs on the Next.js server,
 * reads AEGIS_BACKEND_URL / AEGIS_BACKEND_TOKEN (never prefixed with
 * NEXT_PUBLIC_*), and forwards the request with the Authorization header.
 *
 * See docs/architecture.md for the full flow diagram.
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.AEGIS_BACKEND_URL ?? "http://localhost:8765";
const BACKEND_TOKEN = process.env.AEGIS_BACKEND_TOKEN ?? "";

type Params = { path: string[] };

async function proxy(request: NextRequest, { params }: { params: Promise<Params> }) {
  const { path } = await params;

  const base = BACKEND_URL.endsWith("/") ? BACKEND_URL : `${BACKEND_URL}/`;
  const target = new URL(path.join("/"), base);
  target.search = request.nextUrl.search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  if (BACKEND_TOKEN) {
    headers.set("Authorization", `Bearer ${BACKEND_TOKEN}`);
  }

  const hasBody = !["GET", "HEAD"].includes(request.method);

  let response: Response;
  try {
    response = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.text() : undefined,
      // @ts-expect-error — required to forward a body on the Node runtime
      duplex: hasBody ? "half" : undefined,
    });
  } catch (reason) {
    const message = reason instanceof Error ? reason.message : "Backend unreachable";
    return NextResponse.json({ error: message }, { status: 502 });
  }

  // Streaming pass-through: NEVER buffer this as text — /api/chat responds
  // with SSE (Server-Sent Events) and the proxy must forward bytes as they
  // arrive, not wait for the response to finish.
  const responseHeaders = new Headers(response.headers);
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("content-length");
  responseHeaders.delete("transfer-encoding");
  responseHeaders.delete("connection");

  return new NextResponse(response.body, {
    status: response.status,
    headers: responseHeaders,
  });
}

export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
};
