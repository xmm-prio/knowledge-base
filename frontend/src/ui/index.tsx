/** The design primitives. Pages compose these and never restyle them. */

import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import css from "./ui.module.css";

function classes(...names: (string | false | undefined | null)[]): string {
  return names.filter(Boolean).join(" ");
}

export type ButtonTone = "default" | "primary" | "danger" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: ButtonTone;
  small?: boolean;
}

export function Button({ tone = "default", small, className, ...rest }: ButtonProps) {
  const toneClass =
    tone === "primary" ? css.primary : tone === "danger" ? css.danger : tone === "ghost" ? css.ghost : null;
  return (
    <button
      type="button"
      {...rest}
      className={classes(css.button, toneClass, small && css.small, className)}
    />
  );
}

export function Card({
  children,
  tight,
  className,
}: {
  children: ReactNode;
  tight?: boolean;
  className?: string;
}) {
  return <div className={classes(css.card, tight && css.cardTight, className)}>{children}</div>;
}

export function Panel({
  title,
  note,
  actions,
  children,
  className,
}: {
  title: ReactNode;
  note?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={classes(css.panel, className)}>
      <header className={css.panelHead}>
        <div className={css.panelTitle}>{title}</div>
        {actions ?? (note ? <div className={css.panelNote}>{note}</div> : null)}
      </header>
      {children}
    </section>
  );
}

export function Tag({
  children,
  to,
  accent,
}: {
  children: ReactNode;
  to?: string;
  accent?: boolean;
}) {
  const className = classes(css.tag, accent && css.tagAccent);
  return to ? (
    <Link className={className} to={to}>
      {children}
    </Link>
  ) : (
    <span className={className}>{children}</span>
  );
}

export function TagRow({ children }: { children: ReactNode }) {
  return <div className={css.tagRow}>{children}</div>;
}

export function Loading({ label = "加载中…" }: { label?: string }) {
  return (
    <div className={css.state}>
      <div className={css.spinner} />
      <div>{label}</div>
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className={css.state}>
      <div className={css.stateTitle}>{title}</div>
      {hint ? <div>{hint}</div> : null}
    </div>
  );
}

/** Failures always show the backend's own `detail`; the heading only frames it. */
export function ErrorNotice({ error, title = "请求失败" }: { error: unknown; title?: string }) {
  const status = error instanceof ApiError && error.status ? `HTTP ${error.status}` : null;
  const detail = error instanceof Error ? error.message : String(error);
  return (
    <div className={css.error}>
      <div className={css.errorHead}>
        {title}
        {status ? ` · ${status}` : ""}
      </div>
      <div className={css.errorDetail}>{detail}</div>
    </div>
  );
}

/** The code domain's "the call graph may have holes" note. Never hidden. */
export function Caveat({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  return (
    <div className={css.caveat}>
      <span className={css.caveatMark}>注意</span>
      <span>{text}</span>
    </div>
  );
}

export type Health = "ok" | "bad" | "unknown";

export function Badge({ tone, children }: { tone: Health | "neutral"; children: ReactNode }) {
  const toneClass =
    tone === "ok"
      ? css.badgeOk
      : tone === "bad"
        ? css.badgeBad
        : tone === "unknown"
          ? css.badgeUnknown
          : css.badgeNeutral;
  return <span className={classes(css.badge, toneClass)}>{children}</span>;
}

export function Dot({ tone }: { tone: Health }) {
  const toneClass = tone === "ok" ? css.dotOk : tone === "bad" ? css.dotBad : css.dotUnknown;
  return <span className={classes(css.dot, toneClass)} />;
}

export function Input({ large, ...props }: InputHTMLAttributes<HTMLInputElement> & { large?: boolean }) {
  return <input {...props} className={classes(css.input, large && css.inputLarge, props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={classes(css.select, props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={classes(css.textarea, props.className)} />;
}

export function Field({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <label className={css.field}>
      <span className={css.fieldLabel}>{label}</span>
      {children}
    </label>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className={css.segmented}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={classes(css.segment, option.value === value && css.segmentOn)}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function CopyButton({
  text,
  label = "复制",
  small,
}: {
  text: string;
  label?: string;
  small?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      small={small}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
        } catch {
          // Clipboard permission is not something the page can recover from; the fallback
          // is the text itself, which is already on screen.
        }
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? "已复制" : label}
    </Button>
  );
}
