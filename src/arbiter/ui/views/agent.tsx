"use client";

import {
  Bot,
  BrainCircuit,
  Check,
  Circle,
  ListTree,
  LoaderCircle,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  User,
  Wrench,
  XCircle,
} from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { PageHeader, Panel } from "@/components/ui";
import { streamJsonLines } from "@/lib/api";
import type { JsonRecord } from "@/lib/types";

type StepStatus = "running" | "completed" | "error" | "cancelled";

interface AgentStep {
  id: string;
  kind: string;
  title: string;
  detail?: string;
  status: StepStatus;
  tool?: string;
  arguments?: unknown;
  result?: unknown;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  evidence?: unknown;
  steps?: AgentStep[];
  pending?: boolean;
  approvalRequired?: boolean;
}

interface AgentStreamEvent extends JsonRecord {
  type: string;
  step_id?: string;
  kind?: string;
  title?: string;
  detail?: string;
  status?: StepStatus;
  tool?: string;
  arguments?: unknown;
  result?: unknown;
  message?: string;
  response?: JsonRecord;
}

const suggestions = [
  "What changed in my environment recently?",
  "Which projects have port conflicts?",
  "What is using port 5432?",
];

function eventText(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function applyEvent(message: Message, event: AgentStreamEvent): Message {
  if (event.type === "step_started" || event.type === "step_completed") {
    const id = eventText(event.step_id, `step-${Date.now()}`);
    const current = message.steps ?? [];
    const existing = current.find((step) => step.id === id);
    const next: AgentStep = {
      id,
      kind: eventText(event.kind, existing?.kind ?? "status"),
      title: eventText(event.title, existing?.title ?? "Agent step"),
      detail: eventText(event.detail, existing?.detail),
      status: event.type === "step_started" ? "running" : event.status ?? "completed",
      tool: eventText(event.tool, existing?.tool),
      arguments: event.arguments ?? existing?.arguments,
      result: event.result ?? existing?.result,
    };
    const steps = existing ? current.map((step) => (step.id === id ? next : step)) : [...current, next];
    return { ...message, steps };
  }
  if (event.type === "run_error") {
    return {
      ...message,
      content: eventText(event.message, "The agent run failed."),
      steps: message.steps?.map((step) => (step.status === "running" ? { ...step, status: "error" } : step)),
    };
  }
  if (event.type === "final" && event.response) {
    const response = event.response;
    const content = String(
      response.answer ?? response.message ?? response.response ?? response.summary ?? JSON.stringify(response, null, 2),
    );
    const degraded = response.status === "degraded";
    return {
      ...message,
      content,
      evidence: response.evidence ?? response.observations ?? response.data,
      approvalRequired: Boolean(response.approval_required),
      pending: false,
      steps: message.steps?.map((step) =>
        step.status === "running" ? { ...step, status: degraded ? "error" : "completed" } : step,
      ),
    };
  }
  return message;
}

function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function StepIcon({ step }: { step: AgentStep }) {
  if (step.status === "running") return <LoaderCircle className="spin" />;
  if (step.status === "error" || step.status === "cancelled") return <XCircle />;
  if (step.kind === "tool") return <Wrench />;
  if (step.kind === "model") return <BrainCircuit />;
  if (step.status === "completed") return <Check />;
  return <Circle />;
}

function RunSteps({ steps = [], pending = false }: { steps?: AgentStep[]; pending?: boolean }) {
  if (!steps.length) return null;
  const completed = steps.filter((step) => step.status === "completed").length;
  return (
    <section className="agent-trace" aria-label="Agent execution trace">
      <header>
        <span><ListTree /> Execution trace</span>
        <small>{pending ? "Live" : `${completed}/${steps.length} completed`}</small>
      </header>
      <div className="trace-list">
        {steps.map((step) => (
          <article className={`trace-step ${step.status}`} key={step.id}>
            <span className="trace-marker"><StepIcon step={step} /></span>
            <div>
              <strong>{step.title}</strong>
              {step.detail ? <p>{step.detail}</p> : null}
              {step.arguments !== undefined || step.result !== undefined ? (
                <details>
                  <summary>{step.result !== undefined ? "Result" : "Arguments"}</summary>
                  <pre>{JSON.stringify(step.result ?? step.arguments, null, 2)}</pre>
                </details>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export function AgentView({ notify }: { notify: (message: string, tone?: string) => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const conversationEnd = useRef<HTMLDivElement | null>(null);

  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    void conversationEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function ask(message: string) {
    const trimmed = message.trim();
    if (!trimmed || loading) return;
    const userId = crypto.randomUUID();
    const assistantId = crypto.randomUUID();
    const abortController = new AbortController();
    controller.current = abortController;
    setMessages((current) => [
      ...current,
      { id: userId, role: "user", content: trimmed },
      { id: assistantId, role: "assistant", content: "", steps: [], pending: true },
    ]);
    setInput("");
    setLoading(true);
    try {
      await streamJsonLines<AgentStreamEvent>(
        "/agent/query/stream",
        { message: trimmed },
        (event) => setMessages((current) =>
          current.map((item) => (item.id === assistantId ? applyEvent(item, event) : item)),
        ),
        abortController.signal,
      );
    } catch (reason) {
      const cancelled = reason instanceof Error && reason.name === "AbortError";
      setMessages((current) => current.map((item) => item.id === assistantId ? {
        ...item,
        content: item.content || (cancelled ? "_Run stopped by user._" : "_The agent stream ended unexpectedly._"),
        pending: false,
        steps: item.steps?.map((step) =>
          step.status === "running" ? { ...step, status: cancelled ? "cancelled" : "error" } : step,
        ),
      } : item));
      if (!cancelled) notify(reason instanceof Error ? reason.message : "Agent query failed", "error");
    } finally {
      if (controller.current === abortController) controller.current = null;
      setLoading(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void ask(input);
  }

  return (
    <>
      <PageHeader
        eyebrow="Operational assistant"
        title="Arbiter"
        description="Ask questions against real local state. Follow each safe action as it happens; mutations still require approval."
      />
      <div className="agent-layout">
        <Panel className="agent-console">
          <div className="conversation">
            {!messages.length ? (
              <div className="agent-empty">
                <span><Sparkles /></span>
                <h2>What do you need to know?</h2>
                <p>I inspect live processes, ports, containers, and configuration before answering.</p>
                <div className="suggestion-row">
                  {suggestions.map((suggestion) => <button key={suggestion} onClick={() => void ask(suggestion)}>{suggestion}</button>)}
                </div>
              </div>
            ) : messages.map((message) => (
              <div className={`message ${message.role}`} key={message.id}>
                <span>{message.role === "user" ? <User /> : <Bot />}</span>
                <div className="message-copy">
                  <strong>{message.role === "user" ? "You" : "Arbiter"}</strong>
                  {message.role === "assistant" ? (
                    <>
                      <RunSteps steps={message.steps} pending={message.pending} />
                      {message.content ? <MarkdownMessage content={message.content} /> : message.pending ? <p className="agent-waiting">Working…</p> : null}
                      {message.approvalRequired ? <div className="approval-callout"><ShieldCheck /> Approval is waiting in the safety queue.</div> : null}
                    </>
                  ) : <p>{message.content}</p>}
                  {message.evidence ? <details className="final-evidence"><summary>Supporting evidence</summary><pre>{JSON.stringify(message.evidence, null, 2)}</pre></details> : null}
                </div>
              </div>
            ))}
            <div ref={conversationEnd} />
          </div>
          <form className="agent-composer" onSubmit={submit}>
            <textarea
              rows={2}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void ask(input); }
              }}
              placeholder="Ask what owns a port, find conflicts, or prepare a workspace…"
            />
            <button
              type={loading ? "button" : "submit"}
              disabled={!loading && !input.trim()}
              onClick={loading ? () => controller.current?.abort() : undefined}
              aria-label={loading ? "Stop agent" : "Send"}
              className={loading ? "stop" : ""}
            >
              {loading ? <Square /> : <Send />}
            </button>
          </form>
        </Panel>
        <aside className="agent-rail">
          <Panel>
            <span className="rail-icon"><ShieldCheck /></span>
            <h2>Safety Gate Disclaimer</h2>
            <p>Changes may require explicit approval depending on organizational policies.</p>
          </Panel>
          <Panel>
            <span className="rail-icon trace"><ListTree /></span>
            <h2>Execution Trace</h2>
            <p>Execution steps are logged for auditing purposes.</p>
          </Panel>
          <Panel><span className="eyebrow">Good prompts</span>{suggestions.map((suggestion) => <button key={suggestion} onClick={() => void ask(suggestion)}>{suggestion}</button>)}</Panel>
        </aside>
      </div>
    </>
  );
}
