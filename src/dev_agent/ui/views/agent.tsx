"use client";

import { Bot, Send, ShieldCheck, Sparkles, User } from "lucide-react";
import { FormEvent, useState } from "react";

import { PageHeader, Panel } from "@/components/ui";
import { post } from "@/lib/api";
import type { JsonRecord } from "@/lib/types";

interface Message { role: "user" | "assistant"; content: string; evidence?: unknown }

const suggestions = ["What changed in my environment recently?", "Which projects have port conflicts?", "What is using port 5432?"];

export function AgentView({ notify }: { notify: (message: string, tone?: string) => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function ask(message: string) {
    const trimmed = message.trim();
    if (!trimmed || loading) return;
    setMessages((current) => [...current, { role: "user", content: trimmed }]);
    setInput("");
    setLoading(true);
    try {
      const result = await post<JsonRecord>("/agent/query", { message: trimmed });
      const content = String(result.answer ?? result.message ?? result.response ?? result.summary ?? JSON.stringify(result, null, 2));
      setMessages((current) => [...current, { role: "assistant", content, evidence: result.evidence ?? result.observations ?? result.data }]);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Agent query failed", "error"); }
    finally { setLoading(false); }
  }

  function submit(event: FormEvent) { event.preventDefault(); void ask(input); }

  return (
    <>
      <PageHeader eyebrow="Operational assistant" title="Environment agent" description="Ask questions against real local state. Mutations always pass through the approval queue." />
      <div className="agent-layout">
        <Panel className="agent-console">
          <div className="conversation">
            {!messages.length ? <div className="agent-empty"><span><Sparkles /></span><h2>What do you need to know?</h2><p>I inspect live processes, ports, containers, and configuration before answering.</p><div className="suggestion-row">{suggestions.map((suggestion) => <button key={suggestion} onClick={() => void ask(suggestion)}>{suggestion}</button>)}</div></div> : messages.map((message, index) => <div className={`message ${message.role}`} key={index}><span>{message.role === "user" ? <User /> : <Bot />}</span><div><strong>{message.role === "user" ? "You" : "Environment agent"}</strong><p>{message.content}</p>{message.evidence ? <details><summary>Supporting evidence</summary><pre>{JSON.stringify(message.evidence, null, 2)}</pre></details> : null}</div></div>)}
            {loading ? <div className="message assistant typing"><span><Bot /></span><div><strong>Environment agent</strong><p><i /><i /><i /></p></div></div> : null}
          </div>
          <form className="agent-composer" onSubmit={submit}><textarea rows={2} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void ask(input); } }} placeholder="Ask what owns a port, find conflicts, or prepare a workspace…" /><button disabled={!input.trim() || loading} aria-label="Send"><Send /></button></form>
        </Panel>
        <aside className="agent-rail"><Panel><span className="rail-icon"><ShieldCheck /></span><h2>Approval protected</h2><p>Medium and higher-risk changes require your explicit decision. The agent can inspect freely, but it cannot silently cross the safety gate.</p></Panel><Panel><span className="eyebrow">Good prompts</span>{suggestions.map((suggestion) => <button key={suggestion} onClick={() => void ask(suggestion)}>{suggestion}</button>)}</Panel></aside>
      </div>
    </>
  );
}
