import Link from 'next/link';

export default function HomePage() {
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col justify-center px-6 py-20">
      <p className="mb-4 font-mono text-sm text-fd-muted-foreground">LOCAL DEVELOPMENT CONTROL PLANE</p>
      <h1 className="max-w-3xl text-4xl font-bold tracking-tight sm:text-6xl">Understand conflicts. Reconcile them safely.</h1>
      <p className="mt-6 max-w-2xl text-lg text-fd-muted-foreground">
        Arbiter connects projects, containers, processes, ports, and configuration into one evidence-backed workflow:
        observe, diagnose, propose, approve, act, and verify.
      </p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link href="/docs" className="rounded-lg bg-fd-primary px-5 py-3 font-medium text-fd-primary-foreground">
          Read the documentation
        </Link>
        <a
          href="https://github.com/HazemHassine/dev-environment-agent"
          className="rounded-lg border px-5 py-3 font-medium"
        >
          View on GitHub
        </a>
      </div>
      <pre className="mt-10 overflow-x-auto rounded-xl border bg-fd-card p-5 text-left text-sm">
        <code>{`cp .env.example .env\nuv sync --extra dev\nuv run arbiter serve`}</code>
      </pre>
    </main>
  );
}
