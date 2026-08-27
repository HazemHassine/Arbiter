"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { CubeIcon as AlertTriangle, CubeIcon as Box, QuestionMarkCircledIcon as CircleHelp, BoxIcon as Container, CodeIcon as FileCode2, Link2Icon as Folder, Share2Icon as Network, RadiobuttonIcon as Radio, MagnifyingGlassIcon as Route, CodeIcon as Terminal, MixerHorizontalIcon as Wrench } from "@radix-ui/react-icons";
import * as React from "react";

import { classes, statusTone } from "@/lib/format";

export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
}: {
  title: string;
  description: string;
  eyebrow?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions ? <div className="heading-actions">{actions}</div> : null}
    </header>
  );
}

export function Panel({ children, className, as: Element = "article" }: { children: ReactNode; className?: string; as?: "article" | "section" | "aside" }) {
  return <Element className={classes("panel", className)}>{children}</Element>;
}

export function PanelHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <header className="panel-head">
      <div>
        <h2>{title}</h2>
        {description ? <p>{description}</p> : null}
      </div>
      {action}
    </header>
  );
}

export function StatusBadge({ value, dot = true }: { value: unknown; dot?: boolean }) {
  const label = String(value || "unknown");
  return (
    <span className={classes("status-badge", statusTone(value))}>
      {dot ? <i /> : null}
      {label.replaceAll("_", " ")}
    </span>
  );
}

export function MetricCard({ label, value, note, icon: Icon, tone = "blue" }: { label: string; value: ReactNode; note: ReactNode; icon: React.FC<any>; tone?: string }) {
  return (
    <article className="metric-card">
      <div className={classes("metric-icon", tone)}><Icon /></div>
      <div className="metric-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        <p>{note}</p>
      </div>
    </article>
  );
}

export function EmptyState({ title = "Nothing here yet", description, icon: Icon = CircleHelp }: { title?: string; description?: string; icon?: React.FC<any> }) {
  return (
    <div className="empty-state">
      <Icon />
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
    </div>
  );
}

export function LoadingRows({ count = 4 }: { count?: number }) {
  return <div className="loading-rows" aria-label="Loading">{Array.from({ length: count }, (_, index) => <i key={index} />)}</div>;
}

export function ErrorNotice({ message, onRetry }: { message: string | null; onRetry?: () => void }) {
  if (!message) return null;
  return (
    <div className="error-notice" role="alert">
      <AlertTriangle />
      <span>{message}</span>
      {onRetry ? <button type="button" onClick={onRetry}>Try again</button> : null}
    </div>
  );
}

export function Button({ className, variant = "secondary", children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger" }) {
  return <button className={classes("button", variant, className)} type="button" {...props}>{children}</button>;
}

const resourceIcons: Record<string, React.FC<any>> = {
  project: Folder,
  compose_project: Network,
  compose_service: Box,
  container: Container,
  image: Box,
  volume: Box,
  network: Network,
  port: Route,
  process: Terminal,
  dockerfile: FileCode2,
  compose_file: FileCode2,
  makefile: Wrench,
  make_target: Wrench,
  runtime: Radio,
};

export function ResourceGlyph({ type, size = "medium" }: { type: string; size?: "small" | "medium" | "large" }) {
  const Icon = resourceIcons[type] ?? CircleHelp;
  return <span className={classes("resource-glyph", type, size)}><Icon /></span>;
}

export function KeyValue({ label, value }: { label: string; value: ReactNode }) {
  return <div className="key-value"><span>{label}</span><strong>{value}</strong></div>;
}

export function SearchInput({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return (
    <label className="search-input">
      <span aria-hidden="true" />
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
    </label>
  );
}
