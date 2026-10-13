"use client";
export default function ErrorPage({reset}: {reset: () => void}) { return <main className="standalone"><h1>Não foi possível abrir esta página</h1><p>Os dados da API podem estar temporariamente indisponíveis.</p><button className="button primary" onClick={reset}>Tentar novamente</button></main>; }

